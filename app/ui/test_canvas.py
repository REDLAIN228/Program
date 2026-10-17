from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QKeySequence, QMouseEvent, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QApplication, QWidget

from app.automation import WindowState
from app.models import Brush, Calibration, Rect, Swatch
from app.ui.common import GuiBridge, pil_image


COLORS = [(20, 20, 28), (240, 54, 82), (237, 153, 65), (248, 215, 92),
          (63, 177, 111), (59, 135, 221), (140, 87, 196), (244, 190, 168),
          (111, 72, 61), (155, 160, 171), (255, 255, 255), (31, 75, 86)]


class TestCanvas(QWidget):
    __test__ = False

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ANIME DRAWER · Local test canvas")
        self.resize(820, 720)
        self.color, self.brush = COLORS[0], 9
        self.image = QImage(1000, 1000, QImage.Format.Format_RGB32)
        self.image.fill(Qt.GlobalColor.white)
        self.pressed = False
        self.last = None
        self.received_segments = 0
        self.bridge = GuiBridge()
        self.setMouseTracking(True)

    def canvas_rect(self):
        return Rect(24, 142, self.width() - 48, self.height() - 166)

    def profile(self, native=False):
        state = self.state(native)
        sx, sy = state.client.width / self.width(), state.client.height / self.height()
        def point(x, y):
            return round(x * sx), round(y * sy)
        r = self.canvas_rect()
        r = Rect(round(r.x*sx), round(r.y*sy), round(r.width*sx), round(r.height*sy))
        return Calibration("Local test canvas" + (" · Win32" if native else " · Qt"),
                           state.window_class, state.process,
                           (state.client.width, state.client.height), state.dpi,
                           r, [Swatch(c, point(42 + i * 48, 42)) for i, c in enumerate(COLORS)],
                           [Brush(round(w*sx), point(50 + i * 100, 99)) for i, w in enumerate([3, 9, 18])],
                           color_indicator=point(660, 42),
                           anchors=[Swatch(c, point(42 + i * 48, 42)) for i, c in enumerate(COLORS)])

    def state(self, native=False):
        if native:
            from app.windows import window_state
            return window_state(int(self.winId()))
        pos = self.mapToGlobal(QPoint(0, 0))
        return WindowState(int(self.winId()), self.windowTitle(), "AnimeDrawerTestCanvas", "local-test",
                           Rect(pos.x(), pos.y(), self.width(), self.height()), 96)

    def screenshot(self):
        return pil_image(self.grab().toImage())

    def clear(self):
        self.image.fill(Qt.GlobalColor.white)
        self.received_segments = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#181c25"))
        for i, color in enumerate(COLORS):
            painter.fillRect(24 + i * 48, 24, 36, 36, QColor(*color))
            if self.color == color:
                painter.setPen(QPen(Qt.GlobalColor.white, 2))
                painter.drawRect(22 + i * 48, 22, 40, 40)
        painter.fillRect(640, 24, 40, 36, QColor(*self.color))
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(690, 46, "COLOR")
        for i, width in enumerate([3, 9, 18]):
            painter.fillRect(24 + i * 100, 78, 90, 42,
                             QColor("#b52f49" if self.brush == width else "#303644"))
            painter.drawText(34 + i * 100, 104, f"{width} px")
        painter.fillRect(360, 78, 115, 42, QColor("#303644"))
        painter.drawText(380, 104, "CLEAR")
        painter.drawText(500, 104, "F8 · PAUSE     F9 · STOP")
        r = self.canvas_rect()
        painter.drawImage(r.x, r.y, self.image.copy(0, 0, r.width, r.height))

    def _draw(self, start, end):
        r = self.canvas_rect()
        painter = QPainter(self.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(0, 0, r.width, r.height)
        painter.setPen(QPen(QColor(*self.color), self.brush, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(QPointF(start.x() - r.x, start.y() - r.y),
                         QPointF(end.x() - r.x, end.y() - r.y))
        self.received_segments += 1
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        for i, color in enumerate(COLORS):
            if Rect(24 + i * 48, 24, 36, 36).contains(pos.x(), pos.y()):
                self.color = color
                self.update()
                return
        for i, width in enumerate([3, 9, 18]):
            if Rect(24 + i * 100, 78, 90, 42).contains(pos.x(), pos.y()):
                self.brush = width
                self.update()
                return
        if Rect(360, 78, 115, 42).contains(pos.x(), pos.y()):
            self.clear()
        elif self.canvas_rect().contains(pos.x(), pos.y()):
            self.pressed, self.last = True, pos
            self._draw(pos, pos)

    def mouseMoveEvent(self, event):
        if self.pressed and self.canvas_rect().contains(event.position().x(), event.position().y()):
            self._draw(self.last, event.position())
            self.last = event.position()

    def mouseReleaseEvent(self, event):
        self.pressed = False
        self.last = None

    def resizeEvent(self, event):
        if self.width() > self.image.width() or self.height() > self.image.height():
            old = self.image
            self.image = QImage(max(1000, self.width()), max(1000, self.height()), QImage.Format.Format_RGB32)
            self.image.fill(Qt.GlobalColor.white)
            p = QPainter(self.image)
            p.drawImage(0, 0, old)
            p.end()
        super().resizeEvent(event)


class QtCanvasBackend:
    """App-local Qt event delivery for Linux/headless validation, never external input."""

    def __init__(self, canvas: TestCanvas):
        self.canvas = canvas
        self.position = QPointF()
        self.pressed = False

    def snapshot(self):
        return self.canvas.bridge.call(self.canvas.state)

    def is_foreground(self):
        return self.canvas.bridge.call(lambda: self.canvas.isVisible() and self.canvas.isActiveWindow())

    def point_belongs_to_target(self, x, y):
        return self.snapshot().client.contains(x, y)

    def _event(self, kind, button):
        def send():
            local = self.canvas.mapFromGlobal(self.position.toPoint())
            event = QMouseEvent(kind, QPointF(local), self.position, button,
                                Qt.MouseButton.LeftButton if self.pressed else Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(self.canvas, event)
        self.canvas.bridge.call(send)

    def move(self, x, y):
        from PySide6.QtCore import QEvent
        self.position = QPointF(x, y)
        self._event(QEvent.Type.MouseMove, Qt.MouseButton.NoButton)

    def down(self):
        from PySide6.QtCore import QEvent
        self.pressed = True
        self._event(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton)

    def up(self):
        from PySide6.QtCore import QEvent
        self.pressed = False
        # Release even if STOP raced with a queued press in the GUI thread.
        self._event(QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton)

    def sample(self, x, y):
        def sample():
            p = self.canvas.mapFromGlobal(QPoint(x, y))
            return self.canvas.screenshot().getpixel((p.x(), p.y()))
        return self.canvas.bridge.call(sample)
