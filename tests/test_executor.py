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
