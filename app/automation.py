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

    def stop(self) -> None:
        self.stop_event.set()
        self.backend.up()

    def pause(self, value: bool = True) -> None:
        if value:
            if self.clock:
                self.clock.pause()
            self.pause_event.set()
            self._interrupted.set()
            self.backend.up()
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
        slider = self.profile.brush_slider
        if not slider or not slider.readout:
            self._move(x, y)
            return
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
        feedback = self.profile.brush_slider is not None and self.profile.brush_slider.readout is not None
        if feedback:
            self._wait(plan.timing.control_hold)
        self._guard()
        try:
            self.backend.down()
            self._wait(plan.timing.control_hold if feedback else plan.timing.event)
        finally:
            self.backend.up()
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

    def _read_brush(self, expected, plan):
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
            if value is not None and slider.minimum <= value <= slider.maximum and value == previous:
                return value
            previous = value
            self._wait(max(.15, plan.timing.control_settle/2))
        self._brush_failure(expected, previous, "Число не распознано уверенно или ещё меняется.")

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
            self._wait(plan.timing.control_settle)
        self._guard()
        try:
            self.backend.down()
            self._wait(plan.timing.control_hold if feedback else plan.timing.event)
            length = math.dist(origin, destination)
            steps = max(1, math.ceil(length/3 if feedback else length/6))
            for i in range(1, steps+1):
                self._move(ox+round(origin[0]+(destination[0]-origin[0])*i/steps),
                           oy+round(origin[1]+(destination[1]-origin[1])*i/steps))
                self._wait(max(.025, length/steps/plan.timing.control_speed)
                           if feedback else plan.timing.event)
            if feedback:
                self._wait(plan.timing.control_hold)
        finally:
            self.backend.up()
        self._wait(plan.timing.control_settle if feedback else plan.timing.settle)

    def _set_brush(self, width, plan):
        slider = self.profile.brush_slider
        if not slider:
            if self.profile.size_tab:
                self._click(self.profile.size_tab, plan)
            self._click(next(b.point for b in self.profile.brushes if b.pixels == width), plan)
            self._width = width
            return
        if self.profile.color_tab:
            self._click(self.profile.color_tab, plan)
        if not slider.readout:
            self._drag_slider(slider.point(width), plan, False)
            self._width = width
            return
        current = self._read_brush(width, plan)
        if current != width:
            # The direct position is only an initial guess; the displayed number is authoritative.
            destination = slider.point(width)
            low, high = min(slider.start[0], slider.end[0]), max(slider.start[0], slider.end[0])
            for attempt in range(4):
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
                arrow = slider.increase if current < width else slider.decrease
                self._click(arrow, plan)
                clicks += 1
                observed = self._read_brush(width, plan)
                if observed == current:
                    self._brush_failure(width, observed, "Бесплатная стрелка размера не сработала.")
                current = observed
            if current != width:
                self._brush_failure(width, current, "Не удалось выставить точный размер бесплатным регулятором.")
        self._width = width

    def check_brushes(self, plan, widths, progress=lambda *_: None):
        """Exercise only free brush controls; never move onto the drawing canvas."""
        if not widths or not self.profile.brush_slider or not self.profile.brush_slider.readout:
            raise SafetyError("Для проверки нужны размеры и область числа бесплатного ползунка")
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
                        self.backend.up()
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
            self.backend.up()

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
            if ((not self.profile.color_wheel and stroke.color not in colors)
                    or len(stroke.color) != 3 or any(not 0 <= c <= 255 for c in stroke.color)
                    or stroke.width not in widths or stroke.opacity != 1):
                raise SafetyError("План содержит некалиброванные цвета, размеры или прозрачность")
            if not stroke.points:
                raise SafetyError("Пустой штрих")
            for p in stroke.points:
                canvas.map(p, stroke.width / 2 + 1)

    def run(self, plan: Plan, progress=lambda *_: None, state=lambda *_: None,
            time_limit: float | None = None, require_verified: bool = True,
            deadline: float | None = None, clock_origin: float | None = None) -> str:
        if self.stop_event.is_set():
            self.backend.up()
            state("IDLE")
            return "stopped"
        self.validate_plan(plan, require_verified)
        self._deadline = None
        self._session = self._guard()
        self._color = self._width = None
        self._tool_selected = False
        started = time.monotonic()
        self._deadline = deadline if deadline is not None else (started+time_limit if time_limit is not None else None)
        from app.smart_timer import DrawingClock, costs, transition_cost
        self.clock = DrawingClock(None if self._deadline is None else max(0., self._deadline-started))
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
                    self.backend.up()
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
                    self.backend.up()
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
            self.backend.up()
            self.run_metrics = {**self.clock.snapshot(), "actual": measured_actual,
                                "predicted": measured_prediction, "strokes": len(self.executed_indices),
                                "skipped": len(self.skipped_indices), "draw_seconds": self._pen_seconds}

    def _execute(self, stroke: Stroke, plan: Plan, started: float,
                 time_limit: float | None) -> None:
        color_changed = self._color != stroke.color
        if not self._tool_selected and self.profile.brush_tool:
            self._click(self.profile.brush_tool, plan)
            self._tool_selected = True
        if self._color != stroke.color:
            if self.profile.color_tab:
                self._click(self.profile.color_tab, plan)
            wheel = self.profile.color_wheel
            if wheel:
                if wheel.mode_button:
                    self._click(wheel.mode_button, plan)
                for point in wheel.points(stroke.color):
                    self._click(point, plan)
            else:
                swatch = next(s for s in self.profile.swatches if s.rgb == stroke.color)
                for anchor in self.profile.anchors:
                    if anchor.point == swatch.point:
                        self._check_anchor(anchor)
                self._click(swatch.point, plan)
            if self.profile.color_indicator:
                self._guard()
                assert self._session
                x, y = self.profile.color_indicator
                actual = self.backend.sample(self._session.client.x + x, self._session.client.y + y)
                if max(abs(a-b) for a, b in zip(actual, stroke.color)) > self.profile.color_tolerance:
                    raise SafetyError("Индикатор цвета не совпал с палитрой. Проверьте калибровку.")
            self._color = stroke.color
        feedback = self.profile.brush_slider and self.profile.brush_slider.readout
        if self._width != stroke.width or (feedback and color_changed):
            self._set_brush(stroke.width, plan)
        assert self._session
        canvas = plan.drawing_area(self.profile.canvas)
        local_points = [canvas.map(p, stroke.width / 2 + 1) for p in stroke.points]
        points = [(x + self._session.client.x, y + self._session.client.y) for x, y in local_points]
        self._travel(*points[0], plan)
        if feedback:
            self._wait(plan.timing.control_hold)
        self._guard()
        try:
            self._pen_started = time.monotonic()
            self.backend.down()
            self._wait(plan.timing.event)
            for a, b in zip(points, points[1:]):
                length = math.hypot(b[0] - a[0], b[1] - a[1])
                steps = max(1, math.ceil(length / plan.timing.sample_pixels))
                for i in range(1, steps + 1):
                    if self._deadline is not None and time.monotonic() >= self._deadline:
                        raise DeadlineReached("Достигнут лимит раунда")
                    x = round(a[0] + (b[0] - a[0]) * i / steps)
                    y = round(a[1] + (b[1] - a[1]) * i / steps)
                    self._move(x, y)
                    self._wait(plan.timing.event + length / steps / plan.timing.pixels_per_second)
        finally:
            self.backend.up()
            if self._pen_started is not None:
                self._pen_seconds += time.monotonic()-self._pen_started
                self._pen_started = None

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
