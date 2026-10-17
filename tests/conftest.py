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
    from PySide6.QtWidgets import QApplication
    application = QApplication.instance() or QApplication([])
    yield application
