import time

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QMessageBox

from app.models import Timing
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
    panel.local_canvas.clear()
    source = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(source).rectangle((20, 20, 80, 80), fill=COLORS[1])
    path = tmp_path / "import.png"
    source.save(path)
    panel.load_image(str(path))
    panel.limit.setCurrentText("Unlimited")
    panel.make_plan()
    wait_until(qapp, lambda: panel.job is None)
    assert not errors
    assert panel.plan is not None and len(panel.plan.strokes) > 0
    panel.plan.timing = Timing(.00001, .00001, 1000000, 50)
    panel.run_plan()
    wait_until(qapp, lambda: panel.job is None and not panel._pending_run)
    assert not errors
    assert panel._state == "FINISHED"
    assert panel.local_canvas.received_segments > 0
    assert panel.store.settings()["last_profile"] == panel.profile.name
    assert list((panel.store.root / "images").glob("*.png"))
    assert list((panel.store.root / "plans").glob("*.json"))
    assert "finished" in (panel.store.root / "history.json").read_text()
    panel.icon.close()
    panel.local_canvas.close()
    panel.hide()
