from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QWidget


class FloatingIcon(QWidget):
    opened = Signal()
    quit_requested = Signal()
    moved = Signal(int, int)
    opacity_changed = Signal(float)

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(48, 48)
        self.setWindowOpacity(.86)
        self.setToolTip("ANIME DRAWER · открыть панель\nПеретащите для перемещения")
        self.anchor = self.origin = None
        self.dragged = False
        self.menu = QMenu(self)
        action = self.menu.addAction("Открыть ANIME DRAWER")
        action.triggered.connect(self.opened)
        self.menu.addAction("Прозрачность…", self.opacity_dialog)
        self.menu.addSeparator()
        self.menu.addAction("Выход", self.quit_requested)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#fa627a"), 1.5))
        painter.setBrush(QColor("#201e29"))
        painter.drawRoundedRect(2, 2, 44, 44, 14, 14)
        painter.setPen(QPen(QColor("#ef4b68"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(15, 33, 24, 14)
        painter.drawLine(24, 14, 34, 33)
        painter.drawLine(19, 27, 30, 27)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.menu.popup(event.globalPosition().toPoint())
        elif event.button() == Qt.MouseButton.LeftButton:
            self.anchor = event.globalPosition().toPoint()
            self.origin = self.pos()
            self.dragged = False

    def mouseMoveEvent(self, event):
        if self.anchor is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.anchor
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self.dragged = True
            if self.dragged:
                self.move(self.origin + delta)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.anchor is not None:
            if self.dragged:
                self.moved.emit(self.x(), self.y())
            else:
                self.opened.emit()
            self.anchor = None

    def opacity_dialog(self):
        value, ok = QInputDialog.getInt(self, "Прозрачность", "Непрозрачность, %:",
                                       round(self.windowOpacity()*100), 25, 100)
        if ok:
            self.setWindowOpacity(value / 100)
            self.opacity_changed.emit(value / 100)
