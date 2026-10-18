import time
import numpy as np

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QMessageBox, QInputDialog, QFileDialog

from app.models import Plan, Rect, Stroke, Timing
from app.storage import Store
from app.ui.panel import MainWindow
from app.ui.test_canvas import COLORS


def wait_until(qapp, predicate, limit=15):
    deadline = time.monotonic() + limit
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.001)
    assert predicate(), "GUI operation did not finish"


def test_ui_import_preview_calibration_test_and_run_end_to_end(qapp, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(MainWindow, "start_hotkeys", lambda self: None)
    monkeypatch.setattr(MainWindow, "error", lambda self, text: errors.append(text))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    panel = MainWindow(Store(tmp_path / "data"))
    # Explicit app-local backend, including when CI happens to run on Windows.
    panel.native_test = False
    panel.hotkeys_ready = True
    panel.show()
    panel.open_test_canvas()
    qapp.processEvents()
    panel.test_draw()
    wait_until(qapp, lambda: panel.job is None and not panel._pending_run)
    assert not errors
    assert panel.profile.verified
    panel.limit.setCurrentText("Custom")
    panel.custom_time.setValue(90)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: ("Short", True))
    panel.save_timer_preset()
    assert 90 in panel.store.settings()["timer_presets"].values()
    panel.sync_round_clock()
    assert panel._round_clock.limit == 90 and panel.time_limit() <= 90
    panel.reset_round_clock()
    assert panel._round_clock is None
    panel.local_canvas.clear()
    source = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(source).rectangle((20, 20, 80, 80), fill=COLORS[1])
    path = tmp_path / "import.png"
    source.save(path)
    panel.load_image(str(path))
    panel.limit.setCurrentText("Unlimited")
    panel.drawing_format.setCurrentText("Свой размер")
    panel.drawing_width.setValue(120)
    panel.drawing_height.setValue(160)
    panel.speed.setCurrentText("Turbo · 7")
    panel.make_plan()
    wait_until(qapp, lambda: panel.job is None)
    assert not errors
    assert panel.plan is not None and len(panel.plan.strokes) > 0
    assert panel.plan.canvas_size == (120, 160)
    assert panel.plan.drawing_rect is not None
    assert panel.draw_view._image.size == (panel.profile.canvas.width, panel.profile.canvas.height)
    first_plan = panel.plan
    panel.make_plan()
    assert panel.plan is first_plan and panel.job is None  # Unchanged PREVIEW uses the actual cache.
    assert panel.engine.currentText() == "Vector 2.0"
    panel.compare_engines()
    wait_until(qapp, lambda: panel.job is None)
    assert "OLD:" in panel.vector_stats.text() and "V2:" in panel.vector_stats.text()
    panel.prepare_simulation()
    wait_until(qapp, lambda: panel.job is None)
    assert len(panel._simulation_frames) > 1
    assert np.any(np.asarray(panel._simulation_frames[-1]) < 240)
    panel._simulation_timer.stop()
    saved_plan = panel.store.save_plan(panel.plan)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: (str(saved_plan), "JSON"))
    panel.load_plan()
    wait_until(qapp, lambda: panel.job is None)
    assert panel.plan.canvas_size == (120, 160) and panel.plan.engine == "Vector 2.0"
    panel.plan.timing = Timing(.00001, .00001, 1000000, 50)
    panel.run_plan()
    wait_until(qapp, lambda: panel.job is None and not panel._pending_run)
    assert not errors
    assert panel._state == "FINISHED"
    assert panel.local_canvas.received_segments > 0
    assert panel.store.settings()["last_profile"] == panel.profile.name
    assert panel.store.settings()["draw_width"] == 120
    assert list((panel.store.root / "images").glob("*.png"))
    assert list((panel.store.root / "plans").glob("*.json"))
    assert "finished" in (panel.store.root / "history.json").read_text()
    panel.icon.close()
    panel.local_canvas.close()
    panel.hide()


def test_canvas_flood_during_test_draw_is_rejected_without_confirmation(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.game_profile import screenshot_profile
    from app.automation import WindowState
    errors = []
    state = WindowState(123, "Roblox", "Game", "RobloxPlayerBeta.exe", Rect(0, 0, 1366, 768), 96)
    panel = SimpleNamespace(profile=screenshot_profile(state), store=Store(tmp_path/"data"),
                            _get_target=lambda: state,
                            _screenshot=lambda target: Image.new("RGB", (1366, 768), "black"),
                            error=errors.append)
    panel.profile.verified = True
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Must reject automatically")))
    plan = Plan((555, 555), [Stroke(((.42, .5), (.58, .5)), (0, 0, 0), 1)], Timing(), 1, "test", [])
    MainWindow._test_finished(panel, "finished", Image.new("RGB", (1366, 768), "white"), plan)
    assert errors and "далеко" in errors[0]
    assert not panel.profile.verified


def test_clock_uses_test_stroke_count_instead_of_image_plan(qapp, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.smart_timer import DrawingClock
    monkeypatch.setattr(MainWindow, "start_hotkeys", lambda self: None)
    panel = MainWindow(Store(tmp_path/"data"))
    panel.plan = Plan((100, 100), [Stroke(((.2, .5), (.8, .5)), (0, 0, 0), 1)], Timing(), 1, "x", [])
    clock = DrawingClock(None)
    panel.executor = SimpleNamespace(clock=clock, total_strokes=3, executed_indices=[0, 1, 2],
                                     _pen_seconds=1., _pen_started=None,
                                     pause_event=SimpleNamespace(is_set=lambda: False))
    panel.update_clock()
    assert "100% · 3/3" in panel.clock_stats.text()
    panel.executor = None
    panel._last_clock = {**clock.snapshot(), "total": 3, "strokes": 3, "progress": 1.}
    panel.update_clock()
    assert "100% · 3/3" in panel.clock_stats.text()
    panel._clock_timer.stop()
    panel.icon.close()
    panel.hide()


def test_ready_profile_installs_actual_window_identity_and_persists_opacity(qapp, tmp_path, monkeypatch):
    from app.automation import WindowState
    monkeypatch.setattr(MainWindow, "start_hotkeys", lambda self: None)
    errors = []
    monkeypatch.setattr(MainWindow, "error", lambda self, text: errors.append(text))
    panel = MainWindow(Store(tmp_path/"data"))
    state = WindowState(987, "Roblox", "ActualGameClass", "RobloxPlayerBeta.exe", Rect(-1400, 20, 1366, 768), 120)
    # Patch the class: restoring a bound method as an instance attribute
    # creates a self-cycle that can outlive QApplication during teardown.
    monkeypatch.setattr(MainWindow, "_choose_target", lambda self: state)
    panel.install_game_profile()
    assert not errors
    assert panel.profile.target_class == "ActualGameClass" and panel.profile.dpi == 120
    assert panel.profile.color_wheel.saturation_reversed and panel.profile.opacity_slider.point(100) == (590, 454)
    assert not panel.profile.verified
    panel.brush_opacity.setValue(75)
    panel.game_delay.setValue(350)
    settings = panel.store.settings()
    assert settings["studio_opacity"] == 75 and settings["studio_game_delay"] == 350
    restored = panel.store.profiles()[panel.profile.name]
    assert restored.opacity_slider.point(1) == (720, 454)
    panel._clock_timer.stop()
    panel.icon.close()
    panel.hide()
