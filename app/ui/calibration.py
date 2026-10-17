from __future__ import annotations

from copy import deepcopy

from PIL import Image
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QMouseEvent, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout)

from app.automation import WindowState
from app.models import Brush, BrushSlider, Calibration, ColorWheel, Rect, Swatch
from app.game_profile import screenshot_profile
from app.ui.common import STYLE, fit_window, pixmap


class ClickImage(QLabel):
    clicked = Signal(int, int)

    def __init__(self, image: Image.Image, max_size=(1000, 620)):
        super().__init__()
        self.image = image
        self.factor = min(1., max_size[0] / image.width, max_size[1] / image.height)
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
        self.color_wheel = None
        self.color_tab = self.size_tab = None
        self.brush_slider, self.forbidden, self.adapter = None, [], None
        self.wheel_points = []
        self.mode, self.first = "canvas", None
        self.pending_width = 3
        self.history = []
        layout = QVBoxLayout(self)
        self.name = QLineEdit("Roblox · " + str(state.client.width) + "×" + str(state.client.height))
        layout.addWidget(self.name)
        preset = QPushButton("Профиль игры · 1366×768 · без доната")
        preset.clicked.connect(self.apply_game_preset)
        preset_row = QHBoxLayout()
        preset_row.addWidget(preset, 1)
        self.slider_range_button = QPushButton("Диапазон ползунка")
        self.slider_range_button.clicked.connect(self.set_slider_range)
        preset_row.addWidget(self.slider_range_button)
        layout.addLayout(preset_row)
        self.instructions = QLabel("Холст: отметьте верхний левый и нижний правый углы ВНУТРИ рамки.")
        self.instructions.setWordWrap(True)
        layout.addWidget(self.instructions)
        row = QGridLayout()
        for index, (label, mode) in enumerate([
                ("1. Холст · 2 точки", "canvas"), ("2. + Цвет палитры", "swatch"),
                ("3. + Размер кисти", "brush"), ("Кисть · инструмент", "tool"),
                ("Персонаж · 2 точки", "character"), ("Индикатор цвета", "indicator"),
                ("Круг HSV · 4 точки", "wheel"), ("Вкладки · 2 точки", "tabs"),
                ("Яркость · максимум", "value_reset")]):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, m=mode: self.set_mode(m))
            row.addWidget(button, index // 3, index % 3)
        layout.addLayout(row)
        area = self.screen().availableGeometry()
        self.picture = ClickImage(image, (max(240, area.width() - 100), max(160, area.height() - 485)))
        self.picture.clicked.connect(self.select)
        scroll = QScrollArea()
        scroll.setWidget(self.picture)
        layout.addWidget(scroll)
        status = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        status.addWidget(self.summary, 1)
        self.undo_button = QPushButton("Отменить точку · Ctrl+Z")
        self.undo_button.clicked.connect(self.undo)
        status.addWidget(self.undo_button)
        layout.addLayout(status)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo)
        notice = QLabel("Для этой игры используйте профиль без доната: бесплатный ползунок 1–100. "
                        "Вкладка Размер и инструменты 6, 7, 8 исключены. "
                        "HSV пока требует проверки в игре через TEST DRAW: чёрная, красная, зелёная полоски. "
                        "Кисть — обычная сплошная, непрозрачность 100%, стабилизатор 0%, увеличение 100%. "
                        "Для других игр можно добавить постоянные цвета вместо HSV.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText("Сохранить профиль")
        self.save_button.setToolTip("После сохранения выполните TEST DRAW в игре.")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()
        fit_window(self, max(640, self.picture.width() + 50), self.picture.height() + 445)

    def apply_game_preset(self):
        try:
            profile = screenshot_profile(self.state)
        except ValueError as exc:
            QMessageBox.warning(self, "Игровой профиль", str(exc))
            return
        self.history.append(self.snapshot())
        self.name.setText(profile.name)
        self.canvas, self.character = profile.canvas, profile.character
        self.tool, self.indicator = profile.brush_tool, None
        self.swatches, self.brushes, self.anchors = [], profile.brushes, []
        self.color_wheel, self.color_tab, self.size_tab = profile.color_wheel, profile.color_tab, profile.size_tab
        self.brush_slider, self.forbidden, self.adapter = profile.brush_slider, profile.forbidden, profile.adapter
        self.first, self.wheel_points = None, []
        self.mode = "character"
        self.instructions.setText("Профиль загружен. Проверьте рамки холста и персонажа. "
                                  "Если персонаж сместился, выделите его заново двумя точками. "
                                  "После сохранения выполните TEST DRAW.")
        self.refresh()

    def set_slider_range(self):
        if not self.brush_slider:
            return
        slider = self.brush_slider
        value, ok = QInputDialog.getText(self, "Бесплатный ползунок", "Минимум и максимум из игры, через пробел:",
                                       text=f"{slider.minimum} {slider.maximum}" if slider.minimum else "")
        if not ok:
            return
        try:
            minimum, maximum = map(int, value.replace(",", " ").split())
            if not 1 <= minimum < maximum <= 4096:
                raise ValueError()
            replacement = BrushSlider(slider.start, slider.end, minimum, maximum)
            choices = [n for n in (2, 6, 16, 32, 64) if minimum <= n <= maximum]
            if not choices:
                choices = [minimum]
            if self.canvas and max(choices) >= min(self.canvas.width, self.canvas.height):
                raise ValueError()
        except ValueError:
            QMessageBox.warning(self, "Диапазон", "Нужны два целых числа: 1 ≤ минимум < максимум ≤ 4096.")
            return
        self.history.append(self.snapshot())
        self.brush_slider = replacement
        self.brushes = [Brush(n, replacement.point(n)) for n in choices]
        self.instructions.setText("Диапазон сохранён. Проверьте реальную толщину через TEST DRAW.")
        self.refresh()

    def snapshot(self):
        return deepcopy((self.canvas, self.character, self.tool, self.indicator,
                         self.swatches, self.brushes, self.anchors, self.mode, self.first, self.pending_width,
                         self.color_wheel, self.color_tab, self.size_tab, self.wheel_points, self.name.text(),
                         self.brush_slider, self.forbidden, self.adapter))

    def undo(self):
        if not self.history:
            return
        (self.canvas, self.character, self.tool, self.indicator,
         self.swatches, self.brushes, self.anchors, self.mode, self.first, self.pending_width,
         self.color_wheel, self.color_tab, self.size_tab, self.wheel_points, name,
         self.brush_slider, self.forbidden, self.adapter) = self.history.pop()
        self.name.setText(name)
        self.instructions.setText("Последняя точка отменена. " + (
            "Отметьте противоположный угол." if self.first else "Выберите шаг и отметьте точку заново."))
        self.refresh()

    def set_mode(self, mode):
        if mode == "tabs" and self.adapter == "roblox-free-slider-v1":
            self.instructions.setText("Вкладка Размер — донатная. В этом профиле используется бесплатный ползунок.")
            return
        if mode == "brush":
            value, ok = QInputDialog.getInt(self, "Размер кисти", "Реальная толщина следа, физические px:",
                                            self.pending_width, 1, 200)
            if not ok:
                return
            self.pending_width = value
        self.mode, self.first, self.wheel_points = mode, None, []
        self.instructions.setText({
            "canvas": "Холст: два противоположных угла внутри рамки.",
            "character": "Персонаж: два угла области; только нужный персонаж, без соседних игроков.",
            "tool": "Нажмите на кнопку инструмента кисти.",
            "swatch": "Нажмите в центре постоянного цветового образца. Затем подтвердите его RGB.",
            "brush": f"Нажмите кнопку, которая выбирает кисть {self.pending_width} px.",
            "indicator": "Выберите пиксель внутри однотонного индикатора текущего цвета (не палитры).",
            "wheel": "Круг HSV: 1/4 — отметьте центр цветового круга.",
            "tabs": "1/2 — отметьте вкладку ЦВЕТ. Затем отметьте вкладку РАЗМЕР.",
            "value_reset": "Отметьте верхнюю точку вертикального ползунка яркости (белый, максимум).",
        }[mode])
        self.refresh()

    def select(self, x, y):
        previous = self.snapshot()
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
                self.instructions.setText("Область сохранена. Шаг 2: добавьте цвета; шаг 3: размеры кисти. "
                                          "Персонаж нужен только для CAPTURE.")
        elif self.mode == "swatch":
            color = QColorDialog.getColor(QColor(*self.picture.image.getpixel((x, y))[:3]), self,
                                           "Подтвердите RGB рисуемого цвета")
            if not color.isValid():
                return
            rgb = (color.red(), color.green(), color.blue())
            self.color_wheel = None
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
        elif self.mode == "wheel":
            self.wheel_points.append((x, y))
            steps = ["", "2/4 — точка на красной части кольца, посередине его толщины.",
                     "3/4 — верхний левый угол квадрата оттенков, внутри рамки.",
                     "4/4 — нижний правый угол квадрата оттенков, внутри рамки."]
            if len(self.wheel_points) == 4:
                center, red, (x0, y0), (x1, y1) = self.wheel_points
                square = Rect(min(x0, x1), min(y0, y1), abs(x1-x0)+1, abs(y1-y0)+1)
                self.color_wheel = ColorWheel(center, red, square)
                self.swatches, self.anchors, self.wheel_points = [], [], []
                self.instructions.setText("Круг задан: оттенок по часовой стрелке от красной точки. "
                                          "Добавьте вкладки и размеры кисти. TEST DRAW обязателен.")
            else:
                self.instructions.setText(steps[len(self.wheel_points)])
        elif self.mode == "tabs":
            if self.first is None:
                self.first = (x, y)
                self.instructions.setText("2/2 — отметьте вкладку РАЗМЕР.")
            else:
                self.color_tab, self.size_tab, self.first = self.first, (x, y), None
                self.instructions.setText("Вкладки сохранены. Цвет и размер будут переключаться перед выбором.")
        elif self.mode == "value_reset":
            if not self.color_wheel:
                self.instructions.setText("Сначала задайте круг HSV.")
                return
            from dataclasses import replace
            self.color_wheel = replace(self.color_wheel, value_reset=(x, y))
        self.history.append(previous)
        self.refresh()

    def refresh(self):
        self.picture.markers = ([s.point for s in self.swatches] + [b.point for b in self.brushes]
                                + [p for p in [self.tool, self.indicator, self.first, self.color_tab, self.size_tab] if p]
                                + self.wheel_points)
        if self.brush_slider:
            self.picture.markers += [self.brush_slider.start, self.brush_slider.end]
        if self.color_wheel:
            self.picture.markers += [self.color_wheel.center, self.color_wheel.red]
        self.picture.debug_rects = [r for r in [self.canvas, self.character] if r]
        if self.color_wheel:
            self.picture.debug_rects.append(self.color_wheel.square)
        self.picture.update()
        self.summary.setText(f"1. Холст: {'готов' if self.canvas else 'выделите'} · "
                             f"2. Цвет: {'HSV' if self.color_wheel else str(len(self.swatches))} · "
                             f"3. Размеров: {len(self.brushes)}")
        self.undo_button.setEnabled(bool(self.history))
        self.slider_range_button.setEnabled(self.brush_slider is not None)
        self.save_button.setEnabled(bool(self.canvas and (self.swatches or self.color_wheel) and self.brushes))

    def save(self):
        if not self.canvas:
            QMessageBox.warning(self, "Калибровка", "Выделите холст")
            return
        profile = Calibration(self.name.text().strip() or "Roblox", self.state.window_class,
                              self.state.process, (self.state.client.width, self.state.client.height),
                              self.state.dpi, self.canvas, self.swatches, self.brushes,
                              self.tool, self.character, color_indicator=self.indicator,
                              color_wheel=self.color_wheel, color_tab=self.color_tab, size_tab=self.size_tab,
                              brush_slider=self.brush_slider, forbidden=self.forbidden, adapter=self.adapter)
        profile.anchors = self.anchors
        try:
            profile.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Калибровка", str(exc))
            return
        self.result_profile = profile
        self.accept()
