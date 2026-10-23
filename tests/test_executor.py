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


class PaintingBackend(Backend):
    def __init__(self, canvas, enabled=True, delayed_frames=0):
        from PIL import Image
        super().__init__()
        self.canvas, self.enabled, self.delayed_frames = canvas, enabled, delayed_frames
        self.image = Image.new("RGB", (400, 400), "white")
        self.point, self.post_frames = (0, 0), 0

    def move(self, x, y):
        from PIL import ImageDraw
        local = (x-self.state.client.x, y-self.state.client.y)
        if self.pressed and self.enabled and self.canvas.contains(*local):
            ImageDraw.Draw(self.image).line([self.point, local], fill=(20, 20, 28), width=3)
        self.point = local
        super().move(x, y)

    def capture_region(self, r):
        from PIL import Image
        if any(e[0] == "down" for e in self.events) and not self.pressed:
            self.post_frames += 1
        if self.post_frames < self.delayed_frames:
            return Image.new("RGB", (r.width, r.height), "white")
        x, y = r.x-self.state.client.x, r.y-self.state.client.y
        return self.image.crop((x, y, x+r.width, y+r.height))


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


@pytest.mark.parametrize("failure", ["focus", "geometry", "occlusion", "closed", "hung"])
def test_auto_pause_keeps_completed_strokes_and_replays_failed_stroke(profile, failure):
    backend = Backend()
    original = backend.state
    backend.closed = backend.hung = False
    def snapshot():
        if backend.closed:
            raise SafetyError("Целевое окно закрыто")
        return backend.state
    backend.snapshot = snapshot
    backend.unavailable_reason = lambda: "Roblox не отвечает" if backend.hung else ""
    executor = DrawingExecutor(backend, profile)
    drawing = plan()
    drawing.strokes *= 2
    triggered = False
    def hook():
        nonlocal triggered
        if backend.pressed and executor.completed == 1 and not triggered:
            triggered = True
            if failure == "focus": backend.focus = False
            if failure == "geometry": backend.state = replace(original, client=Rect(-199, 40, 400, 400))
            if failure == "occlusion": backend.occluded = True
            if failure == "closed": backend.closed = True
            if failure == "hung": backend.hung = True
    backend.hook = hook
    paused = threading.Event()
    outcomes, errors, notices = [], [], []
    def run():
        try:
            outcomes.append(executor.run(drawing, auto_pause=True, notice=notices.append,
                                        state=lambda value: paused.set() if value == "PAUSED" else None))
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert paused.wait(2)
        assert executor.pause_event.is_set() and executor.pause_reason and notices
        assert not backend.pressed and executor.completed == 1 and executor.executed_indices == [0]
        count = len(backend.events)
        assert not threading.Event().wait(.05)
        assert len(backend.events) == count  # No retries, moves or clicks while unavailable.
        backend.focus, backend.occluded = True, False
        backend.closed = backend.hung = False
        backend.state = original
        executor.pause(False)
        thread.join(3)
        assert not thread.is_alive() and not errors and outcomes == ["finished"]
        assert executor.executed_indices == [0, 1] and executor.completed == 2
        assert not backend.pressed and not executor.pause_reason
    finally:
        executor.stop()
        thread.join(2)


def test_auto_pause_does_not_resume_itself_and_stop_works_with_closed_game(profile):
    backend = Backend()
    backend.focus = False
    executor = DrawingExecutor(backend, profile)
    paused = threading.Event()
    result = []
    thread = threading.Thread(target=lambda: result.append(executor.run(
        plan(), auto_pause=True, state=lambda value: paused.set() if value == "PAUSED" else None)))
    thread.start()
    try:
        assert paused.wait(2)
        backend.focus = True
        assert not threading.Event().wait(.05)
        assert executor.pause_event.is_set() and not any(e[0] == "down" for e in backend.events)
        backend.snapshot = lambda: (_ for _ in ()).throw(SafetyError("Окно закрыто"))
        executor.stop()
        thread.join(2)
        assert result == ["stopped"] and not thread.is_alive() and not backend.pressed
    finally:
        executor.stop()
        thread.join(2)


def test_rebind_after_restart_is_explicit_and_checks_profile_before_resume(profile):
    executor = DrawingExecutor(Backend(), profile)
    new = Backend()
    new.state = replace(new.state, handle=456, client=Rect(100, 100, 400, 400))
    with pytest.raises(SafetyError, match="паузе"):
        executor.rebind_target(new)
    executor.pause()
    new.state = replace(new.state, dpi=144)
    with pytest.raises(SafetyError, match="профилю"):
        executor.rebind_target(new)
    new.state = replace(new.state, dpi=96)
    executor.rebind_target(new)
    assert executor.backend is new and executor._session.handle == 456
    assert executor.pause_event.is_set() and executor._pointer is None


def test_auto_pause_never_masks_invalid_plan_or_round_deadline(profile):
    executor = DrawingExecutor(Backend(), profile)
    drawing = plan()
    drawing.strokes[0] = replace(drawing.strokes[0], width=999)
    with pytest.raises(SafetyError, match="некалиброванные"):
        executor.run(drawing, auto_pause=True)
    assert not executor.pause_event.is_set()
    drawing = plan()
    drawing.smart_finish = True
    assert executor.run(drawing, auto_pause=True, deadline=time.monotonic()-1) == "deadline"
    assert not executor.pause_event.is_set()


@pytest.mark.parametrize("delayed_render", [False, True])
def test_auto_pause_uses_visible_ink_and_allows_render_latency(profile, delayed_render):
    backend = PaintingBackend(profile.canvas, enabled=delayed_render, delayed_frames=3 if delayed_render else 0)
    executor = DrawingExecutor(backend, profile)
    paused, outcomes, errors = threading.Event(), [], []
    def run():
        try:
            outcomes.append(executor.run(plan(), auto_pause=True,
                            state=lambda value: paused.set() if value == "PAUSED" else None))
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        if not delayed_render:
            assert paused.wait(3)
            assert "след кисти" in executor.pause_reason
            assert executor.completed == 0 and not executor.executed_indices and not backend.pressed
            backend.enabled = True
            executor.pause(False)
        thread.join(3)
        assert not thread.is_alive() and not errors and outcomes == ["finished"]
        assert executor.completed == 1 and not backend.pressed
        if delayed_render:
            assert not paused.is_set() and backend.post_frames >= 3
    finally:
        executor.stop()
        thread.join(2)


def test_disconnect_between_screen_checks_replays_unconfirmed_tail(profile):
    backend = PaintingBackend(profile.canvas)
    executor = DrawingExecutor(backend, profile)
    drawing = plan()
    drawing.strokes = [Stroke(((.1, y), (.9, y)), (20, 20, 28), 3) for y in (.2, .4, .6, .8)]
    paused, outcomes, errors = threading.Event(), [], []
    def progress(done, *_):
        if not paused.is_set():
            backend.enabled = False
            executor._next_ink_check = 0 if done == 3 else time.monotonic()+10
    def run():
        try:
            outcomes.append(executor.run(drawing, progress=progress, auto_pause=True,
                            state=lambda value: paused.set() if value == "PAUSED" else None))
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert paused.wait(3)
        assert executor.completed == 1 and executor.executed_indices == [0]
        backend.enabled = True
        executor.pause(False)
        thread.join(3)
        assert not thread.is_alive() and not errors and outcomes == ["finished"]
        assert executor.executed_indices == [0, 1, 2, 3]
        for stroke in drawing.strokes:
            midpoint = profile.canvas.map((.5, stroke.points[0][1]), 2.5)
            assert backend.image.getpixel(midpoint) == (20, 20, 28)
    finally:
        executor.stop()
        thread.join(2)


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
