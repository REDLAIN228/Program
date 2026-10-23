"""Capture actual 3.0 UI and an actual paused app-local drawing, never Roblox."""
from pathlib import Path
import os
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication, QEvent
    from app.ui.panel import MainWindow
    from app.storage import Store
    from app.models import Rect, Timing
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    root = Path(__file__).resolve().parents[1]
    output = root/"artifacts/v3-ui"
    output.mkdir(parents=True, exist_ok=True)
    def pump(predicate, limit=20):
        until = time.monotonic()+limit
        while not predicate() and time.monotonic() < until:
            app.processEvents()
            time.sleep(.002)
        if not predicate(): raise RuntimeError("UI smoke timeout")
    with tempfile.TemporaryDirectory(prefix="redlain-ui-") as data:
        window = MainWindow(Store(Path(data)))
        window.resize(1320, 740)
        errors = []
        window.error = errors.append
        window.native_test = False
        window.show()
        app.processEvents()
        window.grab().save(str(output/"dashboard.png"))
        window.open_test_canvas()
        window.profile.canvas = Rect(24, 142, 160, 160)
        window.profile.verified = True  # Known app-owned fixture only.
        window.load_image(str(root/"assets/v2-examples/portrait.png"))
        window.engine.setCurrentText("Human 3.0")
        window.make_plan()
        pump(lambda: window.job is None)
        if errors: raise RuntimeError(errors)
        window.inspector_mode.setCurrentText("Human Engine")
        window.show()
        window.grab().save(str(output/"workspace.png"))
        window.plan.timing = Timing(.001, .001, 100000, 20)
        original_event = window.engine_event
        def pause_at_event(event):
            original_event(event)
            if event["type"] == "stroke_complete" and event["index"] == 2:
                window.pause_and_save()
        # Signal receives the method assigned before DrawJob is connected.
        window.engine_event = pause_at_event
        window.run_plan()
        pump(lambda: window.executor is not None and window.executor.pause_event.is_set() and window._state == "PAUSED")
        pump(lambda: window.project_status.text().startswith("Saved · ") and window._project_last_state.get("cursor", 0) > 0)
        window.navigate_v3("Live Drawing")
        window.show()
        app.processEvents()
        window.live_core._drain()
        window.grab().save(str(output/"live-drawing-paused.png"))
        window.navigate_v3("Projects")
        window.refresh_project_library()
        pump(lambda: window._project_library_job is None)
        app.processEvents()
        window.grab().save(str(output/"projects.png"))
        window.stop()
        pump(lambda: window.job is None)
        window.navigate_v3("Workspace")
        window.resize(850, 700)
        app.processEvents()
        window.grab().save(str(output/"workspace-compact.png"))
        assert not errors, errors
        print("Captured real UI and paused local input:", output)
        window.engine_event = original_event
        window.close_resources()
        window.icon.close()
        window.local_canvas.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return 0


if __name__ == "__main__": raise SystemExit(main())
