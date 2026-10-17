from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time
from typing import Protocol

from app.models import Calibration, Plan, Rect, RGB, Stroke


class SafetyError(RuntimeError):
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

    def stop(self) -> None:
        self.stop_event.set()
        self.backend.up()

    def pause(self, value: bool = True) -> None:
        if value:
            self.pause_event.set()
            self._interrupted.set()
            self.backend.up()
        else:
            self.pause_event.clear()

    def _guard(self) -> WindowState:
        if self.stop_event.is_set():
            raise InterruptedError("Рисование остановлено")
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise SafetyError("Достигнут лимит раунда. Рисование остановлено.")
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
        if self.stop_event.wait(seconds):
            raise InterruptedError("Рисование остановлено")
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

    def _click(self, point: tuple[int, int], plan: Plan) -> None:
        assert self._session
        x, y = point
        self._move(self._session.client.x + x, self._session.client.y + y)
        self._guard()
        try:
            self.backend.down()
            self._wait(plan.timing.event)
        finally:
            self.backend.up()
        self._wait(plan.timing.settle)

    def validate_plan(self, plan: Plan, require_verified: bool = True) -> None:
        if self.profile.brush_slider:
            for brush in self.profile.brushes:
                self.profile.brush_slider.point(brush.pixels)
        if require_verified and not self.profile.verified:
            raise SafetyError("Сначала выполните TEST DRAW и подтвердите калибровку")
        if plan.canvas_size != (self.profile.canvas.width, self.profile.canvas.height):
            raise SafetyError("План создан для другого размера холста. Выполните PREVIEW заново.")
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
                self.profile.canvas.map(p, stroke.width / 2 + 1)

    def run(self, plan: Plan, progress=lambda *_: None, state=lambda *_: None,
            time_limit: float | None = None, require_verified: bool = True) -> str:
        self.validate_plan(plan, require_verified)
        self._deadline = None
        self._session = self._guard()
        self._color = self._width = None
        self._tool_selected = False
        started = time.monotonic()
        self._deadline = started+time_limit if time_limit is not None else None
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
                    while self.pause_event.is_set():
                        if self.stop_event.wait(.025):
                            raise InterruptedError("Рисование остановлено")
                    pause_seconds += time.monotonic() - pause_start
                    self._interrupted.clear()
                    # Never steal focus back on resume.
                    self._guard()
                    self._color = self._width = None
                    self._tool_selected = False
                    state("DRAWING")
                elapsed = time.monotonic() - started  # Round timer continues during pause.
                if time_limit is not None and elapsed >= time_limit:
                    raise SafetyError("Достигнут лимит раунда. Рисование остановлено.")
                stroke = plan.strokes[self.completed]
                try:
                    self._execute(stroke, plan, started, time_limit)
                except _Paused:
                    self.backend.up()
                    continue
                self.completed += 1
                active = max(.001, elapsed - pause_seconds)
                progress(self.completed, len(plan.strokes), elapsed,
                         (len(plan.strokes) - self.completed) * active / self.completed)
            state("FINISHED")
            return "finished"
        except InterruptedError:
            state("IDLE")
            return "stopped"
        finally:
            self.backend.up()

    def _execute(self, stroke: Stroke, plan: Plan, started: float,
                 time_limit: float | None) -> None:
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
        if self._width != stroke.width:
            slider = self.profile.brush_slider
            if slider:
                # Reopen the free panel even when color did not change between strokes.
                if self.profile.color_tab:
                    self._click(self.profile.color_tab, plan)
                destination = slider.point(stroke.width)
                origin = slider.point(self._width) if self._width is not None else slider.start
                assert self._session
                ox, oy = self._session.client.x, self._session.client.y
                locator = getattr(self.backend, "slider_thumb", None)
                if locator:
                    self._guard()
                    found = locator((ox+slider.start[0], oy+slider.start[1]),
                                    (ox+slider.end[0], oy+slider.end[1]))
                    if found is None:
                        raise SafetyError("Не найден синий бегунок бесплатного размера кисти. "
                                          "Откройте Цвет → Колесо, закройте список стилей и повторите TEST DRAW.")
                    origin = found[0]-ox, found[1]-oy
                self._move(ox+origin[0], oy+origin[1])
                try:
                    self.backend.down()
                    self._wait(plan.timing.event)
                    steps = max(1, math.ceil(math.dist(origin, destination)/8))
                    for i in range(1, steps+1):
                        self._move(ox+round(origin[0]+(destination[0]-origin[0])*i/steps),
                                   oy+round(origin[1]+(destination[1]-origin[1])*i/steps))
                        self._wait(plan.timing.event)
                finally:
                    self.backend.up()
                self._wait(plan.timing.settle)
            else:
                if self.profile.size_tab:
                    self._click(self.profile.size_tab, plan)
                brush = next(b for b in self.profile.brushes if b.pixels == stroke.width)
                self._click(brush.point, plan)
            self._width = stroke.width
        assert self._session
        canvas = self.profile.canvas
        local_points = [canvas.map(p, stroke.width / 2 + 1) for p in stroke.points]
        points = [(x + self._session.client.x, y + self._session.client.y) for x, y in local_points]
        self._move(*points[0])
        self._guard()
        try:
            self.backend.down()
            self._wait(plan.timing.event)
            for a, b in zip(points, points[1:]):
                length = math.hypot(b[0] - a[0], b[1] - a[1])
                steps = max(1, math.ceil(length / plan.timing.sample_pixels))
                for i in range(1, steps + 1):
                    if time_limit is not None and time.monotonic() - started >= time_limit:
                        raise SafetyError("Достигнут лимит раунда")
                    x = round(a[0] + (b[0] - a[0]) * i / steps)
                    y = round(a[1] + (b[1] - a[1]) * i / steps)
                    self._move(x, y)
                    self._wait(plan.timing.event + length / steps / plan.timing.pixels_per_second)
        finally:
            self.backend.up()

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
