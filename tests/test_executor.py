from dataclasses import replace
import threading
import time

import pytest

from app.automation import DrawingExecutor, SafetyError, WindowState
from app.models import Plan, Rect, Stroke, Swatch, Timing


class Backend:
    def __init__(self):
        self.state = WindowState(123, "test", "TestClass", "test.exe", Rect(-200, 40, 400, 400), 96)
        self.focus = True
        self.occluded = False
        self.pressed = False
        self.events = []
        self.hook = lambda: None

    def snapshot(self):
        return self.state

    def is_foreground(self):
        return self.focus

    def point_belongs_to_target(self, x, y):
        return not self.occluded and self.state.client.contains(x, y)

    def move(self, x, y):
        self.events.append(("move", x, y))
        self.hook()

    def down(self):
        self.pressed = True
        self.events.append(("down",))

    def up(self):
        self.pressed = False
        self.events.append(("up",))

    def sample(self, x, y):
        return (0, 0, 0)


def plan():
    return Plan((300, 280), [Stroke(((.1, .1), (.9, .9)), (20, 20, 28), 3)],
                Timing(.0001, .0001, 1000000, 10), .1, "a", [(20, 20, 28)])


def test_executor_selects_tools_and_translates_to_negative_monitor(profile):
    backend = Backend()
    executor = DrawingExecutor(backend, profile)
    assert executor.run(plan()) == "finished"
    assert executor.completed == 1
    assert not backend.pressed
    assert backend.events[0] == ("move", -180, 60)  # Color selection, client->screen.
    assert sum(event[0] == "down" for event in backend.events) == 3
    drawing = backend.events[8:]
    assert any(e[0] == "move" and e[1] < 0 for e in drawing)


@pytest.mark.parametrize("failure", ["focus", "dpi", "geometry", "occlusion", "identity"])
def test_executor_releases_button_on_safety_failure(profile, failure):
    backend = Backend()
    def hook():
        if backend.pressed:
            if failure == "focus": backend.focus = False
            elif failure == "dpi": backend.state = replace(backend.state, dpi=144)
            elif failure == "geometry": backend.state = replace(backend.state, client=Rect(-199, 40, 400, 400))
            elif failure == "occlusion": backend.occluded = True
            elif failure == "identity": backend.state = replace(backend.state, process="other.exe")
    backend.hook = hook
    executor = DrawingExecutor(backend, profile)
    with pytest.raises(SafetyError):
        executor.run(plan())
    assert not backend.pressed
    assert executor.completed == 0


def test_indicator_mismatch_and_unverified_calibration_rejected(profile):
    backend = Backend()
    profile.verified = False
    executor = DrawingExecutor(backend, profile)
    with pytest.raises(SafetyError, match="TEST DRAW"):
        executor.run(plan())
    profile.verified = True
    profile.color_indicator = (30, 30)
    profile.color_tolerance = 1
    with pytest.raises(SafetyError, match="Индикатор"):
        executor.run(plan())
    assert not backend.pressed


def test_stop_releases_immediately(profile):
    backend = Backend()
    executor = DrawingExecutor(backend, profile)
    backend.hook = lambda: executor.stop() if backend.pressed else None
    assert executor.run(plan()) == "stopped"
    assert not backend.pressed
    assert executor.completed == 0


def test_pause_releases_mouse_and_resume_replays_incomplete_stroke(profile):
    backend = Backend()
    executor = DrawingExecutor(backend, profile)
    paused = threading.Event()
    def hook():
        if backend.pressed and not paused.is_set():
            executor.pause()
            paused.set()
    backend.hook = hook
    outcomes = []
    thread = threading.Thread(target=lambda: outcomes.append(executor.run(plan())))
    thread.start()
    assert paused.wait(2)
    assert not backend.pressed
    assert executor.completed == 0
    executor.pause(False)
    thread.join(3)
    assert not thread.is_alive()
    assert outcomes == ["finished"]
    assert executor.completed == 1
    assert not backend.pressed
    assert sum(e[0] == "down" for e in backend.events) >= 4


def test_uncalibrated_colors_sizes_and_changed_canvas_refused(profile):
    executor = DrawingExecutor(Backend(), profile)
    wrong_color = plan()
    wrong_color.strokes = [Stroke(((.1, .1),), (0, 255, 0), 3)]
    with pytest.raises(SafetyError): executor.validate_plan(wrong_color)
    wrong_width = plan()
    wrong_width.strokes = [Stroke(((.1, .1),), (20, 20, 28), 99)]
    with pytest.raises(SafetyError): executor.validate_plan(wrong_width)
    wrong_canvas = plan()
    wrong_canvas.canvas_size = (200, 200)
    with pytest.raises(SafetyError): executor.validate_plan(wrong_canvas)


def test_round_deadline_interrupts_a_stroke(profile):
    backend = Backend()
    executor = DrawingExecutor(backend, profile)
    with pytest.raises(SafetyError, match="лимит"):
        executor.run(plan(), time_limit=.00001)
    assert not backend.pressed


def test_layout_anchor_change_is_detected_before_any_click(profile):
    backend = Backend()
    profile.anchors = [Swatch((240, 54, 82), (50, 20))]
    with pytest.raises(SafetyError, match="расположение"):
        DrawingExecutor(backend, profile).run(plan())
    assert not any(e[0] == "down" for e in backend.events)


def test_custom_drawing_size_is_translated_to_canvas_center_and_stays_inside(profile):
    backend = Backend()
    drawing = plan()
    drawing.canvas_size = (100, 80)
    drawing.drawing_rect = Rect(100, 100, 100, 80)
    drawing.target_canvas_size = (300, 280)
    area = Rect(180, 200, 100, 80)
    pressed_points, point = [], [None]
    move, down = backend.move, backend.down
    def record_move(x, y):
        point[0] = (x, y)
        move(x, y)
        if backend.pressed:
            pressed_points.append((x, y))
    def record_down():
        down()
        if len([e for e in backend.events if e[0] == "down"]) == 3:
            pressed_points.append(point[0])
    backend.move, backend.down = record_move, record_down
    assert DrawingExecutor(backend, profile).run(drawing) == "finished"
    assert pressed_points
    origin = backend.state.client
    assert all(area.contains(x-origin.x, y-origin.y) for x, y in pressed_points)
    x, y = area.map(drawing.strokes[0].points[0], 2.5)
    assert pressed_points[0] == (origin.x+x, origin.y+y)
    drawing.drawing_rect = Rect(250, 100, 100, 80)
    backend.events.clear()
    with pytest.raises(SafetyError, match="границы"):
        DrawingExecutor(backend, profile).run(drawing)
    assert not backend.events


def test_smart_finish_will_not_start_a_stroke_that_cannot_fit(profile):
    backend = Backend()
    drawing = plan()
    drawing.smart_finish = True
    executor = DrawingExecutor(backend, profile)
    assert executor.run(drawing, time_limit=.0001) == "deadline"
    assert not any(event[0] == "down" for event in backend.events)
    assert not backend.pressed


def test_smart_finish_skips_secondary_work_and_reports_actual_completed_strokes(profile, monkeypatch):
    wait = DrawingExecutor._wait
    monkeypatch.setattr(DrawingExecutor, "_wait", lambda self, seconds: wait(self, 0))
    backend = Backend()
    low = Stroke(((.05, .1), (.95, .9)), (20, 20, 28), 3, priority=3, importance=10)
    high = Stroke(((.5, .5), (.51, .5)), (20, 20, 28), 3, priority=3, importance=100)
    drawing = Plan((300, 280), [low, high], Timing(.01, .01, 1000000, 10), 1, "x", [], smart_finish=True)
    executor = DrawingExecutor(backend, profile)
    assert executor.run(drawing, time_limit=.2) == "partial"
    assert executor.executed_indices == [1] and executor.skipped_indices == [0]
    assert executor.run_metrics["strokes"] == 1
    assert executor.run_metrics["predicted"] > 0 and not backend.pressed


def test_smart_finish_reserves_a_whole_fill_before_starting_it(profile, monkeypatch):
    wait = DrawingExecutor._wait
    monkeypatch.setattr(DrawingExecutor, "_wait", lambda self, seconds: wait(self, 0))
    backend = Backend()
    fills = [Stroke(((.5, y), (.51, y)), (20, 20, 28), 3, priority=1, importance=20, component_id=7)
             for y in (.2, .3)]
    face = Stroke(((.5, .5), (.51, .5)), (20, 20, 28), 3, priority=2, importance=100)
    drawing = Plan((300, 280), fills+[face], Timing(.01, .01, 1000000, 10), 1, "x", [], smart_finish=True)
    executor = DrawingExecutor(backend, profile)
    assert executor.run(drawing, time_limit=.18) == "partial"
    assert executor.executed_indices == [2] and executor.skipped_indices == [0, 1]


def test_absolute_round_deadline_overrides_a_stale_relative_limit(profile):
    backend = Backend()
    drawing = plan()
    drawing.smart_finish = True
    now = time.monotonic()
    executor = DrawingExecutor(backend, profile)
    assert executor.run(drawing, time_limit=1000, deadline=now-1, clock_origin=now-5) == "deadline"
    assert executor.run_metrics["elapsed"] >= 5 and executor.run_metrics["remaining"] == 0
    assert not any(e[0] == "down" for e in backend.events)


def test_paused_executor_observes_deadline_without_waiting_for_resume(profile, monkeypatch):
    from types import SimpleNamespace
    import app.automation as automation
    ticks = [0.]
    def monotonic():
        ticks[0] += .01
        return ticks[0]
    monkeypatch.setattr(automation, "time", SimpleNamespace(monotonic=monotonic))
    backend = Backend()
    drawing = plan()
    drawing.smart_finish = True
    executor = DrawingExecutor(backend, profile)
    executor.pause()
    monkeypatch.setattr(executor.stop_event, "wait", lambda seconds: False)
    assert executor.run(drawing, time_limit=.05) == "deadline"
    assert not backend.pressed and not any(e[0] == "down" for e in backend.events)
