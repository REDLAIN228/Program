from PySide6.QtCore import Property, QPropertyAnimation, QEasingCurve, QRectF, Qt, QObject, QEvent, QVariantAnimation
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget


class HoverAnimation(QObject):
    def __init__(self, button, enabled):
        super().__init__(button)
        self.button, self.enabled = button, enabled
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(130)
        self.animation.valueChanged.connect(self.paint)
        button.installEventFilter(self)

    def paint(self, value):
        base = QColor("#E73558" if self.button.objectName() == "primary" else "#1A1F2B")
        target = QColor("#F04B6C" if self.button.objectName() == "primary" else "#2A3244")
        color = QColor(*(round(a+(b-a)*float(value)) for a, b in zip(base.getRgb()[:3], target.getRgb()[:3])))
        self.button.setStyleSheet(f"QPushButton:enabled:!checked {{ background-color: {color.name()}; }}")

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Enter, QEvent.Type.Leave) and self.enabled() and self.button.isEnabled():
            current = self.animation.currentValue()
            self.animation.stop()
            self.animation.setStartValue(float(current) if current is not None else 0.)
            self.animation.setEndValue(1. if event.type() == QEvent.Type.Enter else 0.)
            self.animation.start()
        return False


def icon(name):
    paths = {
        "dashboard": '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
        "image": '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="2"/><path d="M3 18l6-6 4 4 4-7 4 9"/>',
        "vector": '<path d="M4 18C4 3 20 21 20 6M4 18l6-2M20 6l-6 2"/><circle cx="4" cy="18" r="2"/><circle cx="20" cy="6" r="2"/>',
        "priority": '<path d="M12 3l3 6 6 3-6 3-3 6-3-6-6-3 6-3z"/>',
        "settings": '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
        "history": '<path d="M4 9a9 9 0 1 1-1 7M3 3v6h6M12 7v6l4 2"/>',
        "ai": '<path d="M12 2l2.8 7.2L22 12l-7.2 2.8L12 22l-2.8-7.2L2 12l7.2-2.8z"/>',
    }
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
           'fill="none" stroke="#b9c1d2" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
           +paths.get(name, paths["settings"])+"</svg>")
    renderer = QSvgRenderer(svg.encode())
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def minutes(seconds):
    if seconds is None:
        return "∞"
    seconds = max(0, int(seconds))
    return f"{seconds//60:02d}:{seconds%60:02d}"


class TimerRing(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(150, 150)
        self.value = 0.
        self.text, self.caption, self.risk = "00:00", "READY TO DRAW", 0
        self.animation = QPropertyAnimation(self, b"ringProgress", self)
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_progress(self):
        return self.value

    def set_progress(self, value):
        self.value = max(0., min(1., value))
        self.update()

    ringProgress = Property(float, get_progress, set_progress)

    def display(self, progress, remaining, caption, risk=0):
        self.text, self.caption, self.risk = minutes(remaining), caption, risk
        self.animation.stop()
        if not self.isVisible() or not getattr(self, "animation_enabled", lambda: True)():
            self.set_progress(progress)
            return
        self.animation.setStartValue(self.value)
        self.animation.setEndValue(progress)
        self.animation.start()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())-20
        rect = QRectF((self.width()-side)/2, (self.height()-side)/2, side, side)
        painter.setPen(QPen(QColor("#242b3a"), 6))
        painter.drawEllipse(rect)
        color = ("#8fa9df", "#f4ab55", "#e73558")[self.risk]
        painter.setPen(QPen(QColor(color), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 90*16, -round(self.value*360*16))
        font = painter.font()
        font.setPointSize(22)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#f5f6fa"))
        painter.drawText(rect.adjusted(0, 0, 0, -12), Qt.AlignmentFlag.AlignCenter, self.text)
        font.setPointSize(7)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor("#9299a8"))
        painter.drawText(rect.adjusted(0, 35, 0, 0), Qt.AlignmentFlag.AlignCenter, self.caption)
