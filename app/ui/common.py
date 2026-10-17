from __future__ import annotations

import threading

from PIL import Image
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy

STYLE = """
QWidget { background: #13151b; color: #f0f1f4; font-family: 'Segoe UI'; font-size: 12px; }
QMainWindow, QDialog { background: #13151b; }
QLabel#brand { font-size: 22px; font-weight: 800; letter-spacing: 2px; }
QLabel#muted { color: #989cac; }
QPushButton { background: #262a35; border: 1px solid #363b49; border-radius: 8px;
              padding: 8px 12px; min-height: 18px; }
QPushButton:hover { background: #363b49; border-color: #e74059; }
QPushButton:disabled { color: #626878; background: #1c1f27; }
QPushButton#primary { background: #c62e49; border-color: #ef526b; font-weight: bold; }
QPushButton#danger { color: #ff7188; }
QLineEdit, QTextEdit, QComboBox, QSpinBox { background: #1e222c; border: 1px solid #343948;
    border-radius: 6px; padding: 6px; selection-background-color: #c62e49; }
QComboBox::drop-down { border: none; width: 24px; }
QProgressBar { background: #20242e; border: none; border-radius: 5px; height: 9px; text-align: center; }
QProgressBar::chunk { background: #df3d58; border-radius: 5px; }
QTabWidget::pane { border: 1px solid #343948; border-radius: 8px; }
QTabBar::tab { padding: 8px 14px; background: #20242e; }
QTabBar::tab:selected { background: #39303a; color: #ff8296; }
QListWidget { background: #1c2029; border: 1px solid #343948; border-radius: 6px; }
QCheckBox { spacing: 8px; }
QToolTip { color: white; background: #303642; border: 1px solid #e74059; }
"""


def pixmap(image: Image.Image) -> QPixmap:
    rgb = image.convert("RGB")
    qimage = QImage(rgb.tobytes(), rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimage.copy())


def pil_image(image: QImage) -> Image.Image:
    from app.imaging import flatten
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return flatten(Image.frombytes("RGBA", (image.width(), image.height()), bytes(image.bits()),
                                    "raw", "RGBA", image.bytesPerLine()))


class Preview(QLabel):
    def __init__(self, text="Нет изображения"):
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 170)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._image = None

    def set_image(self, image: Image.Image):
        self._image = image
        self._refresh()

    def _refresh(self):
        if self._image:
            self.setPixmap(pixmap(self._image).scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        self._refresh()
        super().resizeEvent(event)


class Job(QThread):
    progress = Signal(float, str)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function
        self.cancel = threading.Event()

    def run(self):
        try:
            value = self.function(self)
            if not self.cancel.is_set():
                self.result.emit(value)
        except InterruptedError:
            pass
        except Exception as exc:
            # API exceptions are sanitized in the provider; never dump environment/key values.
            self.failed.emit(str(exc))


class GuiBridge(QObject):
    requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.requested.connect(self._dispatch)

    @Slot(object)
    def _dispatch(self, request):
        function, finished, values = request
        try:
            values.append((True, function()))
        except Exception as exc:
            values.append((False, exc))
        finally:
            finished.set()

    def call(self, function):
        if QThread.currentThread() == self.thread():
            return function()
        finished, values = threading.Event(), []
        self.requested.emit((function, finished, values))
        if not finished.wait(5):
            raise RuntimeError("Интерфейс тестового холста не отвечает")
        ok, value = values[0]
        if not ok:
            raise value
        return value
