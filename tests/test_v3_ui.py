import time
from dataclasses import replace

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QMessageBox

from app.models import Rect, Timing
from app.storage import Store
from app.ui.panel import MainWindow
from app.ui.test_canvas import TestCanvas


def pump(qapp, condition, limit=12):
    until = time.monotonic()+limit
    while not condition() and time.monotonic() < until:
        qapp.processEvents()
        time.sleep(.002)
    assert condition(), "3.0 UI operation did not finish"


def test_human_pause_save_reload_and_resume_across_fresh_window(qapp, tmp_path, monkeypatch):
    errors, started = [], []
    monkeypatch.setattr(MainWindow, "start_hotkeys", lambda self: None)
    monkeypatch.setattr(MainWindow, "error", lambda self, text: errors.append(text))
    monkeypatch.setattr(MainWindow, "confirm_project_canvas", lambda self, image, profile: True)  # Explicit test user confirmation.
    monkeypatch.setattr(MainWindow, "_choose_target", lambda self: self.local_canvas.state(False))
    original_event = MainWindow.engine_event
    def events(self, event):
        original_event(self, event)
        if event["type"] == "stroke_start": started.append(event["index"])
        if event["type"] == "stroke_complete" and event["index"] == 1 and not getattr(self, "_test_resuming", False):
            self.pause_and_save()
    monkeypatch.setattr(MainWindow, "engine_event", events)
    store = Store(tmp_path/"data")
    game = TestCanvas()
    game.show()
    qapp.processEvents()
    source = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(source)
    draw.ellipse((10, 10, 90, 95), fill=(20, 20, 28))
    draw.ellipse((20, 25, 80, 85), fill=(244, 190, 168))
    draw.rectangle((35, 48, 42, 57), fill=(20, 20, 28))
    path = tmp_path/"source.png"
    source.save(path)
    first = MainWindow(store)
    first.native_test = False
    first.local_mode, first.local_canvas, first.target = True, game, int(game.winId())
    profile = game.profile(False)
    profile.canvas = Rect(24, 142, 128, 128)
    profile.verified = True
    first._save_profile(profile)
    first.load_image(str(path))
    assert first.engine.currentText() == "Human 3.0"
    assert first.limit.currentText() == "Unlimited"
    first.make_plan()
    pump(qapp, lambda: first.job is None)
    assert not errors and first.plan.engine == "Human 3.0"
    first.plan.timing = Timing(.001, .001, 100000, 12)
    first.run_plan()
    pump(qapp, lambda: first.executor and first.executor.pause_event.is_set() and first._state == "PAUSED")
    pump(qapp, lambda: first.project_status.text().startswith("Saved · ") and first._project_last_state.get("cursor", 0) > 0)
    assert first.project_store.load(first._project_id)["state"]["cursor"] > 0
    first.stop()
    pump(qapp, lambda: first.job is None)
    pump(qapp, lambda: first._project_writer.flush(0))
    project_id = first._project_id
    saved = first.project_store.load(project_id)
    cursor = saved["state"]["cursor"]
    assert 0 < cursor < len(saved["plan"].strokes)
    first.close_resources()
    first.icon.close()
    first.hide()
    second = MainWindow(Store(tmp_path/"data"))  # New controller, new Store, no runner state reused.
    second._test_resuming = True
    second.native_test = False
    second.local_mode, second.local_canvas, second.target = True, game, int(game.winId())
    second._source_key, second._cached_request = "unrelated-old-image", "old-request"
    second.style.setCurrentText("Sketch")
    second.load_project(project_id)
    pump(qapp, lambda: second.job is None)
    assert second._resume_payload["state"]["cursor"] == cursor
    assert second.live_core.done == set(saved["state"]["executed"])
    assert second._source_key == saved["plan"].source_hash and second._cached_request is None
    assert second.style.currentText() == saved["manifest"]["options"]["style"]
    started.clear()
    second.resume_project()
    pump(qapp, lambda: second.job is None and not second._pending_run)
    assert not errors, errors
    assert started and min(started) == cursor and not any(i < cursor for i in started)
    pump(qapp, lambda: second._project_writer is not None and second._project_writer.flush(0))
    final = second.project_store.load(project_id)
    assert final["state"]["cursor"] == len(final["plan"].strokes)
    assert len(final["state"]["executed"]) == len(final["plan"].strokes)
    assert second.live_core.fraction == 1
    second.close_resources()
    second.icon.close()
    second.hide()
    game.close()
