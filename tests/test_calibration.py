from PIL import Image
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

from app.automation import WindowState
from app.models import Rect
from app.ui.calibration import CalibrationDialog


def make_dialog():
    state = WindowState(123, "Roblox", "GameWindow", "RobloxPlayerBeta.exe", Rect(70, 40, 1200, 700), 144)
    return CalibrationDialog(Image.new("RGB", (1200, 700), (10, 20, 30)), state)


def test_calibration_undo_restores_partial_rectangle_and_replaced_color(qapp, monkeypatch):
    dialog = make_dialog()
    dialog.select(100, 150)
    dialog.select(900, 600)
    assert dialog.canvas == Rect(100, 150, 801, 451)
    dialog.undo()
    assert dialog.canvas is None
    assert dialog.first == (100, 150)
    dialog.select(800, 550)
    assert dialog.canvas == Rect(100, 150, 701, 401)
    dialog.set_mode("swatch")
    monkeypatch.setattr(QColorDialog, "getColor", lambda *args: QColor(10, 20, 30))
    dialog.select(30, 30)
    dialog.select(60, 30)
    assert dialog.swatches[0].point == (60, 30)
    dialog.undo()
    assert dialog.swatches[0].point == (30, 30)
    assert dialog.anchors[0].point == (30, 30)
    dialog.undo()
    assert not dialog.swatches and not dialog.anchors
    dialog.close()


def test_calibration_requires_controls_then_saves_client_coordinates(qapp, monkeypatch):
    dialog = make_dialog()
    assert not dialog.save_button.isEnabled()
    dialog.select(100, 150)
    dialog.select(800, 550)
    dialog.set_mode("swatch")
    monkeypatch.setattr(QColorDialog, "getColor", lambda *args: QColor(10, 20, 30))
    dialog.select(30, 30)
    assert not dialog.save_button.isEnabled()
    dialog.mode, dialog.pending_width = "brush", 9
    dialog.select(30, 70)
    assert dialog.save_button.isEnabled()
    dialog.save()
    profile = dialog.result_profile
    profile.validate()
    assert profile.canvas.x == 100  # Client coordinates: no desktop origin/DPI scaling.
    assert profile.dpi == 144
    assert profile.client_size == (1200, 700)
    assert profile.brushes[0].pixels == 9
    assert not profile.verified
    dialog.close()
