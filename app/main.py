from __future__ import annotations

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="REDLAIN DRAW ENGINE 3.0 · desktop painter")
    parser.add_argument("--test-canvas", action="store_true", help="Open the built-in test canvas")
    parser.add_argument("--version", action="version", version="REDLAIN DRAW ENGINE 3.0.0")
    args = parser.parse_args()
    from app.windows import enable_dpi_awareness
    enable_dpi_awareness()
    from PySide6.QtWidgets import QApplication, QSplashScreen
    from PySide6.QtGui import QIcon, QPixmap
    from pathlib import Path
    from app.ui.panel import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("REDLAIN DRAW ENGINE")
    app.setOrganizationName("AnimeDrawer")
    app.setQuitOnLastWindowClosed(False)
    assets = Path(__file__).resolve().parents[1]/"assets"
    app.setWindowIcon(QIcon(str(assets/"redlain.ico")))
    splash = QSplashScreen(QPixmap(str(assets/"redlain-logo.png")).scaledToWidth(620))
    splash.show()
    app.processEvents()
    try:
        window = MainWindow()
    except Exception as exc:
        from PySide6.QtWidgets import QMessageBox
        splash.close()
        QMessageBox.critical(None, "REDLAIN · configuration", str(exc))
        return 1
    window.show()
    splash.finish(window)
    if args.test_canvas:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(200, window.open_test_canvas)
    result = app.exec()
    window.close_resources()
    window.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    del window
    import gc
    gc.collect()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
