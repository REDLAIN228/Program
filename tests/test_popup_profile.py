from dataclasses import replace
from pathlib import Path
import time

import pytest
from PIL import Image

from app.automation import DrawingExecutor, FieldNotCleared, SafetyError, WindowState
from app.game_profile import popup_screenshot_profile, restrict_game_profile
from app.models import Calibration, Plan, Rect, Stroke, Timing
from app.size_ocr import read_numeric_size


def state():
    return WindowState(1, "Roblox", "WINDOWSCLIENT", "RobloxPlayerBeta.exe", Rect(-1400, 20, 1366, 768), 96)


class PopupBackend:
    def __init__(self, profile, opened=False):
        self.profile = profile
        self.opened = opened
        self.point = (10, 10)
        self.pressed = False
        self.rgb = [255, 255, 255]
        self.width = 1
        self.focused = None
        self.edits, self.clicks, self.drawing = [], [], []
        self.brush = False
        self.reject_close = self.reject_color = self.reject_size = False

    def snapshot(self): return state()
    def is_foreground(self): return True
    def point_belongs_to_target(self, x, y): return state().client.contains(x, y)
    def cursor_position(self): return self.point[0]+state().client.x, self.point[1]+state().client.y
    def move(self, x, y): self.point = x-state().client.x, y-state().client.y
    def up(self): self.pressed = False
    def read_numeric_size(self, region): return self.width
    def read_number_field(self, region, dark_text): return dict(cleared=True, value=None)

    def sample(self, x, y):
        point = x-state().client.x, y-state().client.y
        c = self.profile.popup_controls
        if point == c.indicator:
            assert self.opened
            return tuple(self.rgb)
        for anchor in c.visible_anchors:
            if point == anchor.point:
                return anchor.rgb if self.opened else (115, 46, 160)
        raise AssertionError(f"Unexpected sample: {point}")

    def down(self):
        c = self.profile.popup_controls
        self.pressed = True
        self.clicks.append(self.point)
        assert not any(r.contains(*self.point) for r in self.profile.forbidden)
        if self.point == c.toggle:
            if not (self.opened and self.reject_close):
                self.opened = not self.opened
        elif self.opened and self.point in c.rgb_fields:
            self.focused = c.rgb_fields.index(self.point)
        elif not self.opened and self.point == c.brush_field:
            self.focused = "size"
        elif not self.opened and self.point == self.profile.brush_tool:
            self.brush = True
        elif self.profile.canvas.contains(*self.point):
            assert not self.opened, "Paint started under the popup"
            assert self.brush, "Typing left the wrong tool selected"
            self.drawing.append((tuple(self.rgb), self.width))
        else:
            raise AssertionError(f"Unexpected click: {self.point}")

    def replace_number(self, value, guard, wait, *, confirm_cleared=None, selected=False):
        guard()
        wait(.035)
        if confirm_cleared and not confirm_cleared():
            raise FieldNotCleared("Not cleared")
        self.edits.append((self.focused, value))
        self.brush = False
        if self.focused == "size":
            if not self.reject_size:
                self.width = value
        elif not self.reject_color:
            self.rgb[self.focused] = value


@pytest.fixture(autouse=True)
def immediate_target(monkeypatch):
    wait = DrawingExecutor._wait
    monkeypatch.setattr(DrawingExecutor, "_wait", lambda self, seconds: wait(self, 0))


def plan():
    strokes = [Stroke(((.42, y), (.58, y)), rgb, width) for y, rgb, width in
               [(.47, (0, 0, 0), 1), (.50, (255, 0, 0), 2), (.53, (0, 255, 0), 1), (.6, (0, 255, 0), 1)]]
    return Plan((534, 530), strokes, Timing(), 1, "test", [])


def test_profile_roundtrip_does_not_migrate_to_old_game():
    p = popup_screenshot_profile(state())
    assert Calibration.from_dict(p.to_dict()).to_dict() == p.to_dict()
    before = p.to_dict()
    assert not restrict_game_profile(p)
    assert p.to_dict() == before and p.character is None and not p.verified
    with pytest.raises(ValueError, match="1366"):
        popup_screenshot_profile(replace(state(), client=Rect(0, 0, 1920, 1080)))
    with pytest.raises(ValueError, match="Roblox"):
        popup_screenshot_profile(replace(state(), process="other.exe"))


@pytest.mark.parametrize("adapter", ["roblox-popup-rgb-v1", "roblox-popup-rgb-v2"])
def test_old_popup_profile_moves_clicks_to_right_edge_and_requires_new_test(adapter):
    p = popup_screenshot_profile(state())
    p.adapter, p.verified = adapter, True
    p.popup_controls = replace(p.popup_controls, rgb_fields=((624, 564), (726, 564), (826, 564)),
                               brush_field=(652, 692))
    assert restrict_game_profile(p)
    assert p.popup_controls.rgb_fields == ((649, 564), (750, 564), (851, 564))
    assert p.popup_controls.brush_field == (700, 692)
    assert p.adapter == "roblox-popup-rgb-v3" and not p.verified
    p.validate()
    assert not restrict_game_profile(p)


@pytest.mark.parametrize("opened", [False, True])
def test_numeric_rgb_and_size_close_popup_before_paint_and_reuse_cached_controls(opened):
    p = popup_screenshot_profile(state())
    backend = PopupBackend(p, opened)
    executor = DrawingExecutor(backend, p)
    assert executor.run(plan(), require_verified=False) == "finished"
    assert backend.drawing == [((0, 0, 0), 1), ((255, 0, 0), 2), ((0, 255, 0), 1), ((0, 255, 0), 1)]
    assert backend.clicks.count(p.popup_controls.toggle) == 6+int(opened)
    assert len(backend.edits) == 8  # Six changed RGB components, two size changes.
    assert not backend.opened and not backend.pressed


@pytest.mark.parametrize("failure", ["reject_close", "reject_color"])
def test_popup_or_color_failure_never_paints(failure):
    p = popup_screenshot_profile(state())
    backend = PopupBackend(p)
    setattr(backend, failure, True)
    with pytest.raises(SafetyError):
        DrawingExecutor(backend, p).run(plan(), require_verified=False)
    assert not backend.drawing and not backend.pressed


def test_missed_popup_open_click_is_retried_before_typing_or_painting():
    p = popup_screenshot_profile(state())
    class MissesFirstToggle(PopupBackend):
        missed = False
        def down(self):
            if self.point == self.profile.popup_controls.toggle and not self.missed:
                self.missed = True
                self.pressed = True
                self.clicks.append(self.point)
                return
            super().down()
    backend = MissesFirstToggle(p)
    assert DrawingExecutor(backend, p).run(plan(), require_verified=False) == "finished"
    assert backend.missed and backend.drawing[0] == ((0, 0, 0), 1)
    assert not backend.opened and not backend.pressed


def test_rejected_numeric_size_stops_before_wrong_width_stroke():
    p = popup_screenshot_profile(state())
    backend = PopupBackend(p)
    backend.reject_size = True
    with pytest.raises(SafetyError, match="размер|Размер"):
        DrawingExecutor(backend, p).run(plan(), require_verified=False)
    assert backend.drawing == [((0, 0, 0), 1)] and not backend.pressed


def test_zero_brush_size_from_failed_old_input_is_repaired_before_painting():
    p = popup_screenshot_profile(state())
    backend = PopupBackend(p)
    backend.width = 0
    assert DrawingExecutor(backend, p).run(plan(), require_verified=False) == "finished"
    assert backend.drawing[0] == ((0, 0, 0), 1)
    assert ("size", 1) in backend.edits


def test_numeric_brush_check_does_not_draw():
    p = popup_screenshot_profile(state())
    backend = PopupBackend(p, opened=True)
    DrawingExecutor(backend, p).check_brushes(plan(), [1, 2, 16, 1])
    assert backend.width == 1 and not backend.opened and not backend.drawing


def test_new_profile_rejects_unsupported_opacity():
    p = popup_screenshot_profile(state())
    drawing = plan()
    drawing.strokes[0] = replace(drawing.strokes[0], opacity=.5)
    with pytest.raises(SafetyError):
        DrawingExecutor(PopupBackend(p), p).run(drawing, require_verified=False)


def test_ignored_delete_stops_before_any_new_digits_or_paint():
    p = popup_screenshot_profile(state())
    class CannotClear(PopupBackend):
        def read_number_field(self, region, dark_text):
            return dict(cleared=False, value=255)
    backend = CannotClear(p)
    executor = DrawingExecutor(backend, p)
    with pytest.raises(SafetyError, match="очистить"):
        executor.run(plan(), require_verified=False)
    assert not backend.edits and not backend.drawing and not backend.pressed
    assert any(entry["kind"] == "field-select" for entry in executor._control_log)


def test_mouse_selection_retries_a_field_that_did_not_clear_on_first_attempt():
    p = popup_screenshot_profile(state())
    class RequiresSelection(PopupBackend):
        selected = False
        def move(self, x, y):
            old = self.point
            super().move(x, y)
            if self.pressed and self.point[0] < old[0]-4:
                self.selected = True
        def read_number_field(self, region, dark_text):
            return dict(cleared=self.selected, value=None if self.selected else 255)
    backend = RequiresSelection(p)
    executor = DrawingExecutor(backend, p)
    assert executor.run(plan(), require_verified=False) == "finished"
    assert backend.selected and backend.drawing[0] == ((0, 0, 0), 1)


def test_focus_failure_during_clear_confirmation_does_not_retry_typing():
    p = popup_screenshot_profile(state())
    class LostFocus(PopupBackend):
        def read_number_field(self, region, dark_text):
            raise SafetyError("Focus lost")
    backend = LostFocus(p)
    executor = DrawingExecutor(backend, p)
    with pytest.raises(SafetyError, match="Focus lost"):
        executor.run(plan(), require_verified=False)
    assert not backend.edits and not backend.drawing and not backend.pressed
    assert not any(entry["kind"] == "field-select" for entry in executor._control_log)


def test_close_rgb_values_are_entered_exactly_instead_of_reusing_nearby_color():
    p = popup_screenshot_profile(state())
    backend = PopupBackend(p)
    drawing = plan()
    drawing.strokes = [Stroke(((.42, .5), (.58, .5)), (250, 255, 255), 1)]
    DrawingExecutor(backend, p).run(drawing, require_verified=False)
    assert backend.drawing == [((250, 255, 255), 1)]
    assert backend.edits == [(0, 250)]


def test_popup_profile_button_and_calibration_preserve_old_profile(qapp, tmp_path, monkeypatch):
    from app.storage import Store
    from app.ui.panel import MainWindow
    from app.ui.calibration import CalibrationDialog
    errors = []
    monkeypatch.setattr(MainWindow, "start_hotkeys", lambda self: None)
    monkeypatch.setattr(MainWindow, "_choose_target", lambda self: state())
    monkeypatch.setattr(MainWindow, "error", lambda self, message: errors.append(message))
    panel = MainWindow(Store(tmp_path/"data"))
    panel.ready_profile.click()
    old_name = panel.profile.name
    panel.popup_profile.click()
    assert "RGB v3" in panel.popup_profile.text()
    assert not errors and panel.profile.popup_controls is not None
    assert panel.profile.name != old_name and old_name in panel.profiles
    assert panel.store.profiles()[panel.profile.name].popup_controls == panel.profile.popup_controls
    panel.style.setCurrentText("Custom")
    panel.set_original(Image.new("RGB", (32, 32), (255, 0, 0)))
    panel.make_plan()
    deadline = time.monotonic()+15
    while panel.job is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.001)
    assert panel.job is None and not errors
    assert panel.plan is not None and panel.plan.strokes and (255, 0, 0) in panel.plan.palette
    dialog = CalibrationDialog(Image.new("RGB", (1366, 768), "white"), state())
    dialog.apply_game_preset(True)
    assert dialog.save_button.isEnabled()
    dialog.save()
    assert dialog.result_profile.popup_controls == panel.profile.popup_controls
    dialog.close()
    panel.icon.close()
    panel.close()


@pytest.mark.parametrize("number", [0, 1, 2, 4, 8, 16, 32])
def test_black_numeric_brush_readout(number):
    index = [0, 1, 2, 4, 8, 16, 32].index(number)
    fixture = Image.open(Path(__file__).parent/"fixtures"/"numeric-size-labels.png")
    image = fixture.crop((0, index*32, 105, (index+1)*32))
    assert read_numeric_size(image) == number
