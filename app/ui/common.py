from __future__ import annotations

import threading

from PIL import Image
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot, QRectF
from PySide6.QtGui import QImage, QPixmap, QColor, QPen, QTextOption, QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy, QGraphicsView, QGraphicsScene, QTextBrowser

STYLE = """
QWidget { background: #0B0D12; color: #F5F6FA; font-family: 'Segoe UI'; font-size: 11px; }
QMainWindow, QDialog { background: #0B0D12; }
QLabel#brand { font-size: 22px; font-weight: 800; letter-spacing: 2px; }
QLabel#muted, QLabel#sectionTitle { color: #9299A8; }
QLabel#sectionTitle { font-size: 12px; font-weight: 700; padding: 8px 0; letter-spacing: 1px; }
QPushButton { background: #1A1F2B; border: 1px solid #30384A; border-radius: 7px;
 padding: 8px 10px; min-height: 18px; }
QPushButton:hover { background: #2A3244; border-color: #E73558; }
QPushButton:checked { background: #402035; border-color: #E73558; }
QPushButton:disabled { color: #626B80; background: #131720; border-color: #222A39; }
QPushButton#primary { background: #E73558; border-color: #F45B79; font-weight: 700; }
QPushButton#primary:hover { background: #F04B6C; }
QPushButton#danger { color: #FF8298; }
QLineEdit, QTextEdit, QComboBox, QSpinBox { background: #131720; border: 1px solid #2B3345;
 border-radius: 6px; padding: 6px; selection-background-color: #E73558; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background: #1A1F2B; selection-background-color: #402035; }
QProgressBar { background: #1A1F2B; border: none; border-radius: 4px; height: 7px; text-align: center; }
QProgressBar::chunk { background: #E73558; border-radius: 4px; }
QTabWidget::pane, QGraphicsView { border: 1px solid #242D40; border-radius: 10px; background: #0B0D12; }
QTabBar::tab { padding: 8px 12px; background: #131720; }
QTabBar::tab:selected { background: #322335; color: #FF8298; }
QListWidget { background: #131720; border: 1px solid #242D40; border-radius: 10px; }
QListWidget#navigation { border: none; padding: 6px; }
QListWidget#navigation::item { padding: 12px 6px; border-radius: 7px; color: #9299A8; }
QListWidget#navigation::item:selected { background: #352032; color: #F5F6FA; }
QListWidget#navigation::item:hover { background: #1A1F2B; }
QCheckBox { spacing: 7px; }
QToolTip { color: #F5F6FA; background: #1A1F2B; border: 1px solid #E73558; }
QSlider::groove:horizontal { height: 5px; background: #242D40; border-radius: 2px; }
QSlider::handle:horizontal { width: 12px; margin: -4px 0; border-radius: 6px; background: #E73558; }
QScrollArea { border: none; background: #131720; }
QScrollBar:vertical { background: #131720; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #394258; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSplitter::handle { background: #202737; width: 1px; }
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


def fit_window(window, width: int, height: int):
    """Leave room for the native frame and taskbar, using Qt logical pixels."""
    area = window.screen().availableGeometry()
    window.resize(min(width, max(1, area.width() - 32)),
                  min(height, max(1, area.height() - 64)))


class LogView(QTextBrowser):
    def __init__(self, text=""):
        super().__init__()
        self.setOpenExternalLinks(False)
        self.setMinimumHeight(58)
        self.setText(text)

    def setText(self, text):
        self.setPlainText(text)

    def setWordWrap(self, enabled):
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere if enabled else QTextOption.WrapMode.NoWrap)


class Preview(QGraphicsView):
    region_selected = Signal(tuple)

    def __init__(self, text="Нет изображения"):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.scene().addText(text).setDefaultTextColor(QColor("#9299A8"))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMinimumSize(200, 170)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._image = None
        self._zoomed = False
        self.selection_mode = False
        self._selection_start = self._selection_item = None

    def set_image(self, image: Image.Image):
        self._image = image
        self._selection_item = None
        self.scene().clear()
        self.scene().addPixmap(pixmap(image))
        self.setSceneRect(0, 0, image.width, image.height)
        self.fit_image()

    def fit_image(self):
        if self._image:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoomed = False

    def zoom(self, factor):
        if self._image and .02 < self.transform().m11()*factor < 40:
            self.scale(factor, factor)
            self._zoomed = True

    def wheelEvent(self, event):
        self.zoom(1.15 if event.angleDelta().y() > 0 else 1/1.15)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._zoomed:
            self.fit_image()

    def mousePressEvent(self, event):
        if self.selection_mode and self._image and event.button() == Qt.MouseButton.LeftButton:
            self._selection_start = self.mapToScene(event.position().toPoint())
            if self._selection_item:
                self.scene().removeItem(self._selection_item)
            self._selection_item = self.scene().addRect(QRectF(self._selection_start, self._selection_start),
                                                       QPen(QColor("#E73558"), 2))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._selection_start is not None:
            self._selection_item.setRect(QRectF(self._selection_start,
                                                self.mapToScene(event.position().toPoint())).normalized())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._selection_start is not None:
            rect = self._selection_item.rect().intersected(self.sceneRect())
            self._selection_start = None
            if rect.width() >= 2 and rect.height() >= 2:
                self.region_selected.emit((rect.x()/self._image.width, rect.y()/self._image.height,
                                           rect.width()/self._image.width, rect.height()/self._image.height))
            event.accept()
            return
        super().mouseReleaseEvent(event)


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
