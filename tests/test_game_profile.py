from dataclasses import replace
import colorsys
import math

import pytest
from PIL import Image

from app.automation import DrawingExecutor, SafetyError, WindowState
from app.game_profile import screenshot_profile, selection_clicks
from app.models import BrushSlider, Calibration, ColorWheel, Plan, Rect, Stroke, Timing, estimate_plan
from app.planner import PlanOptions, build_plan
from app.ui.calibration import CalibrationDialog


@pytest.fixture(autouse=True)
def synchronous_target_delays(monkeypatch):
    # This target delivers input immediately; preserve STOP/pause checks without
    # pretending to validate Windows frame timing in the simulated backend.
    wait = DrawingExecutor._wait
    monkeypatch.setattr(DrawingExecutor, "_wait", lambda self, seconds: wait(self, 0))


def game_state():
    return WindowState(123, "Roblox", "Game", "RobloxPlayerBeta.exe", Rect(-1400, 20, 1366, 768), 120)


def test_hue_ring_and_sv_square_use_known_primary_and_gray_positions():
    wheel = ColorWheel((100, 100), (100, 50), Rect(200, 200, 101, 101))
    assert wheel.points((255, 0, 0)) == [(100, 50), (300, 200)]
    assert wheel.points((0, 255, 0)) == [(143, 125), (300, 200)]
    assert wheel.points((0, 0, 255)) == [(57, 125), (300, 200)]
    assert wheel.points((128, 128, 128))[-1] == (200, 250)
    assert wheel.points((0, 0, 0))[-1] == (200, 300)
    assert wheel.points((255, 255, 255))[-1] == (200, 200)


def test_game_profile_roundtrip_resolution_and_unverified_status():
    profile = screenshot_profile(game_state())
    assert not profile.verified
    assert Calibration.from_dict(profile.to_dict()).to_dict() == profile.to_dict()
    assert selection_clicks(profile) == (2, 12)
    assert profile.brush_slider.minimum == 1 and profile.brush_slider.maximum == 256
    assert profile.size_tab is None
    with pytest.raises(ValueError, match="1366"):
        screenshot_profile(replace(game_state(), client=Rect(0, 0, 1920, 1080)))
    with pytest.raises(ValueError, match="Roblox"):
        screenshot_profile(replace(game_state(), process="other.exe"))
    with pytest.raises(ValueError):
        replace(profile, color_wheel=replace(profile.color_wheel, center=(1340, 400))).validate()


class TabbedBackend:
    """A target that refuses interaction with controls on a hidden tab."""
    def __init__(self, profile):
        self.profile = profile
        self.tab = "size"
        self.point = (0, 0)
        self.pressed = False
        self.clicks = []
        self.drawing = []
        self.width = 128
        self.opacity = 100
        self.rgb = (0, 0, 0)
        self.hue = 0.

    def read_brush_size(self, region): return self.width
    def read_opacity(self, region): return self.opacity

    def snapshot(self): return game_state()
    def is_foreground(self): return True
    def point_belongs_to_target(self, x, y): return self.snapshot().client.contains(x, y)
    def sample(self, x, y): return getattr(self, "rgb", (0, 0, 0))

    def move(self, x, y):
        origin = self.snapshot().client
        self.point = (x-origin.x, y-origin.y)
        if self.pressed and self.point[1] == 404:
            assert self.tab == "color"
            self.width = round(1+(self.point[0]-590)*255/130)
        if self.pressed and self.point[1] == 454 and 590 <= self.point[0] <= 720:
            self.opacity = round(100-(self.point[0]-590)*99/130)

    def down(self):
        self.pressed = True
        point, p = self.point, self.profile
        if p.canvas.contains(*point):
            self.drawing.append((self.rgb, self.width))
        elif point == p.color_tab:
            self.tab = "color"
        elif point == p.brush_slider.decrease:
            self.width = max(1, self.width-1)
        elif point == p.brush_slider.increase:
            self.width = min(256, self.width+1)
        elif p.opacity_slider and point == p.opacity_slider.decrease:
            self.opacity = max(1, self.opacity-1)
        elif p.opacity_slider and point == p.opacity_slider.increase:
            self.opacity = min(100, self.opacity+1)
        elif point[1] == 454 and 590 <= point[0] <= 720:
            self.opacity = round(100-(point[0]-590)*99/130)
        elif point[1] == 404:
            assert self.tab == "color"
            self.width = round(1+(point[0]-590)*255/130)
        elif point == p.brush_tool:
            pass
        else:
            assert self.tab == "color", "Clicked the color wheel on the size tab"
            # Independent game geometry from the screenshot: hue on the LEFT,
            # white on the RIGHT. Do not reuse ColorWheel.points to model this.
            if 605 <= point[0] <= 682 and 170 <= point[1] <= 248:
                saturation, value = 1-(point[0]-605)/77, 1-(point[1]-170)/78
                self.rgb = tuple(round(v*255) for v in colorsys.hsv_to_rgb(self.hue, saturation, value))
            elif point not in {(573, 317), (746, 132)}:
                self.hue = math.atan2(point[0]-644, 209-point[1])/(2*math.pi) % 1
        self.clicks.append(point)

    def up(self): self.pressed = False


def assert_drawing(backend, expected):
    assert len(backend.drawing) == len(expected)
    for (actual, width), (rgb, requested_width) in zip(backend.drawing, expected):
        assert width == requested_width
        assert max(abs(a-b) for a, b in zip(actual, rgb)) <= 25


def test_executor_switches_hidden_tabs_and_uses_adaptive_colors():
    profile = screenshot_profile(game_state())
    profile.verified = True
    backend = TabbedBackend(profile)
    strokes = [Stroke(((.2, .4), (.3, .4)), color, width)
               for color, width in [((0, 0, 0), 2), ((255, 0, 0), 6), ((0, 255, 0), 2)]]
    plan = Plan((555, 555), strokes, Timing(.00001, .00001, 1000000, 100), 1, "test", [])
    executor = DrawingExecutor(backend, profile)
    assert executor.run(plan) == "finished"
    assert_drawing(backend, [((0, 0, 0), 2), ((255, 0, 0), 6), ((0, 255, 0), 2)])
    assert backend.clicks.count(profile.color_tab) == 1
    assert profile.size_tab is None
    assert not any(r.contains(*point) for r in profile.forbidden for point in backend.clicks)
    assert not backend.pressed
    profile.verified = False
    with pytest.raises(SafetyError, match="TEST DRAW"):
        DrawingExecutor(backend, profile).run(plan)


def test_wheel_plan_accounts_for_tab_and_color_selection_cost():
    source = Image.new("RGB", (40, 40), (100, 60, 35))
    plan, _ = build_plan(source, PlanOptions((100, 100), time_limit=None,
                                           color_clicks=5, brush_clicks=2))
    assert (100, 60, 35) in plan.palette
    assert plan.estimated_seconds == estimate_plan(plan.strokes, plan.canvas_size, plan.timing, 5, 2)
    assert plan.estimated_seconds > estimate_plan(plan.strokes, plan.canvas_size, plan.timing)
    assert Plan.from_dict(plan.to_dict()).estimated_seconds == plan.estimated_seconds


def test_calibration_applies_and_undoes_game_preset(qapp):
    dialog = CalibrationDialog(Image.new("RGB", (1366, 768)), game_state())
    dialog.apply_game_preset()
    assert dialog.save_button.isEnabled()
    assert dialog.color_wheel is not None
    dialog.save()
    assert dialog.result_profile.target_process == "RobloxPlayerBeta.exe"
    assert not dialog.result_profile.verified
    assert dialog.result_profile.color_wheel.saturation_reversed
    assert dialog.result_profile.opacity_slider is not None
    assert dialog.result_profile.color_tolerance == 25
    dialog.undo()
    assert dialog.color_wheel is None and dialog.canvas is None
    assert not dialog.save_button.isEnabled()
    dialog.close()


def test_legacy_paid_preset_is_migrated_and_requires_new_test(tmp_path):
    from app.storage import Store, write_json
    old = screenshot_profile(game_state()).to_dict()
    for key in ["brush_slider", "forbidden", "adapter"]:
        old.pop(key)
    old["verified"] = True
    old["name"] = "Мой переименованный игровой профиль"
    old["size_tab"] = [705, 100]
    old["brushes"] = [{"pixels": 2, "point": [628, 143]}]
    write_json(tmp_path/"profiles.json", {old["name"]: old})
    profile = Store(tmp_path).profiles()[old["name"]]
    assert not profile.verified
    assert profile.size_tab is None
    assert profile.brush_slider.maximum == 256
    assert profile.brushes[0].point == profile.brush_slider.start
    backend = TabbedBackend(profile)
    executor = DrawingExecutor(backend, profile)
    executor._session = game_state()
    for x, y in [(705, 100), (1190, 720), (1250, 720), (1315, 720)]:
        with pytest.raises(SafetyError, match="Донат"):
            executor._move(game_state().client.x+x, game_state().client.y+y)
    assert not backend.clicks


def test_slider_bounds_mapping_and_incomplete_calibration():
    slider = BrushSlider((590, 404), (720, 404), 1, 256)
    assert slider.point(1) == (590, 404)
    assert slider.point(256) == (720, 404)
    assert slider.point(128) == (655, 404)
    with pytest.raises(ValueError): slider.point(257)
    with pytest.raises(ValueError): BrushSlider((590, 404), (720, 404)).point(5)


def test_old_100_range_migrates_once_preserving_custom_geometry(tmp_path):
    from app.game_profile import FREE_SLIDER_ADAPTER, feedback_slider, restrict_game_profile
    from app.storage import Store
    profile = screenshot_profile(game_state())
    profile.adapter = "roblox-free-slider-v1"
    profile.brush_slider = BrushSlider((600, 410), (730, 410), 1, 100)
    profile.character = Rect(155, 255, 330, 490)
    profile.verified = True
    store = Store(tmp_path)
    store.save_profile(profile)
    migrated = store.profiles()[profile.name]
    assert migrated.brush_slider == feedback_slider(BrushSlider((600, 410), (730, 410), 1, 256))
    assert migrated.character == profile.character
    assert migrated.adapter == FREE_SLIDER_ADAPTER and not migrated.verified
    migrated.verified = True
    assert not restrict_game_profile(migrated)
    assert migrated.verified
    store.save_profile(migrated)
    assert store.profiles()[profile.name].verified


def test_stop_during_slider_drag_releases_mouse():
    profile = screenshot_profile(game_state())
    profile.verified = True
    backend = TabbedBackend(profile)
    executor = DrawingExecutor(backend, profile)
    move = backend.move
    def stop_on_slider(x, y):
        move(x, y)
        if backend.pressed and y-game_state().client.y == 404:
            executor.stop()
    backend.move = stop_on_slider
    plan = Plan((555, 555), [Stroke(((.2, .4), (.3, .4)), (0, 0, 0), 64)],
                Timing(.00001, .00001, 1000000, 100), 1, "test", [])
    assert executor.run(plan) == "stopped"
    assert not backend.pressed and not backend.drawing


def test_missing_slider_thumb_prevents_drawing():
    profile = screenshot_profile(game_state())
    profile.verified = True
    backend = TabbedBackend(profile)
    backend.slider_thumb = lambda start, end: None
    executor = DrawingExecutor(backend, profile)
    plan = Plan((555, 555), [Stroke(((.2, .4), (.3, .4)), (0, 0, 0), 16)],
                Timing(.00001, .00001, 1000000, 100), 1, "test", [])
    with pytest.raises(SafetyError, match="бегунок"):
        executor.run(plan)
    assert not backend.drawing and not backend.pressed


def test_slider_drag_starts_at_detected_thumb_instead_of_assuming_minimum():
    profile = screenshot_profile(game_state())
    profile.verified = True
    backend = TabbedBackend(profile)
    origin = game_state().client
    backend.slider_thumb = lambda start, end: (origin.x+720, origin.y+404)
    plan = Plan((555, 555), [Stroke(((.2, .4), (.3, .4)), (0, 0, 0), 16)],
                Timing(.00001, .00001, 1000000, 100), 1, "test", [])
    assert DrawingExecutor(backend, profile).run(plan) == "finished"
    assert (720, 404) in backend.clicks
    assert_drawing(backend, [((0, 0, 0), 16)])


def test_unreadable_size_aborts_before_any_canvas_input():
    profile = screenshot_profile(game_state())
    profile.verified = True
    backend = TabbedBackend(profile)
    backend.read_brush_size = lambda region: None
    plan = Plan((555, 555), [Stroke(((.2, .4), (.3, .4)), (0, 0, 0), 1)],
                Timing(), 1, "test", [])
    with pytest.raises(SafetyError, match="не прочитан"):
        DrawingExecutor(backend, profile).run(plan)
    assert not backend.drawing and not backend.pressed


def test_unresponsive_controls_abort_instead_of_drawing_with_large_brush():
    profile = screenshot_profile(game_state())
    profile.verified = True
    class Unresponsive(TabbedBackend):
        def move(self, x, y):
            width = self.width
            super().move(x, y)
            self.width = width
        def down(self):
            if self.point[1] == 404:
                self.pressed = True
                self.clicks.append(self.point)
            else:
                super().down()
    backend = Unresponsive(profile)
    plan = Plan((555, 555), [Stroke(((.2, .4), (.3, .4)), (0, 0, 0), 1)],
                Timing(), 1, "test", [])
    with pytest.raises(SafetyError, match="в игре 128"):
        DrawingExecutor(backend, profile).run(plan)
    assert not backend.drawing and not backend.pressed


def test_brush_control_check_never_touches_canvas_or_confirms_profile():
    profile = screenshot_profile(game_state())
    backend = TabbedBackend(profile)
    plan = Plan((555, 555), [], Timing(), 0, "check", [])
    result = DrawingExecutor(backend, profile).check_brushes(plan, [1, 6, 16, 1])
    assert "подтверждены" in result
    assert backend.width == 1 and not backend.drawing and not profile.verified
    assert not any(r.contains(*p) for p in backend.clicks for r in profile.forbidden)


def test_size_is_rechecked_after_changing_color_even_if_width_is_cached():
    profile = screenshot_profile(game_state())
    profile.verified = True
    class ResetsOnColor(TabbedBackend):
        def down(self):
            super().down()
            if self.point == self.profile.color_tab:
                self.width = 128
    backend = ResetsOnColor(profile)
    strokes = [Stroke(((.2, .4), (.3, .4)), c, 1) for c in [(0, 0, 0), (255, 0, 0)]]
    plan = Plan((555, 555), strokes, Timing(), 1, "test", [])
    assert DrawingExecutor(backend, profile).run(plan) == "finished"
    assert_drawing(backend, [((0, 0, 0), 1), ((255, 0, 0), 1)])


@pytest.mark.parametrize("speed,max_step", [("Slow", 7), ("Turbo · 7", 15)])
def test_mouse_up_travel_is_paced_and_routes_around_paid_tab(monkeypatch, speed, max_step):
    profile = screenshot_profile(game_state())
    backend = TabbedBackend(profile)
    executor = DrawingExecutor(backend, profile)
    executor._session = game_state()
    ox, oy = game_state().client.x, game_state().client.y
    start, destination = (1330, 120), profile.color_tab
    backend.cursor_position = lambda: (ox+start[0], oy+start[1])
    moves, delays = [], []
    original_move = backend.move
    def record_move(x, y):
        assert not backend.pressed
        moves.append((x-ox, y-oy))
        original_move(x, y)
    backend.move = record_move
    monkeypatch.setattr(executor, "_wait", delays.append)
    plan = Plan((555, 555), [], Timing.preset(speed), 0, "check", [])
    executor._travel(ox+destination[0], oy+destination[1], plan)
    import math
    assert len(moves) > 30 and moves[-1] == destination
    assert all(math.dist(a, b) <= max_step for a, b in zip([start]+moves, moves))
    assert not any(r.contains(*point) for r in profile.forbidden for point in moves)
    assert sum(delays) >= math.dist(start, destination)/plan.timing.control_speed
    assert not backend.clicks


def test_stop_during_mouse_up_travel_prevents_click():
    profile = screenshot_profile(game_state())
    backend = TabbedBackend(profile)
    executor = DrawingExecutor(backend, profile)
    executor._session = game_state()
    backend.cursor_position = lambda: (game_state().client.x+900, game_state().client.y+500)
    move = backend.move
    def stop_after_move(x, y):
        move(x, y)
        executor.stop()
    backend.move = stop_after_move
    plan = Plan((555, 555), [], Timing.preset("Slow"), 0, "check", [])
    with pytest.raises(InterruptedError):
        executor._click(profile.color_tab, plan)
    assert not backend.clicks and not backend.pressed


def test_delayed_size_readout_gets_time_to_stabilize_without_dragging(monkeypatch):
    profile = screenshot_profile(game_state())
    backend = TabbedBackend(profile)
    executor = DrawingExecutor(backend, profile)
    executor._session = game_state()
    readings = iter([None]*6+[88, 88])
    backend.read_brush_size = lambda region: next(readings)
    delays = []
    monkeypatch.setattr(executor, "_wait", delays.append)
    plan = Plan((555, 555), [], Timing.preset("Slow"), 0, "check", [])
    assert executor._read_brush(1, plan) == 88
    assert sum(delays) >= 1
    assert not backend.clicks and not backend.drawing


@pytest.mark.parametrize("missed", [0, 1, 2])
def test_adjacent_brush_size_retries_missed_arrows_without_dragging(missed):
    profile = screenshot_profile(game_state())
    profile.verified = True

    class DropsArrow(TabbedBackend):
        remaining = missed

        def down(self):
            if self.point == self.profile.brush_slider.increase and self.remaining:
                self.remaining -= 1
                self.pressed = True
                self.clicks.append(self.point)
            else:
                super().down()

    backend = DropsArrow(profile)
    backend.width = 1
    plan = Plan((555, 555), [Stroke(((.2, .4), (.3, .4)), (0, 0, 0), 2)],
                Timing.preset("Turbo · 7"), 1, "test", [])
    assert DrawingExecutor(backend, profile).run(plan) == "finished"
    assert backend.clicks.count(profile.brush_slider.increase) == missed+1
    assert not any(590 <= x <= 720 and y == 404 for x, y in backend.clicks)
    assert backend.drawing == [((0, 0, 0), 2)]
    assert not backend.pressed


@pytest.mark.parametrize("delay_reads", [4, 6])
def test_delayed_arrow_update_is_rechecked_before_repeating_input(delay_reads):
    profile = screenshot_profile(game_state())
    profile.verified = True

    class DelayedArrow(TabbedBackend):
        pending = None

        def down(self):
            if self.point == self.profile.brush_slider.increase:
                self.pressed = True
                self.clicks.append(self.point)
                self.pending = delay_reads
            else:
                super().down()

        def read_brush_size(self, region):
            if self.pending is not None:
                if self.pending == 0:
                    self.width += 1
                    self.pending = None
                else:
                    self.pending -= 1
            return self.width

    backend = DelayedArrow(profile)
    backend.width = 1
    plan = Plan((555, 555), [Stroke(((.2, .4), (.3, .4)), (0, 0, 0), 2)],
                Timing(), 1, "test", [])
    assert DrawingExecutor(backend, profile).run(plan) == "finished"
    assert backend.clicks.count(profile.brush_slider.increase) == 1
    assert backend.drawing == [((0, 0, 0), 2)]
    assert not backend.pressed


def test_permanently_unresponsive_arrow_stops_after_bounded_retries():
    profile = screenshot_profile(game_state())
    profile.verified = True

    class BrokenArrow(TabbedBackend):
        def down(self):
            if self.point == self.profile.brush_slider.increase:
                self.pressed = True
                self.clicks.append(self.point)
            else:
                super().down()

    backend = BrokenArrow(profile)
    backend.width = 1
    plan = Plan((555, 555), [Stroke(((.2, .4), (.3, .4)), (0, 0, 0), 2)],
                Timing(), 1, "test", [])
    with pytest.raises(SafetyError, match="после 3 попыток"):
        DrawingExecutor(backend, profile).run(plan)
    assert backend.clicks.count(profile.brush_slider.increase) == 3
    assert not backend.drawing and not backend.pressed


def test_stop_during_brush_retry_prevents_further_clicks():
    profile = screenshot_profile(game_state())
    profile.verified = True
    backend = TabbedBackend(profile)
    backend.width = 1
    executor = DrawingExecutor(backend, profile)
    down = backend.down

    def stop_on_arrow():
        if backend.point == profile.brush_slider.increase:
            backend.clicks.append(backend.point)
            backend.pressed = True
            executor.stop()
        else:
            down()

    backend.down = stop_on_arrow
    plan = Plan((555, 555), [Stroke(((.2, .4), (.3, .4)), (0, 0, 0), 2)],
                Timing(), 1, "test", [])
    assert executor.run(plan) == "stopped"
    assert backend.clicks.count(profile.brush_slider.increase) == 1
    assert not backend.drawing and not backend.pressed


def test_missed_color_selection_is_corrected_after_brush_controls():
    profile = screenshot_profile(game_state())
    profile.verified = True

    class ChangesColorOnSize(TabbedBackend):
        corrupt_once = True

        def down(self):
            super().down()
            if self.point == profile.brush_slider.increase and self.corrupt_once:
                self.rgb = (0, 0, 255)
                self.corrupt_once = False

    backend = ChangesColorOnSize(profile)
    backend.width = 1
    plan = Plan((555, 555), [Stroke(((.42, .5), (.58, .5)), (255, 0, 0), 2)],
                Timing.preset("Turbo · 7"), 1, "test", [])
    assert DrawingExecutor(backend, profile).run(plan) == "finished"
    assert backend.clicks.count((608, 173)) == 2
    assert_drawing(backend, [((255, 0, 0), 2)])


def test_persistently_wrong_color_stops_before_painting():
    profile = screenshot_profile(game_state())
    profile.verified = True
    backend = TabbedBackend(profile)
    backend.sample = lambda *_: (0, 0, 255)
    plan = Plan((555, 555), [Stroke(((.42, .5), (.58, .5)), (255, 0, 0), 2)],
                Timing(), 1, "test", [])
    with pytest.raises(SafetyError, match="Индикатор цвета"):
        DrawingExecutor(backend, profile).run(plan)
    assert not backend.drawing and not backend.pressed


def test_delayed_pen_release_cannot_leave_tails_on_mouse_up_travel(monkeypatch):
    profile = screenshot_profile(game_state())
    profile.verified = True

    class DeferredRelease(TabbedBackend):
        release_remaining = 0.
        tails = []

        def up(self):
            if self.pressed and profile.canvas.contains(*self.point):
                self.release_remaining = 1/60
            super().up()

        def move(self, x, y):
            old = self.point
            super().move(x, y)
            if self.release_remaining > 0 and self.point != old:
                self.tails.append((old, self.point))

    backend = DeferredRelease(profile)
    backend.width = 1
    executor = DrawingExecutor(backend, profile)
    wait = executor._wait

    def advance(seconds):
        wait(0)  # Keep cancellation and deadline checks, without wall-clock sleeps.
        backend.release_remaining = max(0., backend.release_remaining-seconds)

    monkeypatch.setattr(executor, "_wait", advance)
    strokes = [Stroke(((.2, y), (.3, y)), (0, 0, 0), 1) for y in (.2, .8)]
    plan = Plan((555, 555), strokes, Timing.preset("Turbo · 7"), 1, "test", [])
    assert executor.run(plan) == "finished"
    executor.park_pointer(plan)
    assert len(backend.drawing) == 2
    assert not backend.tails
    assert not profile.canvas.contains(*backend.point)
    assert not any(area.contains(*backend.point) for area in profile.forbidden)
    assert not backend.pressed


def test_game_profile_adds_color_check_once_preserving_custom_indicator():
    from app.game_profile import restrict_game_profile
    profile = screenshot_profile(game_state())
    profile.color_indicator = None
    profile.verified = True
    assert restrict_game_profile(profile)
    assert profile.color_indicator == (565, 283) and not profile.verified
    profile.verified = True
    assert not restrict_game_profile(profile) and profile.verified
    profile.color_indicator = (566, 284)
    assert not restrict_game_profile(profile)
    assert profile.color_indicator == (566, 284)


def test_thin_corner_is_visible_to_a_frame_sampled_target(monkeypatch):
    profile = screenshot_profile(game_state())
    profile.verified = True
    backend = TabbedBackend(profile)
    backend.width = 1
    executor = DrawingExecutor(backend, profile)
    elapsed, frame, observed = [0.], [.008], []
    wait = executor._wait

    def advance(seconds):
        wait(0)
        end = elapsed[0]+seconds
        while frame[0] <= end:
            if backend.pressed and profile.canvas.contains(*backend.point):
                observed.append(backend.point)
            frame[0] += 1/60
        elapsed[0] = end

    monkeypatch.setattr(executor, "_wait", advance)
    stroke = Stroke(((.2, .2), (.25, .2), (.25, .25)), (0, 0, 0), 1)
    plan = Plan((555, 555), [stroke], Timing.preset("Turbo · 7"), 1, "test", [])
    assert executor.run(plan) == "finished"
    mapped = [profile.canvas.map(point, 1.5) for point in stroke.points]
    assert all(point in observed for point in mapped)  # Endpoints and the sharp corner survived sampling.


@pytest.mark.parametrize("percent", [1, 25, 50, 75, 100])
def test_opacity_is_confirmed_and_same_value_does_not_repeat_controls(percent):
    profile = screenshot_profile(game_state())
    profile.verified = True
    backend = TabbedBackend(profile)
    backend.width = 1
    applied = []
    down = backend.down

    def record():
        if profile.canvas.contains(*backend.point):
            applied.append(backend.opacity)
        down()

    backend.down = record
    strokes = [Stroke(((.2, y), (.3, y)), (255, 0, 0), 1, opacity=percent/100) for y in (.2, .8)]
    plan = Plan((555, 555), strokes, Timing.preset("Turbo · 7"), 1, "test", [])
    assert DrawingExecutor(backend, profile).run(plan) == "finished"
    assert applied == [percent, percent]
    assert backend.clicks.count(profile.color_tab) == 1
    assert backend.clicks.count(profile.color_wheel.mode_button) == 1
    assert backend.clicks.count(profile.color_wheel.value_reset) == 1
    assert backend.clicks.count((608, 173)) == 1
    assert not any(r.contains(*point) for point in backend.clicks for r in profile.forbidden)


def test_unreadable_opacity_is_not_assumed_to_be_full_opacity():
    profile = screenshot_profile(game_state())
    profile.verified = True
    backend = TabbedBackend(profile)
    backend.read_opacity = lambda *_: None
    plan = Plan((555, 555), [Stroke(((.2, .4), (.3, .4)), (0, 0, 0), 1)], Timing(), 1, "test", [])
    with pytest.raises(SafetyError, match="не подтверждена"):
        DrawingExecutor(backend, profile).run(plan)
    assert not backend.drawing and not backend.pressed


def test_delayed_cursor_arrival_and_release_never_start_a_line_on_the_way(monkeypatch):
    profile = screenshot_profile(game_state())
    profile.verified = True

    class QueuedTarget(TabbedBackend):
        def __init__(self, p):
            super().__init__(p)
            self.queued = None
            self.move_age = 0.
            self.release_in = 0.
            self.starts = []
            self.tails = []

        def cursor_position(self):
            origin = game_state().client
            return self.point[0]+origin.x, self.point[1]+origin.y

        def move(self, x, y):
            self.queued = x, y
            self.move_age = 0.

        def down(self):
            assert self.cursor_position() == self.queued, "Pressed before actual cursor arrival"
            if profile.canvas.contains(*self.point):
                self.starts.append(self.point)
            super().down()

        def up(self):
            if self.pressed:
                self.release_in = .22

        def advance(self, seconds):
            if self.release_in:
                self.release_in = max(0., self.release_in-seconds)
                if not self.release_in:
                    self.pressed = False
            self.move_age += seconds
            if self.queued and self.move_age >= .22:
                old = self.point
                TabbedBackend.move(self, *self.queued)
                if self.release_in and self.point != old:
                    self.tails.append((old, self.point))

    backend = QueuedTarget(profile)
    backend.width = 1
    executor = DrawingExecutor(backend, profile)
    wait = executor._wait

    def advance(seconds):
        wait(0)
        backend.advance(seconds)

    monkeypatch.setattr(executor, "_wait", advance)
    strokes = [Stroke(((.2, y), (.3, y)), color, 1)
               for y, color in [(.2, (0, 0, 0)), (.8, (255, 0, 0))]]
    plan = Plan((555, 555), strokes, Timing.preset("Turbo · 7"), 1, "test", [])
    assert executor.run(plan) == "finished"
    assert backend.starts == [profile.canvas.map(stroke.points[0], 1.5) for stroke in strokes]
    assert not backend.tails


def test_screenshot_saturation_direction_and_corner_inset():
    wheel = screenshot_profile(game_state()).color_wheel
    assert wheel.points((255, 0, 0))[-1] == (608, 173)
    assert wheel.points((255, 255, 255))[-1] == (679, 173)
    assert wheel.points((0, 0, 0))[-1] == (679, 245)


def test_color_verification_handles_indicator_that_fades_with_opacity():
    profile = screenshot_profile(game_state())
    profile.verified = True

    class FadingIndicator(TabbedBackend):
        def sample(self, *_):
            return tuple(round(c*self.opacity/100+255*(1-self.opacity/100)) for c in self.rgb)

    backend = FadingIndicator(profile)
    backend.width = 1
    strokes = [Stroke(((.2, y), (.3, y)), rgb, width, opacity=.5)
               for y, rgb, width in [(.2, (0, 0, 0), 1), (.4, (255, 0, 0), 1), (.6, (255, 0, 0), 2)]]
    plan = Plan((555, 555), strokes, Timing(), 1, "test", [])
    assert DrawingExecutor(backend, profile).run(plan) == "finished"
    assert backend.opacity == 50
    assert_drawing(backend, [((0, 0, 0), 1), ((255, 0, 0), 1), ((255, 0, 0), 2)])


def test_missed_opacity_drag_is_retried_before_painting():
    profile = screenshot_profile(game_state())
    profile.verified = True

    class DropsFirstDrag(TabbedBackend):
        missed = False
        dragging = False
        attempts = 0

        def down(self):
            if self.point[1] == 454 and 590 <= self.point[0] <= 720:
                self.dragging = True
                self.attempts += 1
            super().down()

        def move(self, x, y):
            old = self.opacity
            super().move(x, y)
            if self.dragging and not self.missed:
                self.opacity = old

        def up(self):
            if self.dragging:
                self.missed = True
                self.dragging = False
            super().up()

    backend = DropsFirstDrag(profile)
    backend.width = 1
    plan = Plan((555, 555), [Stroke(((.2, .4), (.3, .4)), (0, 0, 0), 1, opacity=.5)],
                Timing(), 1, "test", [])
    assert DrawingExecutor(backend, profile).run(plan) == "finished"
    assert backend.attempts == 2 and backend.opacity == 50
    assert len(backend.drawing) == 1
