"""Calm animated graphite background behind the workspace cards.

Only the gutters between opaque cards are repainted per frame, so the Preview
and controls are not redrawn by the decoration. Frames stop while the window is
hidden/minimized, while the engine owns external input, and when the user turns
the background or motion off.
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient, QRegion
from PySide6.QtWidgets import QWidget

GRAPHITE = QColor("#0e0e10")


class AnimatedBackdrop(QWidget):
    def __init__(self, motion, parent=None):
        super().__init__(parent)
        self.motion = motion
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._opaque: list[QWidget] = []
        self.opaque_provider = lambda: self._opaque
        self._base = None
        self._t = 0.
        self._last = time.perf_counter()
        self._paint_ms = []
        self.frames = 0
        rng = random.Random(7)  # Deterministic layout; motion is time-based.
        self._particles = [(rng.random(), rng.random(), .3+rng.random()*.7, rng.random()*math.tau) for _ in range(26)]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        motion.changed.connect(self.sync)

    # Cards that fully paint their own rectangle are excluded from frame updates.
    def add_opaque(self, widget):
        self._opaque.append(widget)

    def sync(self):
        window = self.window()
        visible = self.isVisible() and window is not None and window.isVisible() and not window.isMinimized()
        # An inactive window (user is in the game) keeps a static frame.
        active = visible and window.isActiveWindow() and self.motion.background and self.motion.decorative
        if active:
            # Very slow drift: 20 fps (10 on a weak PC) is visually continuous.
            self._timer.setInterval(100 if self.motion.low_power else 50)
            if not self._timer.isActive():
                self._last = time.perf_counter()
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def running(self) -> bool:
        return self._timer.isActive()

    def paint_cost_ms(self) -> float:
        return sum(self._paint_ms)/len(self._paint_ms) if self._paint_ms else 0.

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self, self.sync)  # Cancelled if this widget is deleted.

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event):
        self._base = None
        super().resizeEvent(event)

    def _tick(self):
        now = time.perf_counter()
        self._t += min(.2, now-self._last)
        self._last = now
        region = QRegion(self.rect())
        for widget in self.opaque_provider():
            if widget.isVisible() and widget.parentWidget() is not None:
                top_left = widget.mapTo(self, widget.rect().topLeft())
                # Keep a 5 px band so rounded card corners never show a stale frame.
                region -= QRegion(QRect(top_left, widget.size()).adjusted(5, 5, -5, -5))
        self.update(region)

    def _render_base(self):
        pixmap = QPixmap(self.size())
        pixmap.fill(GRAPHITE)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        glow = QRadialGradient(QPointF(w*.18, -h*.1), max(w, h)*.9)
        glow.setColorAt(0, QColor(42, 30, 33))
        glow.setColorAt(.55, QColor(20, 19, 22))
        glow.setColorAt(1, QColor(13, 13, 15))
        p.fillRect(pixmap.rect(), glow)
        vignette = QLinearGradient(0, 0, 0, h)
        vignette.setColorAt(0, QColor(0, 0, 0, 0))
        vignette.setColorAt(1, QColor(0, 0, 0, 90))
        p.fillRect(pixmap.rect(), vignette)
        p.end()
        self._base = pixmap

    def paintEvent(self, event):
        started = time.perf_counter()
        if self._base is None or self._base.size() != self.size():
            self._render_base()
        p = QPainter(self)
        p.setClipRegion(event.region())
        p.drawPixmap(0, 0, self._base)
        if self.motion.background:
            self._paint_motion(p, self._t if self.motion.level != "off" else 0.)
        p.end()
        self._paint_ms = (self._paint_ms+[(time.perf_counter()-started)*1000])[-60:]
        self.frames += 1

    def _paint_motion(self, p, t):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # Two very soft light pools drifting on slow Lissajous paths.
        for index, (color, radius, speed) in enumerate(((QColor(200, 62, 78, 26), .42, .021),
                                                        (QColor(235, 225, 220, 12), .36, .016))):
            cx = w*(.5+.38*math.sin(t*speed*math.tau+index*2.1))
            cy = h*(.5+.32*math.cos(t*speed*.8*math.tau+index))
            gradient = QRadialGradient(QPointF(cx, cy), max(w, h)*radius)
            gradient.setColorAt(0, color)
            gradient.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
            p.fillRect(self.rect(), gradient)
        # Brand trajectory lines with a slow travelling highlight.
        for index in range(3):
            y0 = h*(.22+index*.27)
            path_pen = QPen(QColor(255, 255, 255, 9), 1)
            p.setPen(path_pen)
            p.drawLine(QPointF(-20, y0+40), QPointF(w+20, y0-60))
            phase = (t*.035+index*.33) % 1.
            x = -20+(w+40)*phase
            y = y0+40-100*phase
            highlight = QPen(QColor(200, 69, 80, 55), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(highlight)
            p.drawLine(QPointF(x-60, y+60*100/(w+40)), QPointF(x, y))
        # Sparse dust drifting upward.
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, depth, phase in self._particles:
            px = (x*w+math.sin(t*.2+phase)*14*depth) % max(1, w)
            py = (y*h-t*6*depth) % max(1, h)
            p.setBrush(QColor(240, 225, 220, round(18+22*depth)))
            p.drawEllipse(QRectF(px, py, 1.4*depth+.6, 1.4*depth+.6))
