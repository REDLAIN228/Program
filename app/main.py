from __future__ import annotations

import argparse
import sys


def splash_card(assets):
    """Opaque graphite card: a transparent logo would float over the desktop."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
    card = QPixmap(680, 230)
    card.fill(QColor("#111113"))  # Fully opaque: a splash window has no translucency.
    painter = QPainter(card)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setPen(QPen(QColor("#3a2a2e"), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(QRectF(.5, .5, 679, 229))
    logo = QPixmap(str(assets/"redlain-logo.png")).scaledToWidth(560, Qt.TransformationMode.SmoothTransformation)
    painter.drawPixmap(60, 50, logo)
    painter.end()
    return card


def main():
    from app import __version__
    parser = argparse.ArgumentParser(description=f"REDLAIN DRAW ENGINE {__version__} · desktop painter")
    parser.add_argument("--test-canvas", action="store_true", help="Open the built-in test canvas")
    parser.add_argument("--version", action="version", version=f"REDLAIN DRAW ENGINE {__version__}")
    args = parser.parse_args()
    from app.windows import enable_dpi_awareness
    enable_dpi_awareness()
    from PySide6.QtWidgets import QApplication, QSplashScreen
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QIcon, QPixmap
    from pathlib import Path
    app = QApplication(sys.argv[:1])
    app.setApplicationName("REDLAIN DRAW ENGINE")
    app.setOrganizationName("AnimeDrawer")
    app.setQuitOnLastWindowClosed(False)
    assets = Path(__file__).resolve().parents[1]/"assets"
    app.setWindowIcon(QIcon(str(assets/"redlain.ico")))
    # The splash only covers real module loading; it shows a state, not a percentage.
    splash = QSplashScreen(splash_card(assets))
    splash.show()
    splash.showMessage("Загрузка движка и интерфейса…", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                       QColor("#d8d2ce"))
    app.processEvents()
    from app.ui.panel import MainWindow
    try:
        window = MainWindow()
    except Exception as exc:
        from PySide6.QtWidgets import QMessageBox
        splash.close()
        QMessageBox.critical(None, "REDLAIN · configuration", str(exc))
        return 1
    window.show()
    splash.finish(window)
    window.shell.play_intro()
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
