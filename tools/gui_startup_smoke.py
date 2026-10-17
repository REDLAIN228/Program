"""Verify actual Qt UI startup and clean shutdown; performs no mouse automation."""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from app.windows import enable_dpi_awareness
    enable_dpi_awareness()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from app.storage import Store
    from app.ui.panel import MainWindow
    application = QApplication([])
    application.setQuitOnLastWindowClosed(False)
    errors = []
    with tempfile.TemporaryDirectory(prefix="anime-startup-") as directory:
        window = MainWindow(Store(Path(directory)))
        # Keep diagnostics visible to CI instead of blocking on a modal error dialog.
        window.error = errors.append
        window.show()
        result = [1]
        def finish():
            visible = window.isVisible() and window.icon.isVisible()
            hotkeys = window.hotkeys_ready
            print(f"Main window visible: {visible}; hotkeys ready: {hotkeys}; errors: {errors}")
            if visible and hotkeys and not errors:
                result[0] = 0
            if window.hotkeys:
                window.hotkeys.close()
            window.icon.close()
            window.hide()
            application.quit()
        QTimer.singleShot(1500, finish)
        application.exec()
        return result[0]


if __name__ == "__main__":
    raise SystemExit(main())
