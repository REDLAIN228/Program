import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from app.models import Brush, Calibration, Rect, Swatch


@pytest.fixture
def profile():
    return Calibration("test", "TestClass", "test.exe", (400, 400), 96,
                       Rect(80, 100, 300, 280),
                       [Swatch((20, 20, 28), (20, 20)), Swatch((240, 54, 82), (50, 20))],
                       [Brush(3, (20, 60)), Brush(9, (50, 60))], verified=True)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    application = QApplication.instance() or QApplication([])
    yield application
    # Close the app-owned disk/network workers before Qt object finalization.
    import time
    import gc
    windows = [w for w in QApplication.topLevelWidgets() if hasattr(w, "close_resources")]
    for window in windows:
        window.close_resources()
    if windows:
        del window
    until = time.monotonic()+3
    while any(window.background_jobs_running() for window in windows) and time.monotonic() < until:
        application.processEvents()
        time.sleep(.005)
    # Destroy retained test windows/timers while Qt is still alive, rather
    # than leaving their native objects to Python's interpreter finalization.
    widget = None
    for widget in QApplication.topLevelWidgets():
        widget.deleteLater()
    del widget
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    windows.clear()
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
