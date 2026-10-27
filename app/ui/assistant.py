"""REDLAIN Assistant: an original robot-artist drawn as a 2.5D QPainter scene.

It is a layered 2D illustration with gradients, rim light, a contact shadow and
depth-based parallax; there is no 3D model or GPU requirement. Every pose comes
from a real application/engine event:

    idle       no work; breathing + blink only
    preparing  an image was imported/loaded/analysed; looks at the easel
    planning   PREVIEW job is running; sketch gesture, no invented percentage
    drawing    the engine reports strokes; the pencil follows the reported cursor
               and uses the active stroke colour; the easel shows real revealed strokes
    paused     arm lowered and still; no progress is implied
    saving     only while a project write is pending, then the confirmed result
    error      calm red visor + the concrete message and next action
    finished   "ARTWORK COMPLETE" for a moment, then idle

It never touches the mouse, sits inside the app window (no overlay), and its
frame timer runs only while the window is visible and motion is allowed.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

RED = QColor("#c84550")
STATES = ("idle", "preparing", "planning", "drawing", "paused", "saving", "error", "finished")

TITLES = {"idle": "Готов", "preparing": "Смотрю изображение", "planning": "Строю план",
          "drawing": "Рисую", "paused": "Пауза", "saving": "Сохраняю", "error": "Нужна помощь",
          "finished": "ARTWORK COMPLETE"}

APP_STATES = {
    "IDLE": "idle", "READY TO RESUME": "idle", "LOADING": "preparing", "ANALYZING": "preparing",
    "CAPTURING": "preparing", "CALIBRATING": "preparing", "COMPARING": "planning", "SIMULATING": "planning",
    "GENERATING": "planning", "PROCESSING": "planning", "DRAWING": "drawing", "SMART FINISH": "drawing",
    "CHECKING BRUSH": "drawing", "PAUSED": "paused", "ERROR": "error", "FINISHED": "finished",
    "FINISHED PARTIAL": "finished", "TIME LIMIT": "finished",
}


class AssistantModel:
    """Pure state holder (unit-testable without painting)."""

    def __init__(self):
        self.state = "idle"
        self.message = "Импортируйте картинку — я подготовлю холст."
        self.stage = ""
        self.color = (40, 40, 44)
        self.cursor = None          # Last engine-reported pen position, 0..1.
        self.save = None            # None | "pending" | "saved"
        self.events = 0

    def app_state(self, state, message=""):
        mapped = APP_STATES.get(state, self.state)
        if mapped == "idle" and self.state == "finished":
            return False  # Keep the short completion moment; the widget times it out.
        changed = mapped != self.state
        self.state = mapped
        if mapped != "drawing":
            self.cursor = None if mapped not in ("paused", "finished") else self.cursor
        if message:
            self.message = message
        return changed

    def engine_event(self, event, color=None, stage=""):
        self.events += 1
        if event.get("type") == "cursor" and "position" in event:
            x, y = event["position"]
            self.cursor = (min(1., max(0., float(x))), min(1., max(0., float(y))))
        if color is not None:
            self.color = tuple(color)
        if stage:
            self.stage = stage


class AssistantView(QWidget):
    """The painted scene only; text lives in real labels for wrapping/accessibility."""

    def __init__(self, model: AssistantModel, motion, parent=None):
        super().__init__(parent)
        self.model, self.motion = model, motion
        self.setMinimumSize(150, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        # Paints its own card-coloured background: frames never dirty the widgets below.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.background = QColor("#131315")
        self.easel_pixmap: QPixmap | None = None
        self._t = 0.
        self._last = time.perf_counter()
        self._hover = QPointF(0, 0)
        self._parallax = QPointF(0, 0)
        self._hand = QPointF(.35, .9)    # Normalized easel coordinates.
        self._paint_ms = []
        self.frames = 0
        self.degraded = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        motion.changed.connect(self._settings_changed)

    # ----- frame scheduling -------------------------------------------------
    def _settings_changed(self):
        # A new user choice gets a fresh measurement before simplifying again.
        self.degraded = False
        self._paint_ms = []
        self.frames = 0
        self.sync()

    def sync(self):
        window = self.window()
        visible = self.isVisible() and window is not None and window.isVisible() and not window.isMinimized()
        if visible and self.motion.assistant and self.motion.decorative:
            busy = self.model.state in ("drawing", "planning", "preparing", "finished")
            if not window.isActiveWindow():
                interval = 100  # The user is in another window: keep it alive, not smooth.
            elif self.degraded or self.motion.low_power or not busy:
                interval = 66
            else:
                interval = self.motion.frame_interval
            self._timer.setInterval(interval)
            if not self._timer.isActive():
                self._last = time.perf_counter()
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def running(self):
        return self._timer.isActive()

    def paint_cost_ms(self):
        return sum(self._paint_ms)/len(self._paint_ms) if self._paint_ms else 0.

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self, self.sync)  # Cancelled if this widget is deleted.

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def mouseMoveEvent(self, event):
        c = QPointF(self.width()/2, self.height()/2)
        d = event.position()-c
        self._hover = QPointF(max(-1., min(1., d.x()/c.x())), max(-1., min(1., d.y()/c.y())))
        if not self._timer.isActive():
            self._parallax = self._hover
            self.update()

    def leaveEvent(self, event):
        self._hover = QPointF(0, 0)
        if not self._timer.isActive():
            self._parallax = self._hover
            self.update()

    def _tick(self):
        now = time.perf_counter()
        dt = min(.1, now-self._last)
        self._last = now
        self._t += dt
        k = 1-math.exp(-dt*7)
        self._parallax += (self._hover-self._parallax)*k
        target = self._hand_target()
        self._hand += (target-self._hand)*(1-math.exp(-dt*(14 if self.model.state == "drawing" else 5)))
        self.update()
        # Keep the decorative cost bounded on slow machines.
        if len(self._paint_ms) >= 30 and self.paint_cost_ms() > 6 and not self.degraded:
            self.degraded = True
            self.sync()

    def _hand_target(self):
        m, t = self.model, self._t
        if m.state == "drawing" and m.cursor is not None:
            return QPointF(*m.cursor)
        if m.state == "planning":
            # Indeterminate sketch gesture: no relation to any percentage.
            return QPointF(.5+.28*math.sin(t*2.3), .45+.18*math.sin(t*3.1+1))
        if m.state == "preparing":
            return QPointF(.15, .75)
        if m.state in ("paused", "error", "idle", "saving"):
            return QPointF(.2, 1.12)
        return QPointF(.5, .6)

    # ----- painting ----------------------------------------------------------
    def paintEvent(self, event):
        started = time.perf_counter()
        if not self._timer.isActive():
            self._hand = self._hand_target()
        p = QPainter(self)
        p.fillRect(self.rect(), self.background)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scale = min(self.width()/210, self.height()/170)
        p.translate((self.width()-210*scale)/2, (self.height()-170*scale)/2)
        p.scale(scale, scale)
        self._paint_scene(p)
        p.end()
        self._paint_ms = (self._paint_ms+[(time.perf_counter()-started)*1000])[-60:]
        self.frames += 1

    def _layer(self, depth):
        return QPointF(self._parallax.x()*5*depth, self._parallax.y()*3*depth)

    def _paint_scene(self, p):
        m, t = self.model, self._t
        animate = self._timer.isActive()
        breathe = math.sin(t*1.6)*1.6 if animate and m.state not in ("error",) else 0.
        if m.state == "drawing" and animate:
            breathe *= .4
        # Contact shadow shrinks as the body lifts: cheap depth cue.
        p.setPen(Qt.PenStyle.NoPen)
        shadow = QRadialGradient(QPointF(76, 160), 52)
        shadow.setColorAt(0, QColor(0, 0, 0, 120))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(shadow)
        w = 92-breathe*1.5
        p.drawEllipse(QRectF(76-w/2, 153, w, 14))
        self._paint_easel(p, self._layer(.35))
        body = self._layer(.6)+QPointF(0, -breathe)
        self._paint_body(p, body)
        head = self._layer(1.)+QPointF(0, -breathe*1.25)
        self._paint_head(p, head, animate)
        self._paint_arm(p, body)
        self._paint_badges(p, head, animate)

    def _easel_rect(self, offset):
        return QRectF(124, 34, 74, 82).translated(offset)

    def _paint_easel(self, p, offset):
        r = self._easel_rect(offset)
        p.setPen(QPen(QColor("#3a3236"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(r.center().x(), r.bottom()), QPointF(r.center().x(), 162))
        p.drawLine(QPointF(r.left()+10, r.bottom()), QPointF(r.left()+2, 162))
        p.drawLine(QPointF(r.right()-10, r.bottom()), QPointF(r.right()-2, 162))
        frame = QLinearGradient(r.topLeft(), r.bottomRight())
        frame.setColorAt(0, QColor("#2c2c31"))
        frame.setColorAt(1, QColor("#17171a"))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(frame)
        p.drawRoundedRect(r.adjusted(-4, -4, 4, 4), 6, 6)
        paper = r
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f4f1ee"))
        p.drawRoundedRect(paper, 3, 3)
        if self.easel_pixmap is not None and not self.easel_pixmap.isNull():
            pm = self.easel_pixmap
            aspect = pm.width()/max(1, pm.height())
            width = min(paper.width(), paper.height()*aspect)
            height = width/aspect
            target = QRectF(paper.center().x()-width/2, paper.center().y()-height/2, width, height)
            p.save()
            if self.model.state == "planning":
                p.setOpacity(.35)
            p.drawPixmap(target, pm, QRectF(pm.rect()))
            p.restore()
        else:
            p.setPen(QPen(QColor(200, 69, 80, 70), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            path = QPainterPath(QPointF(paper.left()+16, paper.bottom()-18))
            path.cubicTo(QPointF(paper.left()+26, paper.top()+10), QPointF(paper.right()-20, paper.bottom()-8),
                         QPointF(paper.right()-14, paper.top()+16))
            p.drawPath(path)
        # Soft light falling on the canvas from the upper left.
        light = QLinearGradient(paper.topLeft(), paper.bottomRight())
        light.setColorAt(0, QColor(255, 255, 255, 40))
        light.setColorAt(1, QColor(0, 0, 0, 50))
        p.setBrush(light)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(paper, 3, 3)

    def _paint_body(self, p, o):
        torso = QRectF(44, 92, 66, 60).translated(o)
        g = QLinearGradient(torso.topLeft(), torso.bottomRight())
        g.setColorAt(0, QColor("#4a4a52"))
        g.setColorAt(.45, QColor("#2a2a30"))
        g.setColorAt(1, QColor("#131316"))
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.setBrush(g)
        p.drawRoundedRect(torso, 24, 24)
        # Rim light on the shaded side in brand red.
        p.setPen(QPen(QColor(200, 69, 80, 110), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(torso.adjusted(1, 1, -1, -1), -70*16, 120*16)
        # Chest emblem: stylised R / trajectory.
        chest = QPointF(torso.center().x(), torso.center().y()+2)
        p.setPen(QPen(RED, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        path = QPainterPath(chest+QPointF(-7, 9))
        path.lineTo(chest+QPointF(-7, -9))
        path.cubicTo(chest+QPointF(6, -10), chest+QPointF(7, 1), chest+QPointF(-5, 0))
        path.lineTo(chest+QPointF(7, 9))
        p.drawPath(path)
        # Left arm resting along the body.
        p.setPen(QPen(QColor("#2b2b31"), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(torso.topLeft()+QPointF(6, 20), torso.topLeft()+QPointF(-4, 46))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1.2))
        p.drawLine(torso.topLeft()+QPointF(3, 21), torso.topLeft()+QPointF(-6, 44))

    def _paint_head(self, p, o, animate):
        m, t = self.model, self._t
        neck = QRectF(70, 84, 14, 12).translated(o*.8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1d1d21"))
        p.drawRoundedRect(neck, 4, 4)
        head = QRectF(40, 36, 74, 54).translated(o)
        g = QLinearGradient(head.topLeft(), head.bottomRight())
        g.setColorAt(0, QColor("#55555e"))
        g.setColorAt(.5, QColor("#2e2e35"))
        g.setColorAt(1, QColor("#16161a"))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(g)
        p.drawRoundedRect(head, 20, 20)
        # Antenna with a status light.
        tip = head.topLeft()+QPointF(head.width()*.72, -14)
        p.setPen(QPen(QColor("#3a3a42"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(head.topLeft()+QPointF(head.width()*.68, 2), tip)
        pulse = .5+.5*math.sin(t*4) if animate and m.state in ("drawing", "saving", "planning") else .6
        glow = QRadialGradient(tip, 9)
        base = RED if m.state != "paused" else QColor("#b8b2ad")
        glow.setColorAt(0, QColor(base.red(), base.green(), base.blue(), round(150*pulse)))
        glow.setColorAt(1, QColor(base.red(), base.green(), base.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(tip, 9, 9)
        p.setBrush(base)
        p.drawEllipse(tip, 2.6, 2.6)
        # Visor: dark glass that shifts more than the head -> turning illusion.
        look = {"preparing": QPointF(5, 1), "planning": QPointF(5, 2), "drawing": QPointF(6, 2)}.get(m.state, QPointF(0, 0))
        visor = QRectF(50, 50, 54, 26).translated(o+look+self._parallax*2)
        vg = QLinearGradient(visor.topLeft(), visor.bottomLeft())
        vg.setColorAt(0, QColor("#1f1f25") if m.state != "error" else QColor("#3a1418"))
        vg.setColorAt(1, QColor("#060607"))
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.setBrush(vg)
        p.drawRoundedRect(visor, 12, 12)
        # Eyes: blink in idle states; half-closed when paused.
        blink = 1.
        if animate and m.state in ("idle", "preparing", "finished"):
            phase = t % 4.2
            blink = .15 if phase < .12 else 1.
        if m.state == "paused":
            blink = .35
        eye_color = {"error": QColor("#ff6b78"), "paused": QColor("#b8b2ad")}.get(m.state, QColor("#f6f1ec"))
        if m.state == "finished":
            eye_color = QColor("#ffd9dc")
        scan = math.sin(t*2.6)*3 if animate and m.state == "preparing" else 0
        for dx in (-11, 11):
            center = visor.center()+QPointF(dx+scan, 1)
            eg = QRadialGradient(center, 9)
            eg.setColorAt(0, QColor(eye_color.red(), eye_color.green(), eye_color.blue(), 90))
            eg.setColorAt(1, QColor(eye_color.red(), eye_color.green(), eye_color.blue(), 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(eg)
            p.drawEllipse(center, 9, 9)
            p.setBrush(eye_color)
            h = 8*blink
            p.drawRoundedRect(QRectF(center.x()-3.2, center.y()-h/2, 6.4, max(1.2, h)), 3, 3)
        # Specular streak on the glass.
        p.setPen(QPen(QColor(255, 255, 255, 46), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(visor.topLeft()+QPointF(8, 6), visor.topLeft()+QPointF(18, 4))

    def _paint_arm(self, p, o):
        m = self.model
        easel = self._easel_rect(self._layer(.35))
        shoulder = QPointF(104, 104)+o
        hand = QPointF(easel.left()+self._hand.x()*easel.width(), easel.top()+self._hand.y()*easel.height())
        # Two-bone arm with a fixed bend direction.
        upper, lower = 30., 34.
        d = hand-shoulder
        dist = max(1e-3, math.hypot(d.x(), d.y()))
        reach = min(dist, upper+lower-.5)
        hand = shoulder+d*(reach/dist)
        a = math.acos(max(-1., min(1., (upper*upper+reach*reach-lower*lower)/(2*upper*reach))))
        base = math.atan2(d.y(), d.x())
        elbow = shoulder+QPointF(math.cos(base+a)*upper, math.sin(base+a)*upper)
        p.setBrush(Qt.BrushStyle.NoBrush)  # An open path would otherwise be filled as a triangle.
        for width, color in ((10, QColor("#232328")), (7, QColor("#3b3b43"))):
            p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            path = QPainterPath(shoulder)
            path.lineTo(elbow)
            path.lineTo(hand)
            p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#4b4b55"))
        p.drawEllipse(elbow, 4, 4)
        # Pencil: brand red body, tip in the engine's active stroke colour.
        angle = math.atan2(hand.y()-elbow.y(), hand.x()-elbow.x())
        p.save()
        p.translate(hand)
        p.rotate(math.degrees(angle)-18)
        p.setBrush(RED)
        p.drawRoundedRect(QRectF(-16, -2.6, 16, 5.2), 1.5, 1.5)
        p.setBrush(QColor("#e9d8c4"))
        cone = QPainterPath(QPointF(0, -2.6))
        cone.lineTo(QPointF(6, 0))
        cone.lineTo(QPointF(0, 2.6))
        cone.closeSubpath()
        p.drawPath(cone)
        p.setBrush(QColor(*m.color) if m.state == "drawing" else QColor("#2a2a2e"))
        p.drawEllipse(QPointF(5.4, 0), 1.6, 1.6)
        p.restore()
        p.setBrush(QColor("#2f2f36"))
        p.drawEllipse(hand, 4.4, 4.4)

    def _paint_badges(self, p, head, animate):
        m, t = self.model, self._t
        if m.save == "pending":
            center = QPointF(30, 40)+head
            p.setPen(QPen(QColor(255, 255, 255, 40), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(center, 7, 7)
            p.setPen(QPen(RED, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            start = int((t*360) % 360) if animate else 90
            p.drawArc(QRectF(center.x()-7, center.y()-7, 14, 14), start*16, 100*16)
        elif m.save == "saved":
            center = QPointF(30, 40)+head
            p.setPen(QPen(QColor("#8fd19e"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(center+QPointF(-4, 0), center+QPointF(-1, 3))
            p.drawLine(center+QPointF(-1, 3), center+QPointF(5, -4))
        if m.state == "finished":
            easel = self._easel_rect(self._layer(.35))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(16, 16, 18, 210))
            band = QRectF(easel.left()-6, easel.center().y()-9, easel.width()+12, 18)
            p.drawRoundedRect(band, 5, 5)
            font = QFont(p.font())
            font.setPointSizeF(5.6)
            font.setBold(True)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, .6)
            p.setFont(font)
            p.setPen(QColor("#f6eeea"))
            p.drawText(band, Qt.AlignmentFlag.AlignCenter, "ARTWORK COMPLETE")
            if animate:
                for i in range(6):
                    phase = (t*.8+i/6) % 1.
                    a = i*math.tau/6+t*.6
                    point = easel.center()+QPointF(math.cos(a)*(30+phase*14), math.sin(a)*(26+phase*12))
                    p.setBrush(QColor(200, 69, 80, round(160*(1-phase))))
                    p.drawEllipse(point, 1.6, 1.6)


class AssistantPanel(QFrame):
    """Card with the scene, a status title and a concrete local hint."""
    visibility_changed = Signal(bool)

    def __init__(self, motion, parent=None):
        super().__init__(parent)
        self.setObjectName("assistantCard")
        self.motion = motion
        self.model = AssistantModel()
        self.view = AssistantView(self.model, motion)
        self.title = QLabel(TITLES["idle"])
        self.title.setObjectName("assistantTitle")
        self.message = QLabel(self.model.message)
        self.message.setObjectName("muted")
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header = QHBoxLayout()
        name = QLabel("REDLAIN ASSISTANT")
        name.setObjectName("eyebrow")
        header.addWidget(name)
        header.addStretch()
        self.collapse = QPushButton("—")
        self.collapse.setObjectName("ghost")
        self.collapse.setToolTip("Свернуть ассистента до строки статуса")
        self.collapse.setCheckable(True)
        self.collapse.setFixedWidth(30)
        self.collapse.toggled.connect(self.set_collapsed)
        header.addWidget(self.collapse)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(4)
        layout.addLayout(header)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.title)
        layout.addWidget(self.message)
        self._finish_timer = QTimer(self)
        self._finish_timer.setSingleShot(True)
        self._finish_timer.timeout.connect(self._finish_done)
        self._saved_timer = QTimer(self)
        self._saved_timer.setSingleShot(True)
        self._saved_timer.timeout.connect(self._saved_done)
        self._react_timer = QTimer(self)
        self._react_timer.setSingleShot(True)
        self._react_timer.timeout.connect(self._react_done)
        motion.changed.connect(self._apply_enabled)
        self._apply_enabled()

    def _apply_enabled(self):
        self.setVisible(self.motion.assistant)
        self.view.sync()

    def set_collapsed(self, collapsed):
        self.view.setVisible(not collapsed)
        self.message.setVisible(not collapsed)
        self.collapse.setText("+" if collapsed else "—")
        self.view.sync()

    def _refresh(self):
        self.title.setText(TITLES[self.model.state]+(f" · {self.model.stage}" if self.model.state == "drawing" and self.model.stage else ""))
        self.message.setText(self.model.message)
        self.view.update()

    def set_state(self, app_state, message=""):
        changed = self.model.app_state(app_state, message)
        if self.model.state == "finished" and changed:
            self._finish_timer.start(2600)
        if changed and self.model.state != "preparing":
            self._react_timer.stop()
        if changed:
            self.view.sync()  # Frame rate follows the state (busy 30 fps, calm 15 fps).
        self._refresh()

    def react_preparing(self, message, ms=1400):
        """Short real reaction to an imported/loaded image."""
        if self.model.state in ("idle", "finished", "error"):
            self.model.state = "preparing"
            self.model.message = message
            self._react_timer.start(ms)
            self._refresh()

    def _react_done(self):
        if self.model.state == "preparing":
            self.model.state = "idle"
            self._refresh()

    def _finish_done(self):
        if self.model.state == "finished":
            self.model.state = "idle"
            self._refresh()

    def set_hint(self, message):
        if self.model.state in ("idle",) and message != self.model.message:
            self.model.message = message
            self._refresh()

    def set_message(self, message):
        self.model.message = message
        self._refresh()

    def engine_event(self, event, color=None, stage=""):
        self.model.engine_event(event, color, stage)
        if stage and self.model.state == "drawing":
            self._refresh()

    def set_easel(self, pixmap):
        self.view.easel_pixmap = pixmap
        self.view.update()

    def save_status(self, status, message=""):
        if status == "pending":
            self.model.save = "pending"
            self._saved_timer.stop()
        elif status == "saved":
            self.model.save = "saved"
            self._saved_timer.start(1600)
            if message and self.model.state in ("idle", "paused"):
                self.model.message = message
        else:
            self.model.save = None
        self._refresh()

    def _saved_done(self):
        if self.model.save == "saved":
            self.model.save = None
            self.view.update()

    def close_resources(self):
        for timer in (self._finish_timer, self._saved_timer, self._react_timer, self.view._timer):
            timer.stop()
