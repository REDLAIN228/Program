from dataclasses import replace

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
    assert selection_clicks(profile) == (5, 12)
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

    def read_brush_size(self, region): return self.width

    def snapshot(self): return game_state()
    def is_foreground(self): return True
    def point_belongs_to_target(self, x, y): return self.snapshot().client.contains(x, y)
    def sample(self, x, y): return (0, 0, 0)

    def move(self, x, y):
        origin = self.snapshot().client
        self.point = (x-origin.x, y-origin.y)
        if self.pressed and self.point[1] == 404:
            assert self.tab == "color"
            self.width = round(1+(self.point[0]-590)*255/130)

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
        elif point[1] == 404:
            assert self.tab == "color"
            self.width = round(1+(point[0]-590)*255/130)
        elif point == p.brush_tool:
            pass
        else:
            assert self.tab == "color", "Clicked the color wheel on the size tab"
            # Expected square extremes for black, red, and green; independent of HSV math.
            if point == (606, 246): self.rgb = (0, 0, 0)
            elif point == (680, 171):
                self.rgb = (255, 0, 0) if self.last_hue == (643, 135) else (0, 255, 0)
            elif point not in {(573, 317), (746, 132)}:
                self.last_hue = point
        self.clicks.append(point)

    def up(self): self.pressed = False


def test_executor_switches_hidden_tabs_and_uses_adaptive_colors():
    profile = screenshot_profile(game_state())
    profile.verified = True
    backend = TabbedBackend(profile)
    strokes = [Stroke(((.2, .4), (.3, .4)), color, width)
               for color, width in [((0, 0, 0), 2), ((255, 0, 0), 6), ((0, 255, 0), 2)]]
    plan = Plan((555, 555), strokes, Timing(.00001, .00001, 1000000, 100), 1, "test", [])
    executor = DrawingExecutor(backend, profile)
    assert executor.run(plan) == "finished"
    assert backend.drawing == [((0, 0, 0), 2), ((255, 0, 0), 6), ((0, 255, 0), 2)]
    assert backend.clicks.count(profile.color_tab) == 6
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
    assert backend.drawing == [((0, 0, 0), 16)]


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
    assert backend.drawing == [((0, 0, 0), 1), ((255, 0, 0), 1)]
