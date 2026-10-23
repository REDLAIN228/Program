"""A bounded-size, event-driven preview of actual completed strokes."""
from collections import deque

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.human import STAGES
from app.raster import composite_stroke
from app.smart_timer import costs
from app.ui.common import pixmap


def prepare_restored_core(plan, executed, preview):
    """Rasterize a large saved ledger in a worker, without creating Qt objects."""
    from PIL import ImageDraw
    from app.raster import draw_stroke
    size = tuple(max(1, round(n*min(1., 420/max(plan.canvas_size)))) for n in plan.canvas_size)
    revealed, mask = Image.new("RGB", size, "white"), Image.new("L", size)
    painter = ImageDraw.Draw(mask)
    weights = costs(plan)
    stages = [0.]*7
    for index in executed:
        stroke = plan.strokes[index]
        composite_stroke(revealed, stroke, plan.canvas_size, size)
        draw_stroke(painter, stroke, plan.canvas_size, size, 255)
        stages[stroke.stage] += weights[index]
    if plan.drawing_rect:
        r = plan.drawing_rect
        preview = preview.crop((r.x, r.y, r.x+r.width, r.y+r.height))
    return dict(indices=tuple(executed), revealed=revealed, mask=mask,
                future=preview.resize(size, Image.Resampling.LANCZOS), weights=weights, stages=stages)


class LiveArtCore(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 280)
        self.plan = None
        self.status, self.operation, self.eta = "IDLE", "Импортируйте изображение", None
        self.pending = deque()
        self.done = set()
        self.active_index, self.active_stage = None, 0
        self.position = None
        self._completion = 0.
        self._complete_animation = QVariantAnimation(self)
        self._complete_animation.setDuration(700)
        self._complete_animation.setStartValue(0.)
        self._complete_animation.setEndValue(1.)
        self._complete_animation.valueChanged.connect(self._finish_frame)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._drain)

    def _finish_frame(self, value):
        self._completion = float(value)
        self.update()

    def closeEvent(self, event):
        self._timer.stop()
        self._complete_animation.stop()
        super().closeEvent(event)

    def set_plan(self, plan, executed=()):
        from app.planner import render_plan
        executed = list(executed)
        self.plan, self.done = plan, set()
        self.pending.clear()
        self._completion = 0.
        self._complete_animation.stop()
        size = tuple(max(1, round(n*min(1., 420/max(plan.canvas_size)))) for n in plan.canvas_size)
        cached = getattr(plan, "_project_preview", None)
        if cached is not None:
            if plan.drawing_rect:
                r = plan.drawing_rect
                cached = cached.crop((r.x, r.y, r.x+r.width, r.y+r.height))
            self.future = cached.resize(size, Image.Resampling.LANCZOS)
        else:
            self.future = render_plan(plan, size)
        self.revealed = Image.new("RGB", size, "white")
        self.reveal_mask = Image.new("L", size)
        self._newly_completed = executed
        self.weights = costs(plan)
        self.stage_total = [sum(w for w, s in zip(self.weights, plan.strokes) if s.stage == stage) for stage in range(7)]
        self.stage_done = [0.]*7
        self.setToolTip("\n".join(f"{i+1:02d} · {name}: {sum(s.stage == i for s in plan.strokes)} мазков" for i, name in enumerate(STAGES)))
        self.total_weight, self.completed_weight = sum(self.weights), 0.
        restored = getattr(plan, "_restored_core", None)
        if restored and restored["indices"] == tuple(executed):
            self.revealed, self.reveal_mask, self.future = restored["revealed"].copy(), restored["mask"].copy(), restored["future"]
            self.done, self.stage_done = set(executed), list(restored["stages"])
            self.completed_weight = sum(self.stage_done)
            self._newly_completed = []
        else:
            for index in executed:
                self._complete_stroke(index)
        self.eta = max(0., self.total_weight-self.completed_weight)
        self._refresh_map()
        self.status = "READY"
        self.position = None
        self.update()

    def _complete_stroke(self, index):
        if self.plan is None or index in self.done or not 0 <= index < len(self.plan.strokes):
            return
        stroke = self.plan.strokes[index]
        composite_stroke(self.revealed, stroke, self.plan.canvas_size, self.revealed.size)
        self.done.add(index)
        weight = self.weights[index]
        self.completed_weight += weight
        self.stage_done[stroke.stage] += weight

    def _refresh_map(self):
        if len(self.done) == len(self.plan.strokes):
            self.map_pixmap = pixmap(self.revealed)
            self._newly_completed = []
            return
        # Pending regions are subdued; only real completed strokes reveal color.
        future = self.future.convert("L").convert("RGB")
        muted = Image.blend(future, Image.new("RGB", future.size, (27, 28, 30)), .73)
        # White strokes are intentional too; reveal their real path using a mask.
        from app.raster import draw_stroke
        from PIL import ImageDraw
        if not hasattr(self, "reveal_mask") or self.reveal_mask.size != self.revealed.size or not self.done:
            self.reveal_mask = Image.new("L", self.revealed.size)
        painter = ImageDraw.Draw(self.reveal_mask)
        for index in getattr(self, "_newly_completed", self.done):
            draw_stroke(painter, self.plan.strokes[index], self.plan.canvas_size, self.revealed.size, 255)
        self._newly_completed = []
        muted.paste(self.revealed, mask=self.reveal_mask)
        self.map_pixmap = pixmap(muted)

    def consume(self, event):
        if self.plan is None:
            return
        self.pending.append(event)
        if not self._timer.isActive():
            self._timer.start()

    def set_status(self, status):
        self.status = status
        if status in ("PAUSED", "IDLE"):
            self._drain()
            self._timer.stop()
        elif status == "FINISHED":
            self._drain()
            if self.pending:
                self._timer.start()
        self.update()

    def _drain(self):
        changed = False
        budget = 96
        self._newly_completed = []
        while self.pending and budget:
            event = self.pending.popleft()
            budget -= 1
            if event["type"] == "rewind":
                pending, status = list(self.pending), self.status
                self.set_plan(self.plan, event["executed"])
                self.pending.extend(pending)
                self.status = status
                changed = True
            elif event["type"] == "stroke_complete":
                self._complete_stroke(event["index"])
                self._newly_completed.append(event["index"])
                changed = True
            elif event["type"] in ("stroke_start", "cursor", "operation"):
                self.active_index, self.active_stage = event["index"], event["stage"]
                self.operation = event.get("operation", self.operation)
                if "position" in event:
                    self.position = tuple(event["position"])
        if changed:
            self._refresh_map()
        if not self.pending:
            self._timer.stop()
            if self.status == "FINISHED" and self.plan and len(self.done) == len(self.plan.strokes) and self._completion == 0:
                self._complete_animation.start()
        self.update()

    @property
    def fraction(self):
        if self.plan and len(self.done) == len(self.plan.strokes):
            return 1.
        return min(1., max(0., self.completed_weight/max(1e-9, self.total_weight))) if self.plan else 0.

    def paintEvent(self, event):
        from app.ui.instruments import minutes
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        painter.setPen(QPen(QColor("#28282c"), 1))
        painter.setBrush(QColor("#101113"))
        painter.drawRoundedRect(rect, 18, 18)
        painter.setPen(QColor("#949499"))
        painter.drawText(rect.adjusted(22, 16, -22, -16), Qt.AlignmentFlag.AlignTop, "LIVE ART CORE")
        painter.drawText(rect.adjusted(22, 16, -22, -16), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                         self.status+" · "+self.operation)
        if self.plan is None:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Каждый мазок раскрывает картину")
            return
        available = QRectF(rect.x()+48, rect.y()+58, rect.width()-96, rect.height()-144)
        aspect = self.map_pixmap.width()/max(1, self.map_pixmap.height())
        width = min(available.width(), available.height()*aspect)
        height = width/aspect
        art = QRectF(available.center().x()-width/2, available.center().y()-height/2, width, height)
        painter.drawPixmap(art, self.map_pixmap, QRectF(self.map_pixmap.rect()))
        orbit = art.adjusted(-17, -17, 17, 17)
        for stage in range(7):
            start = 90*16-round(stage*360/7*16)
            span = -round((360/7-5)*16)
            painter.setPen(QPen(QColor("#303034"), 2))
            painter.drawArc(orbit, start, span)
            if self.stage_total[stage] > 0:
                fraction = min(1., self.stage_done[stage]/self.stage_total[stage])
                painter.setPen(QPen(QColor("#c83e4e" if fraction < 1 else "#eee9e5"), 2.5))
                painter.drawArc(orbit, start, round(span*fraction))
        if self.position and self.status == "DRAWING":
            x, y = self.position
            point = QPointF(art.x()+x*art.width(), art.y()+y*art.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(220, 63, 80, 38))
            painter.drawEllipse(point, 8, 8)
            painter.setBrush(QColor("#fff3ef"))
            painter.drawEllipse(point, 2.5, 2.5)
        complete = len(self.done) == len(self.plan.strokes)
        title = "ARTWORK COMPLETE" if complete and self.status == "FINISHED" else f"{self.active_stage+1:02d}  {STAGES[self.active_stage]}"
        painter.setPen(QColor("#f3f0ec"))
        painter.drawText(QRectF(rect.x()+22, rect.bottom()-76, rect.width()-44, 24), Qt.AlignmentFlag.AlignCenter, title)
        painter.setPen(QColor("#949499"))
        summary = f"{len(self.done):,} / {len(self.plan.strokes):,} мазков   ·   {self.fraction*100:.1f}%   ·   ETA {minutes(self.eta) if self.eta is not None else '—'}"
        painter.drawText(QRectF(rect.x()+22, rect.bottom()-47, rect.width()-44, 24), Qt.AlignmentFlag.AlignCenter, summary)
        if self._completion:
            painter.setPen(QPen(QColor(235, 220, 215, round(130*(1-self._completion))), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(art.adjusted(-8*self._completion, -8*self._completion,
                                                8*self._completion, 8*self._completion), 4, 4)
