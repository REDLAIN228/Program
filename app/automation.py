from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time
from typing import Protocol

from app.models import Calibration, Plan, Rect, RGB, Stroke


class SafetyError(RuntimeError):
    pass


class DeadlineReached(SafetyError):
    pass


@dataclass(frozen=True)
class WindowState:
    handle: int
    title: str
    window_class: str
    process: str
    client: Rect  # Physical screen coordinates; may have negative origins.
    dpi: int


class InputBackend(Protocol):
    def snapshot(self) -> WindowState: ...
    def is_foreground(self) -> bool: ...
    def move(self, x: int, y: int) -> None: ...
    def down(self) -> None: ...
    def up(self) -> None: ...
    def sample(self, x: int, y: int) -> RGB: ...
    def point_belongs_to_target(self, x: int, y: int) -> bool: ...


class DrawingExecutor:
    """Interruptible ordinary-input runner. Resume replays an incomplete stroke."""

    def __init__(self, backend: InputBackend, profile: Calibration):
        from app.game_profile import restrict_game_profile
        restrict_game_profile(profile)
        profile.validate()
        self.backend = backend
        self.profile = profile
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self._interrupted = threading.Event()
        self.completed = 0
        self._session: WindowState | None = None
        self._color = None
        self._width = None
        self._tool_selected = False
        self._deadline = None
        self._pointer = None
        self.clock = None
        self.executed_indices = []
        self.skipped_indices = []
        self.run_metrics = dict(elapsed=0., active=0., paused=0., remaining=None, actual=0., predicted=0.,
                                strokes=0, skipped=0, draw_seconds=0.)
        self._pen_seconds = 0.
        self._pen_started = None
        self._released_at = None
        self._controls_ready = False
        self._last_hue = None
        self._opacity = None
        self._latency = 1.
        self._control_log = []
        self._observed_color = None
        self._popup = None
        if profile.popup_controls:
            from app.popup_controls import PopupController
            self._popup = PopupController(self)

    def _release(self):
        self.backend.up()
        self._released_at = time.monotonic()

    def _press(self, kind="control"):
        self._guard()
        cursor = getattr(self.backend, "cursor_position", None)
        self._control_log = (self._control_log+[dict(kind=kind, wanted=self._pointer, actual=cursor() if cursor else None,
                                                   latency=self._latency)])[-64:]
        down_at = getattr(self.backend, "down_at", None)
        if down_at and self._pointer is not None:
            down_at(*self._pointer)
        else:
            self.backend.down()
        self._released_at = None

    def _arrive(self, point, plan, *, pen_start=False):
        """Do not press while Windows or the game still sees the previous position."""
        if pen_start:
            # Reassert pen-up at the stationary start after leaving controls.
            # Do not let a slider's drag capture become the first paint stroke.
            self._release()
        self._wait(plan.timing.control_hold*self._latency)
        position = getattr(self.backend, "cursor_position", None)
        if position is None:
            return
        stable = 0
        for attempt in range(24):
            self._guard()
            actual = position()
            stable = stable+1 if math.dist(actual, point) <= 1 else 0
            if stable >= 2:
                return
            if attempt and attempt % 6 == 0:
                self._move(*point)
            self._wait(max(.025, plan.timing.game_delay/4))
        self._control_failure("cursor", point, position(),
                              "Курсор не дошёл до нужной точки. Нажатие отменено; увеличьте задержку игры.")

    def _control_failure(self, kind, expected, observed, reason):
        save = getattr(self.backend, "save_control_diagnostic", None)
        path = ""
        if save:
            try:
                path = " Снимок контролов: "+save(self.profile, dict(kind=kind, expected=expected,
                                                                  observed=observed, presses=self._control_log))
            except OSError:
                pass
        raise SafetyError(reason+path)

    def _open_controls(self, plan):
        if self._controls_ready:
            return
        if self.profile.color_tab:
            self._click(self.profile.color_tab, plan)
        wheel = self.profile.color_wheel
        if wheel:
            if wheel.mode_button:
                self._click(wheel.mode_button, plan)
            if wheel.value_reset:
                self._reset_value(plan)
        self._controls_ready = True

    def stop(self) -> None:
        self.stop_event.set()
        self._release()

    def pause(self, value: bool = True) -> None:
        if value:
            if self.clock:
                self.clock.pause()
            self.pause_event.set()
            self._interrupted.set()
            self._release()
        else:
            if self.clock:
                self.clock.resume()
            self.pause_event.clear()

    def _guard(self) -> WindowState:
        if self.stop_event.is_set():
            raise InterruptedError("Рисование остановлено")
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise DeadlineReached("Достигнут лимит раунда. Рисование остановлено.")
        state = self.backend.snapshot()
        p = self.profile
        if (state.client.width, state.client.height) != p.client_size or state.dpi != p.dpi:
            raise SafetyError("Размер окна или DPI изменились. Повторите калибровку.")
        if state.window_class != p.target_class or state.process.casefold() != p.target_process.casefold():
            raise SafetyError("Профиль относится к другому окну")
        if self._session and (state.handle, state.client, state.dpi) != (
                self._session.handle, self._session.client, self._session.dpi):
            raise SafetyError("Окно перемещено, изменено или закрыто. Рисование остановлено.")
        if not self.backend.is_foreground():
            raise SafetyError("Потерян фокус целевого окна. Рисование остановлено.")
        return state

    def _wait(self, seconds: float) -> None:
        if self._deadline is not None:
            remaining = self._deadline-time.monotonic()
            if remaining <= 0:
                raise DeadlineReached("Достигнут лимит раунда. Рисование остановлено.")
            seconds = min(seconds, remaining)
        if self.stop_event.wait(seconds):
            raise InterruptedError("Рисование остановлено")
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise DeadlineReached("Достигнут лимит раунда. Рисование остановлено.")
        if self.pause_event.is_set() or self._interrupted.is_set():
            raise _Paused()

    def _move(self, x: int, y: int) -> None:
        self._guard()
        if self.pause_event.is_set() or self._interrupted.is_set():
            raise _Paused()
        if not self.backend.point_belongs_to_target(x, y):
            raise SafetyError("Холст перекрыт другим окном. Рисование остановлено.")
        assert self._session
        if any(r.contains(x-self._session.client.x, y-self._session.client.y) for r in self.profile.forbidden):
            raise SafetyError("Донатная область исключена из управления")
        self.backend.move(x, y)
        self._pointer = (x, y)

    def _travel(self, x: int, y: int, plan: Plan) -> None:
        """Move with the button released; drawing samples still use _move directly."""
        if not self.profile.feedback:
            self._move(x, y)
            return
        if self._released_at is None:
            self._release()
        self._wait(max(0., plan.timing.pen_release*self._latency-(time.monotonic()-self._released_at)))
        self._guard()
        position = getattr(self.backend, "cursor_position", None)
        origin = position() if position else self._pointer
        # The first cursor position can be outside the game. Enter the target
        # without clicking; all subsequent travel is sampled and checked.
        if origin is None or not self.backend.point_belongs_to_target(*origin):
            self._move(x, y)
            return
        assert self._session
        if any(r.contains(origin[0]-self._session.client.x, origin[1]-self._session.client.y)
               for r in self.profile.forbidden):
            self._move(x, y)
            return
        from app.cursor import travel_path
        ox, oy = self._session.client.x, self._session.client.y
        try:
            route = travel_path((origin[0]-ox, origin[1]-oy), (x-ox, y-oy),
                                Rect(0, 0, *self.profile.client_size), self.profile.forbidden)
        except ValueError as exc:
            raise SafetyError(str(exc)) from exc
        for px, py in route:
            destination = (px+ox, py+oy)
            length = math.dist(origin, destination)
            # Turbo uses larger mouse-up samples rather than flooding Windows
            # with waits shorter than its scheduling resolution.
            sample = max(6, plan.timing.control_speed*.01)
            steps = max(1, math.ceil(length/sample))
            for index in range(1, steps+1):
                self._move(round(origin[0]+(destination[0]-origin[0])*index/steps),
                           round(origin[1]+(destination[1]-origin[1])*index/steps))
                self._wait(length/steps/plan.timing.control_speed)
            origin = destination

    def _click(self, point: tuple[int, int], plan: Plan) -> None:
        assert self._session
        x, y = point
        self._travel(self._session.client.x + x, self._session.client.y + y, plan)
        self._guard()
        feedback = self.profile.feedback
        if feedback:
            self._arrive((self._session.client.x+x, self._session.client.y+y), plan)
        self._guard()
        try:
            self._press()
            self._wait(plan.timing.control_hold*self._latency if feedback else plan.timing.event)
        finally:
            self._release()
        self._wait(plan.timing.control_settle if feedback else plan.timing.settle)

    def _brush_failure(self, expected, observed, reason):
        diagnostic = getattr(self.backend, "save_size_diagnostic", None)
        path = ""
        if diagnostic:
            try:
                path = " Снимок числа: "+diagnostic(expected, observed)
            except OSError:
                pass
        actual = str(observed) if observed is not None else "не прочитан"
        raise SafetyError(f"Размер кисти: запрошен {expected}, в игре {actual}. {reason} "
                          "Рисование остановлено до штриха."+path)

    def _read_brush(self, expected, plan, changed_from=None):
        """Read a stable size, allowing delayed UI updates after an arrow click."""
        slider = self.profile.brush_slider
        assert slider and slider.readout and self._session
        reader = getattr(self.backend, "read_brush_size", None)
        if reader is None:
            self._brush_failure(expected, None, "Нет проверки числа размера.")
        r = slider.readout
        area = Rect(self._session.client.x+r.x, self._session.client.y+r.y, r.width, r.height)
        previous = None
        for attempt in range(12):
            self._guard()
            for x, y in [(area.x, area.y), (area.x+area.width-1, area.y+area.height-1)]:
                if not self.backend.point_belongs_to_target(x, y):
                    self._brush_failure(expected, None, "Число размера перекрыто другим окном.")
            value = reader(area)
            if (value is not None and slider.minimum <= value <= slider.maximum and value == previous
                    and (value != changed_from or attempt >= 5)):
                return value
            previous = value
            self._wait(max(.15, plan.timing.control_settle/2))
        self._brush_failure(expected, previous, "Число не распознано уверенно или ещё меняется.")

    def _read_opacity(self, expected, plan, changed_from=None):
        slider = self.profile.opacity_slider
        reader = getattr(self.backend, "read_opacity", None)
        if not slider or not slider.readout or reader is None:
            raise SafetyError("Для непрозрачности нужен готовый игровой профиль и чтение процента.")
        r, origin = slider.readout, self._session.client
        area = Rect(origin.x+r.x, origin.y+r.y, r.width, r.height)
        previous = None
        for attempt in range(12):
            self._guard()
            if not all(self.backend.point_belongs_to_target(x, y) for x, y in
                       [(area.x, area.y), (area.x+area.width-1, area.y+area.height-1)]):
                raise SafetyError("Процент непрозрачности перекрыт другим окном")
            value = reader(area)
            if (value is not None and 1 <= value <= 100 and value == previous
                    and (value != changed_from or attempt >= 5)):
                return value
            previous = value
            self._wait(max(.15, plan.timing.control_settle/2))
        self._control_failure("opacity", expected, previous,
                              f"Непрозрачность {expected}% не подтверждена по числу в игре. Штрих отменён.")

    def _set_opacity(self, percent, plan):
        slider = self.profile.opacity_slider
        if not slider:
            if percent != 100:
                raise SafetyError("В профиле нет регулятора непрозрачности")
            return
        self._open_controls(plan)
        current = self._read_opacity(percent, plan)
        for drag_attempt in range(3):
            if abs(current-percent) <= 4:
                break
            before_drag = current
            ox, oy = self._session.client.x, self._session.client.y
            start, end = slider.point(current), slider.point(percent)
            self._travel(ox+start[0], oy+start[1], plan)
            self._arrive((ox+start[0], oy+start[1]), plan)
            try:
                self._press()
                self._wait(plan.timing.control_hold*self._latency)
                steps = max(1, math.ceil(math.dist(start, end)/2))
                for i in range(1, steps+1):
                    self._move(ox+round(start[0]+(end[0]-start[0])*i/steps),
                               oy+round(start[1]+(end[1]-start[1])*i/steps))
                    self._wait(max(.025, plan.timing.game_delay/4))
                self._wait(plan.timing.control_hold*self._latency)
            finally:
                self._release()
            self._wait(plan.timing.control_settle)
            current = self._read_opacity(percent, plan)
            if current == before_drag:
                self._latency = min(3., self._latency+.5)
                self._wait(plan.timing.control_settle*self._latency)
                current = self._read_opacity(percent, plan)
        for step in range(24):
            if current == percent:
                self._opacity = percent
                return
            arrow = slider.increase if current < percent else slider.decrease
            before = current
            for attempt in range(3):
                if attempt:
                    self._latency = min(3., self._latency+.5)
                    current = self._read_opacity(percent, plan)
                    if current != before:
                        break
                self._click(arrow, plan)
                current = self._read_opacity(percent, plan, changed_from=before)
                if current != before:
                    break
            if current == before:
                break
        if current == percent:
            self._opacity = percent
            return
        self._control_failure("opacity", percent, current,
                              f"Непрозрачность: запрошено {percent}%, в игре {current}%. Штрих отменён.")

    def _step_brush(self, current, width, plan):
        """Retry missed free-arrow input; never paint using an unconfirmed width."""
        slider = self.profile.brush_slider
        assert slider
        arrow = slider.increase if current < width else slider.decrease
        for attempt in range(3):
            if attempt:
                self._wait(max(.2, plan.timing.control_settle))
                # A late update may arrive after the preceding read. Recheck
                # before retrying so it cannot cause an extra size increment.
                observed = self._read_brush(width, plan)
                if observed != current:
                    return observed
            self._click(arrow, plan)
            observed = self._read_brush(width, plan, changed_from=current)
            if observed != current:
                return observed
            self._latency = min(3., self._latency+.5)
        self._brush_failure(width, current, "Бесплатная стрелка размера не сработала после 3 попыток.")

    def _drag_slider(self, destination, plan, feedback):
        slider = self.profile.brush_slider
        assert slider and self._session
        ox, oy = self._session.client.x, self._session.client.y
        origin = slider.point(self._width) if self._width is not None else slider.start
        locator = getattr(self.backend, "slider_thumb", None)
        if locator:
            self._guard()
            found = locator((ox+slider.start[0], oy+slider.start[1]), (ox+slider.end[0], oy+slider.end[1]))
            if found is None:
                raise SafetyError("Не найден синий бегунок бесплатного размера кисти. "
                                  "Откройте Цвет → Колесо, закройте список стилей и повторите TEST DRAW.")
            origin = found[0]-ox, found[1]-oy
        self._travel(ox+origin[0], oy+origin[1], plan)
        if feedback:
            self._arrive((ox+origin[0], oy+origin[1]), plan)
        self._guard()
        try:
            self._press()
            self._wait(plan.timing.control_hold*self._latency if feedback else plan.timing.event)
            length = math.dist(origin, destination)
            steps = max(1, math.ceil(length/3 if feedback else length/6))
            for i in range(1, steps+1):
                self._move(ox+round(origin[0]+(destination[0]-origin[0])*i/steps),
                           oy+round(origin[1]+(destination[1]-origin[1])*i/steps))
                self._wait(max(.025, length/steps/plan.timing.control_speed)
                           if feedback else plan.timing.event)
            if feedback:
                self._wait(plan.timing.control_hold*self._latency)
        finally:
            self._release()
        self._wait(plan.timing.control_settle if feedback else plan.timing.settle)

    def _set_brush(self, width, plan):
        if self._popup:
            self._popup.set_width(width, plan)
            return
        slider = self.profile.brush_slider
        if not slider:
            if self.profile.size_tab:
                self._click(self.profile.size_tab, plan)
            self._click(next(b.point for b in self.profile.brushes if b.pixels == width), plan)
            self._width = width
            return
        self._open_controls(plan)
        if not slider.readout:
            self._drag_slider(slider.point(width), plan, False)
            self._width = width
            return
        current = self._read_brush(width, plan)
        if current != width:
            # The direct position is only an initial guess; the displayed number is authoritative.
            destination = slider.point(width)
            low, high = min(slider.start[0], slider.end[0]), max(slider.start[0], slider.end[0])
            # At this slider's resolution adjacent small sizes can share a
            # screen pixel. Use exact arrows directly for nearby sizes.
            for attempt in range(4 if abs(current-width) > 8 else 0):
                self._drag_slider(destination, plan, True)
                current = self._read_brush(width, plan)
                if current == width or abs(current-width) <= 8:
                    break
                if current < width:
                    low = max(low, destination[0]+1)
                else:
                    high = min(high, destination[0]-1)
                if low > high:
                    break
                destination = ((low+high)//2, slider.start[1])
            clicks = 0
            while current != width and clicks < 32:
                current = self._step_brush(current, width, plan)
                clicks += 1
            if current != width:
                self._brush_failure(width, current, "Не удалось выставить точный размер бесплатным регулятором.")
        self._width = width

    def park_pointer(self, plan):
        """Release and move outside the canvas before taking comparison images."""
        while True:
            try:
                return self._park_pointer(plan)
            except _Paused:
                self._release()
                while self.pause_event.is_set():
                    self._guard()
                    if self.stop_event.wait(.025):
                        raise InterruptedError("Рисование остановлено")
                self._interrupted.clear()

    def _park_pointer(self, plan):
        if self._session is None:
            self._session = self._guard()
        self._release()
        self._wait(plan.timing.pen_release*self._latency)
        r = self.profile.canvas
        bounds = Rect(0, 0, *self.profile.client_size)
        candidates = [(r.x-10, r.y-10), (r.x+r.width+10, r.y-10),
                      (r.x-10, r.y+r.height+10), (10, 10),
                      (bounds.width-11, bounds.height-11)]
        for x, y in candidates:
            if (bounds.contains(x, y) and not r.contains(x, y)
                    and not any(area.contains(x, y) for area in self.profile.forbidden)):
                self._travel(self._session.client.x+x, self._session.client.y+y, plan)
                self._wait(max(.12, plan.timing.settle))
                return True
        return False  # A canvas covering the entire client has no parking area.

    def check_brushes(self, plan, widths, progress=lambda *_: None):
        """Exercise only free brush controls; never move onto the drawing canvas."""
        if not widths or not self.profile.feedback:
            raise SafetyError("Для проверки нужны размеры и область числа бесплатного ползунка")
        if self.profile.brush_slider:
            for width in widths:
                self.profile.brush_slider.point(width)
        self._session = self._guard()
        self._deadline = time.monotonic()+120
        try:
            for index, width in enumerate(widths):
                if width not in {b.pixels for b in self.profile.brushes}:
                    raise SafetyError("Размер не калиброван")
                while True:
                    try:
                        self._set_brush(width, plan)
                        break
                    except _Paused:
                        self._release()
                        while self.pause_event.is_set():
                            if self.stop_event.wait(.025):
                                raise InterruptedError("Проверка остановлена")
                        self._interrupted.clear()
                        self._guard()
                        self._width = None
                progress((index+1)/len(widths), f"Размер {width} подтверждён по числу в игре")
            return "Размеры "+", ".join(map(str, widths))+" подтверждены. Теперь выполните TEST DRAW."
        except InterruptedError:
            return "Проверка размера остановлена."
        finally:
            self._release()

    def validate_plan(self, plan: Plan, require_verified: bool = True) -> None:
        if self.profile.brush_slider:
            for brush in self.profile.brushes:
                self.profile.brush_slider.point(brush.pixels)
        if require_verified and not self.profile.verified:
            raise SafetyError("Сначала выполните TEST DRAW и подтвердите калибровку")
        try:
            canvas = plan.drawing_area(self.profile.canvas)
        except ValueError as exc:
            raise SafetyError(str(exc)) from exc
        colors = {s.rgb for s in self.profile.swatches}
        widths = {b.pixels for b in self.profile.brushes}
        for stroke in plan.strokes:
            if ((not self.profile.dynamic_color and stroke.color not in colors)
                    or len(stroke.color) != 3 or any(not 0 <= c <= 255 for c in stroke.color)
                    or stroke.width not in widths or not math.isfinite(stroke.opacity)
                    or not .01 <= stroke.opacity <= 1
                    or (stroke.opacity != 1 and not self.profile.opacity_slider)):
                raise SafetyError("План содержит некалиброванные цвета, размеры или прозрачность")
            if not stroke.points:
                raise SafetyError("Пустой штрих")
            for p in stroke.points:
                canvas.map(p, stroke.width / 2 + 1)

    def run(self, plan: Plan, progress=lambda *_: None, state=lambda *_: None,
            time_limit: float | None = None, require_verified: bool = True,
            deadline: float | None = None, clock_origin: float | None = None) -> str:
        if self.stop_event.is_set():
            self._release()
            state("IDLE")
            return "stopped"
        self.validate_plan(plan, require_verified)
        self._deadline = None
        self._session = self._guard()
        self._color = self._width = None
        self._opacity = None
        self._controls_ready = False
        self._last_hue = None
        self._tool_selected = False
        started = time.monotonic()
        self._deadline = deadline if deadline is not None else (started+time_limit if time_limit is not None else None)
        from app.smart_timer import DrawingClock, costs, transition_cost
        self.clock = DrawingClock(None if self._deadline is None else max(0., self._deadline-started))
        self.total_strokes = len(plan.strokes)
        if clock_origin is not None:
            self.clock.started = clock_origin
            self.clock.limit = None if self._deadline is None else max(0., self._deadline-clock_origin)
        prices = costs(plan)
        suffix = [0.]*(len(prices)+1)
        for index in range(len(prices)-1, -1, -1):
            suffix[index] = suffix[index+1]+prices[index]
        observed_factor = 1.
        fill_groups = {}
        for index, stroke in enumerate(plan.strokes):
            if stroke.priority == 1:
                fill_groups.setdefault((stroke.color, stroke.component_id), []).append(index)
        fill_prices = {key: sum(prices[i] for i in indices) for key, indices in fill_groups.items()}
        fill_scores = {key: sum(plan.strokes[i].importance for i in indices)/len(indices)
                       for key, indices in fill_groups.items()}
        started_fills, skipped_fills = set(), set()
        future_skipped_price = 0.
        measured_actual = measured_prediction = 0.
        self.executed_indices, self.skipped_indices = [], []
        pause_seconds = 0.
        try:
            if not self.profile.color_tab:
                for anchor in self.profile.anchors:
                    self._check_anchor(anchor)
            state("DRAWING")
            while self.completed < len(plan.strokes):
                if self.pause_event.is_set() or self._interrupted.is_set():
                    self._release()
                    state("PAUSED")
                    pause_start = time.monotonic()
                    if self.pause_event.is_set():
                        self.clock.pause()
                    while self.pause_event.is_set():
                        if self._deadline is not None and time.monotonic() >= self._deadline:
                            raise DeadlineReached("Лимит раунда истёк во время паузы")
                        if self.stop_event.wait(.025):
                            raise InterruptedError("Рисование остановлено")
                    pause_seconds += time.monotonic() - pause_start
                    self.clock.resume()
                    self._interrupted.clear()
                    # Never steal focus back on resume.
                    self._guard()
                    self._color = self._width = None
                    self._opacity = None
                    self._controls_ready = False
                    self._last_hue = None
                    self._tool_selected = False
                    state("DRAWING")
                elapsed = time.monotonic() - started  # Round timer continues during pause.
                if self._deadline is not None and time.monotonic() >= self._deadline:
                    raise DeadlineReached("Достигнут лимит раунда. Рисование остановлено.")
                stroke = plan.strokes[self.completed]
                fill_key = (stroke.color, stroke.component_id) if stroke.priority == 1 else None
                if fill_key in skipped_fills:
                    future_skipped_price -= prices[self.completed]
                    self.skipped_indices.append(self.completed)
                    self.completed += 1
                    continue
                previous = plan.strokes[self.executed_indices[-1]] if self.executed_indices else None
                if previous is not None and (self._color != previous.color or self._width != previous.width):
                    previous = None  # Resume resets the tool cache; include selection again.
                current_price = transition_cost(plan, stroke, previous)
                if plan.smart_finish and self._deadline is not None:
                    available = self._deadline-time.monotonic()-plan.safety_buffer
                    predicted = current_price*observed_factor
                    low_priority = (stroke.priority != 1 and
                                    (stroke.importance < 35 or (stroke.priority >= 2 and stroke.importance < 65)))
                    remaining_price = max(0., suffix[self.completed]-future_skipped_price)*observed_factor
                    if fill_key is not None and fill_key not in started_fills:
                        whole_fill = (fill_prices[fill_key]+max(0, current_price-prices[self.completed]))*observed_factor
                        secondary = fill_scores[fill_key] < 65
                        if available < whole_fill or (secondary and available < remaining_price):
                            state("SMART FINISH")
                            if secondary:
                                skipped_fills.add(fill_key)
                                future_skipped_price += fill_prices[fill_key]-prices[self.completed]
                                self.skipped_indices.append(self.completed)
                                self.completed += 1
                                continue
                            state("TIME LIMIT")
                            return "deadline"
                    if available < predicted or (low_priority and available < remaining_price):
                        state("SMART FINISH")
                        if low_priority:
                            self.skipped_indices.append(self.completed)
                            self.completed += 1
                            continue
                        state("TIME LIMIT")
                        return "deadline"
                stroke_started = time.monotonic()
                if fill_key is not None:
                    started_fills.add(fill_key)  # A paused partial fill must be replayed, never silently dropped.
                try:
                    self._execute(stroke, plan, started, time_limit)
                except _Paused:
                    self._release()
                    continue
                duration = time.monotonic()-stroke_started
                self.executed_indices.append(self.completed)
                measured_actual += duration
                measured_prediction += current_price/plan.time_factor
                if current_price > .05:
                    ratio = max(.25, min(4., duration/current_price))
                    observed_factor = .8*observed_factor+.2*ratio
                self.completed += 1
                elapsed = time.monotonic()-started
                progress(len(self.executed_indices), len(plan.strokes), elapsed,
                         suffix[self.completed]*observed_factor)
            state("FINISHED" if not self.skipped_indices else "FINISHED PARTIAL")
            return "finished" if not self.skipped_indices else "partial"
        except DeadlineReached:
            if not plan.smart_finish:
                raise
            state("TIME LIMIT")
            return "deadline"
        except InterruptedError:
            state("IDLE")
            return "stopped"
        finally:
            self._release()
            self.run_metrics = {**self.clock.snapshot(), "actual": measured_actual,
                                "predicted": measured_prediction, "strokes": len(self.executed_indices),
                                "skipped": len(self.skipped_indices), "draw_seconds": self._pen_seconds}

    def _palette_marker(self, kind):
        locator = getattr(self.backend, "color_control_marker", None)
        if locator:
            self._guard()
            point = locator(self.profile.color_wheel, kind)
            if point is not None:
                return point
        return None

    def _drag_palette(self, path, plan):
        """Generate real mouse movement while held; a stationary click may do nothing."""
        assert self._session
        ox, oy = self._session.client.x, self._session.client.y
        self._travel(ox+path[0][0], oy+path[0][1], plan)
        self._arrive((ox+path[0][0], oy+path[0][1]), plan)
        try:
            self._press()
            self._control_log[-1]["drag_to"] = (ox+path[-1][0], oy+path[-1][1])
            self._wait(plan.timing.control_hold*self._latency)
            for a, b in zip(path, path[1:]):
                distance = math.dist(a, b)
                steps = max(1, math.ceil(distance/6))
                for i in range(1, steps+1):
                    self._move(ox+round(a[0]+(b[0]-a[0])*i/steps),
                               oy+round(a[1]+(b[1]-a[1])*i/steps))
                    self._wait(plan.timing.palette_event(distance/steps))
            self._wait(plan.timing.control_hold*self._latency)
        finally:
            self._release()
        self._wait(plan.timing.control_settle*self._latency)

    def _reset_value(self, plan):
        wheel = self.profile.color_wheel
        if not wheel or not wheel.value_reset:
            return
        if not wheel.value_end:
            self._click(wheel.value_reset, plan)
            return
        start = self._palette_marker("value") or wheel.value_end
        if math.dist(start, wheel.value_reset) <= 2:
            return  # The visible selector already confirms maximum brightness.
        self._drag_palette([start, wheel.value_reset], plan)

    def _select_color(self, color, plan, recover=False):
        self._open_controls(plan)
        wheel = self.profile.color_wheel
        if wheel:
            if recover:
                self._reset_value(plan)
            points = wheel.points(color)
            if max(color) != min(color) and points[0] != self._last_hue:
                marker = self._palette_marker("hue")
                start = marker or self._last_hue or wheel.red
                if marker is None or math.dist(start, points[0]) > 1:
                    cx, cy = wheel.center
                    radius = math.dist(wheel.center, wheel.red)
                    angle = math.atan2(start[1]-cy, start[0]-cx)
                    end = math.atan2(points[0][1]-cy, points[0][0]-cx)
                    delta = (end-angle+math.pi) % (2*math.pi)-math.pi
                    count = max(2, math.ceil(abs(delta)*radius/6))
                    path = [start]+[(round(cx+radius*math.cos(angle+delta*i/count)),
                                     round(cy+radius*math.sin(angle+delta*i/count))) for i in range(1, count+1)]
                    if math.dist(start, points[0]) <= 1:
                        path = [start, (round(cx+radius*math.cos(angle+.04)),
                                        round(cy+radius*math.sin(angle+.04))), points[0]]
                    path[-1] = points[0]
                    self._drag_palette(path, plan)
                self._last_hue = points[0]
            r = wheel.square
            start = self._palette_marker("square") or (r.x+r.width//2, r.y+r.height//2)
            path = [start, points[-1]]
            if start == points[-1]:
                path.insert(1, (r.x+r.width//2, r.y+r.height//2))
            self._drag_palette(path, plan)
        else:
            swatch = next(s for s in self.profile.swatches if s.rgb == color)
            for anchor in self.profile.anchors:
                if anchor.point == swatch.point:
                    self._check_anchor(anchor)
            self._click(swatch.point, plan)

    def _color_matches(self, color, plan):
        if not self.profile.color_indicator:
            return True
        assert self._session
        x, y = self.profile.color_indicator
        x, y = x+self._session.client.x, y+self._session.client.y
        matches = 0
        for attempt in range(6):
            self._guard()
            if not self.backend.point_belongs_to_target(x, y):
                raise SafetyError("Индикатор цвета перекрыт другим окном")
            actual = self.backend.sample(x, y)
            self._observed_color = actual
            matches = matches+1 if max(abs(a-b) for a, b in zip(actual, color)) <= self.profile.color_tolerance else 0
            if matches >= 2:
                return True
            self._wait(max(.05 if matches else .12, plan.timing.event))
        return False

    @staticmethod
    def _toward(start, end, distance):
        length = math.dist(start, end)
        fraction = min(1., distance/length)
        return tuple(round(a+(b-a)*fraction) for a, b in zip(start, end))

    def _enter_stroke(self, points, plan):
        """Prime the game's cached pointer along the stroke, with the pen up.

        An OS cursor check cannot detect a game retaining the previous move.
        Make the last distinct moves belong to the first segment, so a cached
        point cannot connect the UI-to-canvas approach to the painted line.
        """
        start = points[0]
        following = next((point for point in points[1:] if point != start), None)
        if following is None:
            self._travel(*start, plan)
        else:
            lead = self._toward(start, following, 8)
            middle = self._toward(start, following, 4)
            path = [lead, middle, start]
            if lead == middle or middle == start:
                # A one-pixel segment has only two distinct valid positions.
                path = [following, start, following, start]
            self._travel(*path[0], plan)
            for point in path[1:]:
                self._move(*point)
                self._wait(plan.timing.pen_refresh)
        self._arrive(start, plan, pen_start=True)

    def _finish_stroke(self, points, plan):
        # A game painting the previous move also needs the endpoint flushed.
        # Retrace only the last two pixels inside the existing final segment.
        end = points[-1]
        previous = next((point for point in reversed(points[:-1]) if point != end), None)
        if previous is not None:
            self._move(*self._toward(end, previous, 2))
            self._wait(plan.timing.pen_refresh)
            self._move(*end)
            self._wait(plan.timing.pen_refresh)

    def _execute(self, stroke: Stroke, plan: Plan, started: float,
                 time_limit: float | None) -> None:
        if self._popup:
            self._popup.prepare(stroke.color, stroke.width, plan)
        else:
            self._prepare_controls(stroke, plan)
        feedback = self.profile.feedback
        assert self._session
        canvas = plan.drawing_area(self.profile.canvas)
        local_points = [canvas.map(p, stroke.width / 2 + 1) for p in stroke.points]
        points = [(x + self._session.client.x, y + self._session.client.y) for x, y in local_points]
        if feedback:
            self._enter_stroke(points, plan)
        else:
            self._travel(*points[0], plan)
        self._guard()
        try:
            self._pen_started = time.monotonic()
            self._press(kind="stroke")
            self._wait(plan.timing.pen_hold*self._latency if feedback else plan.timing.event)
            for a, b in zip(points, points[1:]):
                length = math.hypot(b[0] - a[0], b[1] - a[1])
                steps = max(1, math.ceil(length / plan.timing.pen_sample(stroke.width, bool(feedback))))
                for i in range(1, steps + 1):
                    if self._deadline is not None and time.monotonic() >= self._deadline:
                        raise DeadlineReached("Достигнут лимит раунда")
                    x = round(a[0] + (b[0] - a[0]) * i / steps)
                    y = round(a[1] + (b[1] - a[1]) * i / steps)
                    self._move(x, y)
                    self._wait(plan.timing.pen_event(stroke.width, bool(feedback))
                               + length / steps / plan.timing.pixels_per_second)
            if feedback:
                if stroke.opacity == 1:
                    self._finish_stroke(points, plan)
                self._wait(plan.timing.pen_hold*self._latency)
        finally:
            self._release()
            if self._pen_started is not None:
                self._pen_seconds += time.monotonic()-self._pen_started
                self._pen_started = None
        if feedback:
            self._wait(plan.timing.pen_release*self._latency)

    def _prepare_controls(self, stroke, plan):
        color_changed = self._color != stroke.color
        if not self._tool_selected and self.profile.brush_tool:
            self._click(self.profile.brush_tool, plan)
            self._tool_selected = True
        if color_changed:
            self._open_controls(plan)
            # Some game indicators fade with brush opacity. Confirm each new
            # hue at 100%, then restore the requested drawing opacity.
            if self.profile.opacity_slider and self._opacity != 100:
                self._set_opacity(100, plan)
            if (self._color is not None or not self.profile.color_indicator
                    or not self._color_matches(stroke.color, plan)):
                self._select_color(stroke.color, plan)
        feedback = self.profile.brush_slider and self.profile.brush_slider.readout
        controls_changed = color_changed or self._width != stroke.width
        if self._width != stroke.width or (feedback and color_changed):
            self._set_brush(stroke.width, plan)
        if controls_changed and self._opacity in (None, 100) and not self._color_matches(stroke.color, plan):
            self._latency = min(3., self._latency+.5)
            self._last_hue = None
            self._select_color(stroke.color, plan, recover=True)
            if feedback:
                self._set_brush(stroke.width, plan)
            if not self._color_matches(stroke.color, plan):
                self._control_failure("color", stroke.color, self._observed_color,
                                      f"Индикатор цвета не совпал: нужен {stroke.color}, в игре {self._observed_color}. "
                                      "Рисование остановлено до штриха. Проверьте Цвет → Колесо и профиль.")
        self._color = stroke.color
        percent = round(stroke.opacity*100)
        if self.profile.opacity_slider and self._opacity != percent:
            self._set_opacity(percent, plan)

    def _check_anchor(self, anchor) -> None:
        self._guard()
        assert self._session
        x, y = anchor.point
        x, y = x + self._session.client.x, y + self._session.client.y
        if not self.backend.point_belongs_to_target(x, y):
            raise SafetyError("Палитра перекрыта другим окном")
        actual = self.backend.sample(x, y)
        if max(abs(a-b) for a, b in zip(actual, anchor.rgb)) > 55:
            raise SafetyError("Изменилась палитра или расположение интерфейса. Повторите CALIBRATE / TEST DRAW.")


class _Paused(Exception):
    pass
