from PySide6.QtCore import QPoint, Qt, Signal, QRectF
from PySide6.QtGui import QAction, QColor, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton


class FloatingIcon(QWidget):
    opened = Signal()
    quit_requested = Signal()
    moved = Signal(int, int)
    opacity_changed = Signal(float)
    pause_requested = Signal()
    stop_requested = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(48, 48)
        self.setWindowOpacity(.86)
        self.setToolTip("REDLAIN DRAW ENGINE · открыть панель\nПеретащите для перемещения")
        from pathlib import Path
        self.brand_renderer = QSvgRenderer(str(Path(__file__).resolve().parents[2]/"assets/redlain-icon.svg"), self)
        self.anchor = self.origin = None
        self.dragged = False
        self.progress = 0.
        self.popup = QFrame(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.popup.setStyleSheet("QFrame {background:#131720;border:1px solid #30374a;border-radius:12px;}"
                                 "QLabel {color:#f5f6fa;border:0;padding:4px;}"
                                 "QPushButton {background:#1a1f2b;color:#f5f6fa;border:1px solid #343d51;"
                                 "border-radius:6px;padding:8px;} QPushButton:hover {background:#333d53;}")
        layout = QVBoxLayout(self.popup)
        layout.addWidget(QLabel("REDLAIN DRAW ENGINE 4.0"))
        self.status_label, self.time_label = QLabel("IDLE · 0%"), QLabel("Осталось —")
        layout.addWidget(self.status_label)
        layout.addWidget(self.time_label)
        row = QHBoxLayout()
        self.pause_button, self.stop_button = QPushButton("Pause"), QPushButton("Stop · F9")
        self.pause_button.clicked.connect(self.pause_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        row.addWidget(self.pause_button)
        row.addWidget(self.stop_button)
        layout.addLayout(row)
        open_button = QPushButton("Open App")
        open_button.clicked.connect(self.opened)
        layout.addWidget(open_button)
        self.popup.setWindowOpacity(.95)
        self.menu = QMenu(self)
        action = self.menu.addAction("Открыть REDLAIN DRAW ENGINE")
        action.triggered.connect(self.opened)
        self.menu.addAction("Прозрачность…", self.opacity_dialog)
        self.menu.addSeparator()
        self.menu.addAction("Выход", self.quit_requested)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#544044"), 1.))
        painter.setBrush(QColor("#19191c"))
        painter.drawRoundedRect(2, 2, 44, 44, 14, 14)
        self.brand_renderer.render(painter, QRectF(5, 5, 38, 38))
        painter.setPen(QPen(QColor("#c84550"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(QRectF(1, 1, 46, 46), 90*16, -round(360*16*self.progress))

    def update_status(self, state, progress, remaining):
        from app.ui.instruments import minutes
        self.progress = max(0., min(1., progress))
        self.status_label.setText(f"{state} · {self.progress*100:.0f}%")
        self.time_label.setText("Осталось "+minutes(remaining))
        self.pause_button.setText("Resume" if state == "PAUSED" else "Pause")
        self.update()

    def hideEvent(self, event):
        self.popup.hide()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.popup.close()
        super().closeEvent(event)

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
                if self.popup.isVisible():
                    self.popup.hide()
                else:
                    screen = self.screen().availableGeometry()
                    self.popup.adjustSize()
                    self.popup.move(max(screen.left(), min(self.x()+52, screen.right()-self.popup.width())),
                                    max(screen.top(), min(self.y(), screen.bottom()-self.popup.height())))
                    self.popup.show()
            self.anchor = None

    def opacity_dialog(self):
        value, ok = QInputDialog.getInt(self, "Прозрачность", "Непрозрачность, %:",
                                       round(self.windowOpacity()*100), 25, 100)
        if ok:
            self.setWindowOpacity(value / 100)
            self.opacity_changed.emit(value / 100)
