from dataclasses import replace

from PIL import Image
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QComboBox, QLineEdit, QSpinBox,
                               QPushButton, QLabel, QCheckBox, QColorDialog)
from PySide6.QtGui import QColor

from app.canvas_fill import FillSettings, MODES, apply_canvas_fill, highlight_padding
from app.ui.common import Job, Preview


class PaddingPreview(Preview):
    position_clicked = Signal(float, float)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._image:
            point = self.mapToScene(event.position().toPoint())
            if 0 <= point.x() < self._image.width and 0 <= point.y() < self._image.height:
                self.position_clicked.emit(point.x()/self._image.width, point.y()/self._image.height)
        super().mousePressEvent(event)


class FillEditor(QWidget):
    settings_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source, self.mask = None, None
        self.target = (534, 530)
        self.crop = False
        self.settings = FillSettings()
        self.job, self._generation, self._dirty = None, 0, False
        self._loading = False
        box = QVBoxLayout(self)
        title = QLabel("SMART CANVAS FILL")
        title.setObjectName("sectionTitle")
        box.addWidget(title)
        self.view = PaddingPreview()
        self.view.setMinimumHeight(150)
        self.view.position_clicked.connect(self.position)
        box.addWidget(self.view, 1)
        self.info = QLabel("Поля определяются по геометрии. Белые объекты исходника сохраняются.")
        self.info.setWordWrap(True)
        box.addWidget(self.info)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(MODES)
        form.addRow("Заполнение", self.mode)
        self.text = QLineEdit("REDLAIN")
        self.text.setMaxLength(160)
        form.addRow("Текст", self.text)
        self.font_size = QSpinBox()
        self.font_size.setRange(6, 256)
        self.font_size.setValue(28)
        form.addRow("Размер", self.font_size)
        self.font = QComboBox()
        self.font.addItems(["Sans", "Serif", "Mono"])
        form.addRow("Шрифт", self.font)
        self.align = QComboBox()
        self.align.addItems(["center", "left", "right"])
        form.addRow("Выравнивание", self.align)
        self.color = QPushButton("Цвет текста / узора")
        self.color.clicked.connect(self.choose_color)
        form.addRow(self.color)
        self.highlight = QCheckBox("Подсветить только добавленные поля")
        self.highlight.setChecked(True)
        form.addRow(self.highlight)
        box.addLayout(form)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(160)
        self._timer.timeout.connect(self.update_preview)
        for control in (self.mode, self.font, self.align):
            control.currentTextChanged.connect(self.changed)
        self.text.textChanged.connect(self.changed)
        self.font_size.valueChanged.connect(self.changed)
        self.highlight.toggled.connect(lambda _: self._timer.start())

    def set_settings(self, value):
        self._loading = True
        self.settings = FillSettings.from_dict(value)
        self.mode.setCurrentText(self.settings.mode)
        self.text.setText(self.settings.text)
        self.font_size.setValue(self.settings.font_size)
        self.font.setCurrentText(self.settings.font)
        self.align.setCurrentText(self.settings.alignment)
        self._loading = False
        self._timer.start()

    def set_source(self, image, target, crop=False):
        self.source, self.target, self.crop = image.copy(), tuple(target), crop
        self._generation += 1
        self._timer.start()

    def changed(self, *_):
        if self._loading:
            return
        self.settings = replace(self.settings, mode=self.mode.currentText(), text=self.text.text(),
                                font_size=self.font_size.value(), font=self.font.currentText(), alignment=self.align.currentText())
        self._generation += 1
        self.settings_changed.emit(self.settings.to_dict())
        self._timer.start()

    def choose_color(self):
        color = QColorDialog.getColor(QColor(*self.settings.color), self, "Цвет оформления полей")
        if color.isValid():
            self.settings = replace(self.settings, color=color.getRgb()[:3])
            self.changed()

    def position(self, x, y):
        if self.mask is None:
            return
        px, py = min(self.mask.width-1, round(x*self.mask.width)), min(self.mask.height-1, round(y*self.mask.height))
        if self.mask.getpixel((px, py)) == 0:
            self.info.setText("Текст размещается только в добавленных полях. Область исходника защищена.")
            return
        self.settings = replace(self.settings, x=x, y=y)
        self.changed()

    def update_preview(self):
        if self.source is None:
            return
        if self.job:
            self._dirty = True
            return
        source, target, settings, crop = self.source.copy(), self.target, self.settings, self.crop
        generation, show_mask = self._generation, self.highlight.isChecked()
        def process(job):
            image, mask, info = apply_canvas_fill(source, target, settings, crop)
            return highlight_padding(image, mask) if show_mask else image, mask, info
        job = Job(process, self)
        self.job = job
        def ready(result):
            if generation != self._generation:
                self._dirty = True
                return
            image, self.mask, info = result
            self.view.set_image(image)
            fraction = info["padding_pixels"]/(image.width*image.height)
            self.info.setText(f"Добавленные поля: {fraction*100:.1f}%. "
                              "Нажмите на поле, чтобы разместить текст. "
                              +("Использован упрощённый рисуемый шрифт." if info["font_fallback"] else ""))
        job.result.connect(ready)
        job.failed.connect(self.info.setText)
        def finished():
            self.job = None
            job.deleteLater()
            if self._dirty:
                self._dirty = False
                self._timer.start()
        job.finished.connect(finished)
        job.start()
