from __future__ import annotations

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="ANIME DRAWER · desktop auto painter")
    parser.add_argument("--test-canvas", action="store_true", help="Open the built-in test canvas")
    args = parser.parse_args()
    from app.windows import enable_dpi_awareness
    enable_dpi_awareness()
    from PySide6.QtWidgets import QApplication
    from app.ui.panel import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ANIME DRAWER")
    app.setOrganizationName("AnimeDrawer")
    app.setQuitOnLastWindowClosed(False)
    try:
        window = MainWindow()
    except Exception as exc:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "ANIME DRAWER · configuration", str(exc))
        return 1
    window.show()
    if args.test_canvas:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(200, window.open_test_canvas)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
