from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout)

from app.automation import WindowState
from app.models import Brush, Calibration, Rect, Swatch
from app.ui.common import STYLE, pixmap


class ClickImage(QLabel):
    clicked = Signal(int, int)

    def __init__(self, image: Image.Image):
        super().__init__()
        self.image = image
        self.factor = min(1., 1000 / image.width, 620 / image.height)
        self.setFixedSize(round(image.width * self.factor), round(image.height * self.factor))
        self.markers = []
        self.debug_rects = []
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, event):
        self.clicked.emit(min(self.image.width - 1, max(0, round(event.position().x() / self.factor))),
                          min(self.image.height - 1, max(0, round(event.position().y() / self.factor))))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), pixmap(self.image))
        painter.setPen(QPen(QColor("#ff365b"), 2))
        for x, y in self.markers:
            x, y = x * self.factor, y * self.factor
            painter.drawLine(QPointF(x-5, y), QPointF(x+5, y))
            painter.drawLine(QPointF(x, y-5), QPointF(x, y+5))
        for r in self.debug_rects:
            painter.drawRect(round(r.x*self.factor), round(r.y*self.factor),
                             round(r.width*self.factor), round(r.height*self.factor))


class CalibrationDialog(QDialog):
    def __init__(self, image: Image.Image, state: WindowState, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CALIBRATION · координаты внутри окна")
        self.setStyleSheet(STYLE)
        self.state = state
        self.result_profile = None
        self.canvas = self.character = None
        self.tool = self.indicator = None
        self.swatches, self.brushes = [], []
        self.anchors = []
        self.mode, self.first = "canvas", None
        self.pending_width = 3
        layout = QVBoxLayout(self)
        self.name = QLineEdit("Roblox · " + str(state.client.width) + "×" + str(state.client.height))
        layout.addWidget(self.name)
        self.instructions = QLabel("Холст: отметьте верхний левый и нижний правый углы ВНУТРИ рамки.")
        self.instructions.setWordWrap(True)
        layout.addWidget(self.instructions)
        row = QHBoxLayout()
        for label, mode in [("Холст · 2 точки", "canvas"), ("Персонаж · 2 точки", "character"),
                            ("Кисть · инструмент", "tool"), ("+ Цвет палитры", "swatch"),
                            ("+ Размер кисти", "brush"), ("Индикатор цвета", "indicator")]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, m=mode: self.set_mode(m))
            row.addWidget(button)
        layout.addLayout(row)
        self.picture = ClickImage(image)
        self.picture.clicked.connect(self.select)
        scroll = QScrollArea()
        scroll.setWidget(self.picture)
        layout.addWidget(scroll)
        self.summary = QLabel("Цветов: 0 · размеров: 0")
        layout.addWidget(self.summary)
        notice = QLabel("Откройте постоянную палитру ДО снимка. Добавьте все доступные цвета и размеры. "
                        "Укажите реальную толщину в пикселях, непрозрачность выставьте 100%. "
                        "Индикатор — точка текущего выбранного цвета, а не кнопка палитры. "
                        "Круг/слайдеры и заливка без проверки не используются.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(min(1100, self.picture.width() + 50), min(850, self.picture.height() + 240))

    def set_mode(self, mode):
        if mode == "brush":
            value, ok = QInputDialog.getInt(self, "Размер кисти", "Реальная толщина следа, физические px:",
                                            self.pending_width, 1, 200)
            if not ok:
                return
            self.pending_width = value
        self.mode, self.first = mode, None
        self.instructions.setText({
            "canvas": "Холст: два противоположных угла внутри рамки.",
            "character": "Персонаж: два угла области; только нужный персонаж, без соседних игроков.",
            "tool": "Нажмите на кнопку инструмента кисти.",
            "swatch": "Нажмите в центре постоянного цветового образца. Затем подтвердите его RGB.",
            "brush": f"Нажмите кнопку, которая выбирает кисть {self.pending_width} px.",
            "indicator": "Выберите пиксель внутри однотонного индикатора текущего цвета (не палитры).",
        }[mode])

    def select(self, x, y):
        if self.mode in {"canvas", "character"}:
            if self.first is None:
                self.first = (x, y)
                self.picture.markers.append((x, y))
                self.instructions.setText("Теперь отметьте противоположный угол.")
            else:
                x0, y0 = self.first
                rect = Rect(min(x0, x), min(y0, y), abs(x-x0) + 1, abs(y-y0) + 1)
                setattr(self, self.mode, rect)
                self.first = None
                self.instructions.setText("Область сохранена. Добавьте цвета и размеры кисти.")
        elif self.mode == "swatch":
            color = QColorDialog.getColor(QColor(*self.picture.image.getpixel((x, y))[:3]), self,
                                           "Подтвердите RGB рисуемого цвета")
            if not color.isValid():
                return
            rgb = (color.red(), color.green(), color.blue())
            self.swatches = [s for s in self.swatches if s.rgb != rgb]
            self.swatches.append(Swatch(rgb, (x, y)))
            self.anchors = [a for a in self.anchors if a.point in {s.point for s in self.swatches}]
            self.anchors.append(Swatch(tuple(self.picture.image.getpixel((x, y))[:3]), (x, y)))
        elif self.mode == "brush":
            self.brushes = [b for b in self.brushes if b.pixels != self.pending_width]
            self.brushes.append(Brush(self.pending_width, (x, y)))
        elif self.mode == "tool":
            self.tool = (x, y)
        elif self.mode == "indicator":
            self.indicator = (x, y)
        self.picture.markers = ([s.point for s in self.swatches] + [b.point for b in self.brushes]
                                + [p for p in [self.tool, self.indicator, self.first] if p])
        self.picture.debug_rects = [r for r in [self.canvas, self.character] if r]
        self.picture.update()
        self.summary.setText(f"Цветов: {len(self.swatches)} · размеров: {len(self.brushes)} · "
                             f"холст: {'да' if self.canvas else 'нет'} · персонаж: {'да' if self.character else 'нет'}")

    def save(self):
        if not self.canvas:
            QMessageBox.warning(self, "Калибровка", "Выделите холст")
            return
        profile = Calibration(self.name.text().strip() or "Roblox", self.state.window_class,
                              self.state.process, (self.state.client.width, self.state.client.height),
                              self.state.dpi, self.canvas, self.swatches, self.brushes,
                              self.tool, self.character, color_indicator=self.indicator)
        profile.anchors = self.anchors
        try:
            profile.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Калибровка", str(exc))
            return
        self.result_profile = profile
        self.accept()
