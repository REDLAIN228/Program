from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox, QPushButton, QProgressBar,
                               QScrollArea, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from app.ai import OpenAIImageProvider, ProviderSettings, read_key, save_key
from app.automation import DrawingExecutor, SafetyError
from app.imaging import blank_white_canvas, open_image
from app.game_profile import selection_clicks
from app.layout import FORMATS, drawing_rect
from app.models import Plan, Rect, Stroke, Timing, estimate_plan
from app.planner import PlanOptions, build_plan, render_plan, render_placement
from app.storage import Store
from app.ui.calibration import CalibrationDialog, ClickImage
from app.ui.common import Job, Preview, STYLE, fit_window
from app.ui.floating import FloatingIcon
from app.ui.test_canvas import QtCanvasBackend, TestCanvas


class DrawJob(Job):
    stats = Signal(int, int, float, float)
    state = Signal(str)


class DebugOverlay(QWidget):
    def __init__(self, state, profile):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.profile = profile
        self.setGeometry(state.client.x, state.client.y, state.client.width, state.client.height)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QPen(QColor("#ff375f"), 3))
        for name, r in [("CANVAS", self.profile.canvas), ("CHARACTER", self.profile.character)]:
            if r:
                p.drawRect(r.x, r.y, r.width, r.height)
                p.drawText(r.x + 8, r.y + 20, name)
        for item in self.profile.swatches + self.profile.brushes:
            x, y = item.point
            p.drawEllipse(QPoint(x, y), 6, 6)


class MainWindow(QMainWindow):
    hotkey_pause = Signal()
    hotkey_stop = Signal()

    def __init__(self, store: Store | None = None):
        super().__init__()
        self.store = store or Store()
        self.settings = self.store.settings()
        self.profiles = self.store.profiles()
        self.setWindowTitle("ANIME DRAWER · TURBO + SIZE")
        self.setStyleSheet(STYLE)
        self.setWindowOpacity(.98)
        self.setAcceptDrops(True)
        self.original = self.processed = self.plan = None
        self.original_source = None
        self.character_reference = None
        self.profile = None
        self.target = None
        self.local_canvas = None
        self.local_mode = False
        self.native_test = os.name == "nt"
        self.job = self.executor = None
        self.debug = None
        self.hotkeys = None
        self.hotkeys_ready = os.name != "nt"
        self._closing = False
        self._loading = False
        self._pending_run = False
        self._pending_capture = False
        self._state = "IDLE"
        self._build_ui()
        fit_window(self, 620, 840)
        self._loading = True
        for key, control in [("draw_style", self.style), ("draw_quality", self.quality),
                             ("draw_speed", self.speed), ("draw_limit", self.limit), ("draw_brushwork", self.brushwork),
                             ("draw_format", self.drawing_format), ("draw_scale", self.drawing_scale)]:
            if self.settings.get(key) and control.findText(self.settings[key]) >= 0:
                control.setCurrentText(self.settings[key])
        self.crop_fit.setChecked(bool(self.settings.get("draw_crop", False)))
        self.remove_bg.setChecked(bool(self.settings.get("draw_remove_bg", False)))
        self.drawing_width.setValue(int(self.settings.get("draw_width", 300)))
        self.drawing_height.setValue(int(self.settings.get("draw_height", 300)))
        self._format_changed()
        self._loading = False
        self.icon = FloatingIcon()
        self.icon.opened.connect(self.toggle)
        self.icon.quit_requested.connect(self.quit_app)
        self.icon.moved.connect(self.remember_icon)
        self.icon.opacity_changed.connect(lambda value: self.save_setting("icon_opacity", value))
        self.icon.setWindowOpacity(self.settings.get("icon_opacity", .86))
        screens = QApplication.screens()
        point = QPoint(*self.settings.get("icon_position", [40, 120]))
        if not any(s.availableGeometry().contains(point) for s in screens):
            point = screens[0].availableGeometry().topLeft() + QPoint(40, 80)
        self.icon.move(point)
        self.icon.show()
        self.hotkey_pause.connect(self.pause)
        self.hotkey_stop.connect(self.stop)
        QShortcut(QKeySequence("Ctrl+V"), self, activated=self.paste_image)
        QShortcut(QKeySequence("F8"), self, activated=self.pause)
        QShortcut(QKeySequence("F9"), self, activated=self.stop)
        self.refresh_profiles()
        QTimer.singleShot(100, self.start_hotkeys)

    def _build_ui(self):
        base = QWidget()
        outer = QVBoxLayout(base)
        outer.setContentsMargins(22, 18, 22, 18)
        top = QHBoxLayout()
        brand = QLabel("ANIME DRAWER")
        brand.setObjectName("brand")
        top.addWidget(brand)
        top.addStretch()
        self.status = QLabel("●  IDLE")
        self.status.setStyleSheet("color: #f46a81; font-weight: bold;")
        top.addWidget(self.status)
        outer.addLayout(top)
        subtitle = QLabel("DESKTOP AUTO PAINTER   /   CPU   /   ORDINARY INPUT")
        subtitle.setObjectName("muted")
        outer.addWidget(subtitle)
        if os.name != "nt":
            banner = QLabel("Linux: доступен локальный тест Qt. Внешний ввод и Roblox требуют Windows.")
            banner.setWordWrap(True)
            outer.addWidget(banner)
        form = QFormLayout()
        self.source = QComboBox()
        self.source.addItems(["Image", "Character", "Text"])
        form.addRow("SOURCE", self.source)
        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText("Опишите образ, позу, свет и детали для AI…")
        self.prompt.setMaximumHeight(78)
        form.addRow("PROMPT", self.prompt)
        self.style = QComboBox()
        self.style.addItems(["Anime", "Manga", "Detailed Anime", "Black & White", "Sketch", "Comic", "Pixel Art", "Custom"])
        form.addRow("ART STYLE", self.style)
        self.brushwork = QComboBox()
        self.brushwork.addItems(["По форме", "Построчно"])
        form.addRow("ШТРИХИ", self.brushwork)
        options = QHBoxLayout()
        self.quality = QComboBox()
        self.quality.addItems(["Fast", "Balanced", "Detailed", "Ultra Detailed", "Full HD"])
        self.quality.setToolTip("Full HD: расчёт до 1920 px и 128 цветов без автоматического снижения качества. "
                               "Размер результата ограничен выбранным холстом.")
        self.quality.setCurrentText("Balanced")
        self.speed = QComboBox()
        self.speed.addItems(["Slow", "Safe", "Normal", "Fast", "Turbo · 5", "Turbo · 6", "Turbo · 7"])
        self.speed.setCurrentText("Turbo · 7")
        self.speed.setToolTip("7 ступеней: Normal — третья, Turbo · 7 — на четыре выше. "
                             "Ожидание подтверждения размера кисти сохраняется.")
        self.limit = QComboBox()
        self.limit.addItems(["Auto · 165 s", "60 seconds", "120 seconds", "165 seconds", "Unlimited",
                             "240 seconds", "300 seconds"])
        options.addWidget(self.quality)
        options.addWidget(self.speed)
        options.addWidget(self.limit)
        form.addRow("QUALITY / SPEED / TIME", options)
        sizing = QHBoxLayout()
        self.drawing_format = QComboBox()
        self.drawing_format.addItems(list(FORMATS))
        self.drawing_scale = QComboBox()
        self.drawing_scale.addItems(["25%", "50%", "75%", "100%"])
        self.drawing_scale.setCurrentText("100%")
        sizing.addWidget(self.drawing_format)
        sizing.addWidget(self.drawing_scale)
        form.addRow("ФОРМАТ / МАСШТАБ", sizing)
        dimensions = QHBoxLayout()
        self.drawing_width, self.drawing_height = QSpinBox(), QSpinBox()
        for spin in (self.drawing_width, self.drawing_height):
            spin.setRange(32, 8192)
            spin.setValue(300)
            spin.setSuffix(" px")
            spin.setToolTip("Свой размер рисунка. Максимум — размер текущего холста.")
        dimensions.addWidget(self.drawing_width)
        dimensions.addWidget(QLabel("×"))
        dimensions.addWidget(self.drawing_height)
        form.addRow("СВОЙ РАЗМЕР · Ш × В", dimensions)
        self.profile_combo = QComboBox()
        form.addRow("PROFILE", self.profile_combo)
        outer.addLayout(form)
        preprocess = QHBoxLayout()
        self.crop_fit = QCheckBox("Заполнить кадр обрезкой")
        self.remove_bg = QCheckBox("Удалить фон · GrabCut")
        preprocess.addWidget(self.crop_fit)
        preprocess.addWidget(self.remove_bg)
        outer.addLayout(preprocess)
        grid = QGridLayout()
        tools_menu = QMenu(self)
        self.actions = {}
        buttons = [("CAPTURE", self.capture), ("IMPORT IMAGE", self.import_image), ("GENERATE", self.generate),
                   ("PREVIEW", self.make_plan), ("CALIBRATE", self.calibrate), ("TEST DRAW", self.test_draw),
                   ("LOCAL CANVAS", self.open_test_canvas), ("AI SETTINGS", self.ai_settings), ("CROP IMAGE", self.crop_image),
                   ("LOAD PLAN", self.load_plan), ("SAVE PLAN", self.save_plan), ("DEBUG OVERLAY", self.show_debug),
                   ("EXPORT PREVIEW PNG", self.export_preview), ("CHECK BRUSH SIZE", self.check_brush_size)]
        for i, (label, function) in enumerate(buttons):
            if i < 6:
                button = QPushButton(label)
                button.clicked.connect(function)
                grid.addWidget(button, i // 3, i % 3)
                self.actions[label] = button
            else:
                self.actions[label] = tools_menu.addAction(label, function)
        outer.addLayout(grid)
        tools_button = QPushButton("TOOLS  ▾   /   LOCAL CANVAS · AI · CROP · CACHE · DEBUG")
        tools_button.setMenu(tools_menu)
        outer.addWidget(tools_button)
        self.previews = QTabWidget()
        self.original_view, self.processed_view, self.draw_view = Preview(), Preview(), Preview()
        for name, view in [("ORIGINAL", self.original_view), ("PROCESSED", self.processed_view), ("DRAW PREVIEW", self.draw_view)]:
            self.previews.addTab(view, name)
        outer.addWidget(self.previews, 1)
        self.stats = QLabel("Загрузите изображение. AI API для импорта не нужен.")
        self.stats.setWordWrap(True)
        outer.addWidget(self.stats)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        outer.addWidget(self.progress)
        self.log = QLabel("Начинайте с пустого белого холста и непрозрачности кисти 100%.")
        self.log.setWordWrap(True)
        self.log.setObjectName("muted")
        self.log.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.log)
        row = QHBoxLayout()
        self.run_button = QPushButton("▶  RUN")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.run_plan)
        self.pause_button = QPushButton("PAUSE · F8")
        self.pause_button.clicked.connect(self.pause)
        self.stop_button = QPushButton("STOP · F9")
        self.stop_button.setObjectName("danger")
        self.stop_button.clicked.connect(self.stop)
        for b in [self.run_button, self.pause_button, self.stop_button]:
            row.addWidget(b)
        foot = QHBoxLayout()
        history = QPushButton("HISTORY")
        history.clicked.connect(self.history)
        foot.addWidget(history)
        foot.addStretch()
        hide = QPushButton("Свернуть в иконку")
        hide.clicked.connect(self.hide)
        foot.addWidget(hide)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(base)
        frame = QWidget()
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(scroll, 1)
        bottom = QVBoxLayout()
        bottom.setContentsMargins(18, 8, 18, 12)
        bottom.addLayout(row)
        bottom.addLayout(foot)
        frame_layout.addLayout(bottom)
        self.setCentralWidget(frame)
        for control in [self.quality, self.style, self.speed, self.source, self.brushwork]:
            control.currentTextChanged.connect(self.invalidate_plan)
        self.drawing_format.currentTextChanged.connect(self._format_changed)
        self.drawing_scale.currentTextChanged.connect(self.invalidate_plan)
        self.drawing_width.valueChanged.connect(self.invalidate_plan)
        self.drawing_height.valueChanged.connect(self.invalidate_plan)
        self.crop_fit.toggled.connect(self.invalidate_plan)
        self.remove_bg.toggled.connect(self.invalidate_plan)
        self.profile_combo.currentTextChanged.connect(self.select_profile)

    def start_hotkeys(self):
        if os.name == "nt":
            from app.windows import GlobalHotkeys
            self.hotkeys = GlobalHotkeys(self.hotkey_pause.emit, self.emergency_stop)
            try:
                self.hotkeys.start()
                self.hotkeys_ready = True
            except Exception as exc:
                self.error(str(exc))

    def emergency_stop(self):
        # This callback runs in the Win32 message thread: release input immediately.
        if self.executor:
            try:
                self.executor.stop()
            except Exception:
                pass
        self.hotkey_stop.emit()

    def save_setting(self, key, value):
        self.settings[key] = value
        self.store.save_settings(self.settings)

    def remember_icon(self, x, y):
        self.save_setting("icon_position", [x, y])

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            if self.executor:
                self.executor.pause()
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def set_state(self, state):
        self._state = state
        self.status.setText("●  " + state)
        self.pause_button.setText("RESUME · F8" if state == "PAUSED" else "PAUSE · F8")
        if state == "PAUSED":
            self.icon.show()

    def error(self, message):
        self.set_state("ERROR")
        self.progress.setRange(0, 100)
        self.log.setText(message)
        self.showNormal()
        self.icon.show()
        QMessageBox.warning(self, "ANIME DRAWER", message)

    def busy(self):
        return self.job is not None or self._pending_run or self._pending_capture

    def _require_free(self):
        if self.busy():
            self.log.setText("Дождитесь текущей операции или нажмите STOP.")
            return False
        return True

    def _start_job(self, job, done):
        self.job = job
        for action in self.actions.values():
            action.setEnabled(False)
        for control in [self.source, self.quality, self.speed, self.style, self.profile_combo,
                        self.crop_fit, self.remove_bg, self.limit, self.brushwork,
                        self.drawing_format, self.drawing_scale, self.drawing_width, self.drawing_height]:
            control.setEnabled(False)
        self.run_button.setEnabled(False)
        job.progress.connect(self.job_progress)
        job.failed.connect(self.error)
        def handle_result(value):
            try:
                done(value)
            except Exception as exc:
                self.error(str(exc))
        job.result.connect(handle_result)
        job.finished.connect(self._job_finished)
        job.start()

    def _job_finished(self):
        previous = self.job
        self.job = None
        self.executor = None
        for action in self.actions.values():
            action.setEnabled(True)
        for control in [self.source, self.quality, self.speed, self.style, self.profile_combo,
                        self.crop_fit, self.remove_bg, self.limit, self.brushwork,
                        self.drawing_format, self.drawing_scale, self.drawing_width, self.drawing_height]:
            control.setEnabled(True)
        self._update_size_controls()
        self.run_button.setEnabled(True)
        self.progress.setRange(0, 100)
        if self._state in {"PROCESSING", "GENERATING"}:
            self.set_state("IDLE")
        self.icon.show()
        if previous:
            previous.deleteLater()
        if self._closing:
            QTimer.singleShot(0, self.quit_app)

    def job_progress(self, fraction, text):
        self.progress.setRange(0, 100)
        self.progress.setValue(round(fraction * 100))
        self.log.setText(text)

    def invalidate_plan(self, *_):
        if not self._loading:
            self.plan = None
            self.stats.setText("Настройки изменены. Нажмите PREVIEW для пересчёта.")
            self.settings.update(draw_style=self.style.currentText(), draw_quality=self.quality.currentText(),
                                 draw_speed=self.speed.currentText(), draw_limit=self.limit.currentText(),
                                 draw_brushwork=self.brushwork.currentText(),
                                 draw_format=self.drawing_format.currentText(), draw_scale=self.drawing_scale.currentText(),
                                 draw_width=self.drawing_width.value(), draw_height=self.drawing_height.value(),
                                 draw_crop=self.crop_fit.isChecked(), draw_remove_bg=self.remove_bg.isChecked())
            self.store.save_settings(self.settings)

    def _update_size_controls(self):
        custom = self.drawing_format.currentText() == "Свой размер"
        free = not self.busy()
        self.drawing_width.setEnabled(custom and free)
        self.drawing_height.setEnabled(custom and free)
        self.drawing_scale.setEnabled(not custom and free)

    def _format_changed(self, *_):
        self._update_size_controls()
        self.invalidate_plan()

    def set_original(self, image, kind="import"):
        self.original = image.convert("RGB")
        self.original_source = self.source.currentText()
        self.original_view.set_image(self.original)
        self.previews.setCurrentIndex(0)
        self.invalidate_plan()
        path = self.store.archive_image(self.original)
        self.store.record(kind, {"width": image.width, "height": image.height, "image": str(path)})
        self.set_state("IDLE")

    def import_image(self):
        if not self._require_free():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Импорт изображения", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.load_image(path)

    def load_image(self, path):
        if not self._require_free():
            return
        try:
            self.source.setCurrentText("Image")
            self.set_original(open_image(path))
        except Exception as exc:
            self.error(str(exc))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.busy():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.load_image(url.toLocalFile())
                event.acceptProposedAction()
                break

    def paste_image(self):
        if not self._require_free():
            return
        # Keep normal text paste when editing the prompt/API fields.
        if isinstance(QApplication.focusWidget(), (QTextEdit, QLineEdit)):
            QApplication.focusWidget().paste()
            return
        from app.ui.common import pil_image
        image = QApplication.clipboard().image()
        if not image.isNull():
            self.source.setCurrentText("Image")
            self.set_original(pil_image(image), "clipboard")

    def crop_image(self):
        if not self._require_free() or self.original is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Обрезка · две противоположные точки")
        layout = QVBoxLayout(dialog)
        picture = ClickImage(self.original)
        layout.addWidget(picture)
        points = []
        def select(x, y):
            points.append((x, y))
            picture.markers = points[-2:]
            picture.update()
            if len(points) == 2:
                x0, y0 = points[0]
                box = (min(x0, x), min(y0, y), max(x0, x)+1, max(y0, y)+1)
                self.set_original(self.original.crop(box), "crop")
                dialog.accept()
        picture.clicked.connect(select)
        dialog.exec()

    def refresh_profiles(self):
        name = self.profile.name if self.profile else self.settings.get("last_profile", "")
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("— выберите профиль —")
        self.profile_combo.addItems(sorted(self.profiles))
        self.profile_combo.setCurrentText(name if name in self.profiles else "— выберите профиль —")
        self.profile_combo.blockSignals(False)
        if name in self.profiles:
            self.profile = self.profiles[name]

    def select_profile(self, name):
        self.profile = self.profiles.get(name)
        self.local_mode = False
        self.target = None
        self.invalidate_plan()
        if self.profile:
            self.save_setting("last_profile", name)
            self.log.setText("Профиль выбран. CALIBRATE — выбрать окно или переоткалибровать; "
                             "RUN проверит размеры, DPI и фокус.")

    def _save_profile(self, profile):
        self.profile = profile
        self.store.save_profile(profile)
        self.profiles[profile.name] = profile
        self.save_setting("last_profile", profile.name)
        self.refresh_profiles()
        self.invalidate_plan()

    def open_test_canvas(self):
        if not self._require_free():
            return
        if self.local_canvas is None:
            self.local_canvas = TestCanvas()
            QShortcut(QKeySequence("F8"), self.local_canvas, activated=self.pause)
            QShortcut(QKeySequence("F9"), self.local_canvas, activated=self.stop)
        self.local_canvas.show()
        self.local_canvas.raise_()
        self.local_canvas.activateWindow()
        profile = self.local_canvas.profile(native=self.native_test)
        self.local_mode = True
        self.target = int(self.local_canvas.winId())
        self._save_profile(profile)
        self.log.setText("Локальный холст готов. TEST DRAW проверяет калибровку, затем очистите холст кнопкой CLEAR. "
                         + ("Используется обычный Win32 SendInput." if self.native_test else "Linux: используется доставка Qt-событий только внутри этого приложения."))

    def _choose_target(self):
        if self.local_mode and self.local_canvas:
            return self.local_canvas.state(native=self.native_test)
        if os.name != "nt":
            raise SafetyError("Внешние окна поддерживаются на Windows. Используйте LOCAL CANVAS для локального теста.")
        from app.windows import list_windows
        states = [s for s in list_windows() if s.handle not in {int(self.winId()), int(self.icon.winId())}]
        if not states:
            raise SafetyError("Окон не найдено. Откройте Roblox в оконном или безрамочном режиме.")
        from PySide6.QtWidgets import QInputDialog
        labels = [f"{s.title} · {s.process} · {s.client.width}×{s.client.height} · {s.handle}" for s in states]
        value, ok = QInputDialog.getItem(self, "Целевое окно", "Выберите Roblox или локальный тестовый холст:", labels, 0, False)
        if not ok:
            return None
        state = states[labels.index(value)]
        self.target = state.handle
        return state

    def _get_target(self):
        if self.local_mode and self.local_canvas:
            return self.local_canvas.state(native=self.native_test)
        if self.target is not None:
            from app.windows import window_state
            return window_state(self.target)
        return self._choose_target()

    def _screenshot(self, state):
        if self.local_mode and not self.native_test:
            return self.local_canvas.screenshot()
        from app.windows import Win32Backend, capture_client
        backend = Win32Backend(state.handle)
        if not backend.is_foreground():
            raise SafetyError("Целевое окно потеряло фокус перед захватом. Повторите операцию.")
        for x, y in [(state.client.x+3, state.client.y+3),
                     (state.client.x+state.client.width//2, state.client.y+state.client.height//2)]:
            if not backend.point_belongs_to_target(x, y):
                raise SafetyError("Целевое окно перекрыто. Уберите перекрывающие окна перед захватом.")
        return capture_client(state)

    def _activate_target(self):
        if self.debug:
            self.debug.hide()
        self.hide()
        self.icon.hide()
        if self.local_mode:
            self.local_canvas.show()
            self.local_canvas.raise_()
            self.local_canvas.activateWindow()
        if os.name == "nt":
            from app.windows import focus_window
            focus_window(self.target)

    def calibrate(self):
        if not self._require_free():
            return
        try:
            self.set_state("CALIBRATING")
            previous_target = self.local_mode, self.target
            if os.name == "nt":
                # CALIBRATE must be able to switch from the local test to Roblox.
                self.local_mode, self.target = False, None
            state = self._choose_target()
            if state is None:
                self.local_mode, self.target = previous_target
                self.set_state("IDLE")
                return
            self._activate_target()
            self._pending_capture = True
            QTimer.singleShot(350, lambda: self._calibrate_snapshot(state))
        except Exception as exc:
            self.error(str(exc))

    def _calibrate_snapshot(self, _state):
        try:
            state = self._get_target()
            image = self._screenshot(state)
            self.show()
            self.icon.show()
            self._pending_capture = False
            dialog = CalibrationDialog(image, state, self)
            if dialog.exec():
                self._save_profile(dialog.result_profile)
                self.log.setText("Калибровка сохранена. Выполните TEST DRAW на свободном месте холста. "
                                 "После проверки: очистите холст → CAPTURE → PREVIEW → RUN.")
            self.set_state("IDLE")
        except Exception as exc:
            self._pending_capture = False
            self.error(str(exc))

    def capture(self):
        if not self._require_free():
            return
        try:
            state = self._get_target()
            if state is None:
                return
            if not self.profile or not self.profile.character:
                raise ValueError("В CALIBRATE выделите область нужного персонажа. Автовыбор другого игрока не используется.")
            if (state.client.width, state.client.height) != self.profile.client_size or state.dpi != self.profile.dpi:
                raise SafetyError("Изменились размеры окна или DPI. Повторите CALIBRATE.")
            if state.process.casefold() != self.profile.target_process.casefold() or state.window_class != self.profile.target_class:
                raise SafetyError("Выбранное окно не соответствует профилю персонажа")
            self.set_state("CAPTURING")
            self._activate_target()
            self._pending_capture = True
            QTimer.singleShot(350, self._capture_ready)
        except Exception as exc:
            self.error(str(exc))

    def _capture_ready(self):
        try:
            state = self._get_target()
            if ((state.client.width, state.client.height) != self.profile.client_size
                    or state.dpi != self.profile.dpi):
                raise SafetyError("Окно или DPI изменились перед захватом. Повторите CALIBRATE.")
            image = self._screenshot(state)
            r = self.profile.character
            self.source.setCurrentText("Character")
            self.character_reference = image.crop((r.x, r.y, r.x+r.width, r.y+r.height))
            self.set_original(self.character_reference, "capture")
            self.show()
            self.icon.show()
            self._pending_capture = False
            self.log.setText("Персонаж захвачен. Для копии с экрана нажмите PREVIEW. "
                             "Во вкладке ORIGINAL проверьте, не попали ли соседи; область меняется в CALIBRATE.")
        except Exception as exc:
            self._pending_capture = False
            self.error(str(exc))

    def ai_settings(self):
        if not self._require_free():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("AI Image Engine · Images API")
        layout = QFormLayout(dialog)
        endpoint = QLineEdit(self.settings.get("provider_url", "https://api.openai.com/v1"))
        model = QLineEdit(self.settings.get("provider_model", "gpt-image-1"))
        secret = QLineEdit()
        secret.setEchoMode(QLineEdit.EchoMode.Password)
        secret.setPlaceholderText("Новый ключ; пусто — сохранить существующий")
        layout.addRow("HTTPS base URL", endpoint)
        layout.addRow("Image model", model)
        layout.addRow("API key", secret)
        info = QLabel("Ключ сохраняется в системном хранилище keyring. Также поддерживается "
                      "ANIME_DRAWER_API_KEY (имеет приоритет). JSON ключ не содержит. "
                      "Для Character нужны multipart /images/edits; для Text — /images/generations. "
                      "Использование API может быть платным.")
        info.setWordWrap(True)
        layout.addRow(info)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(dialog.reject)
        def save():
            try:
                # Validate URL without a network call or exposing the key.
                OpenAIImageProvider(ProviderSettings(endpoint.text().strip(), model.text().strip()), "validation-only")
                if secret.text():
                    save_key(secret.text())
                self.settings.update(provider_url=endpoint.text().strip(), provider_model=model.text().strip())
                self.store.save_settings(self.settings)
                dialog.accept()
            except Exception as exc:
                QMessageBox.warning(dialog, "AI Settings", str(exc))
        buttons.accepted.connect(save)
        layout.addRow(buttons)
        dialog.resize(540, 280)
        dialog.exec()

    def generate(self):
        if not self._require_free():
            return
        try:
            mode = self.source.currentText()
            if mode == "Character" and self.character_reference is None:
                raise ValueError("Сначала CAPTURE нужного персонажа")
            if not self.prompt.toPlainText().strip():
                raise ValueError("Введите PROMPT")
            settings = ProviderSettings(self.settings.get("provider_url", "https://api.openai.com/v1"),
                                        self.settings.get("provider_model", "gpt-image-1"))
            provider = OpenAIImageProvider(settings, read_key())
            reference = (self.character_reference.copy() if mode == "Character" else
                         self.original.copy() if mode == "Image" and self.original else None)
            if QMessageBox.question(self, "AI generation", f"Отправить {'изображение и описание' if reference else 'описание'} "
                                    f"провайдеру {settings.base_url}? Запрос может быть платным.") != QMessageBox.StandardButton.Yes:
                return
            prompt = self.prompt.toPlainText() + "\nArt style: " + self.style.currentText()
            if reference:
                prompt += "\nPreserve the recognizable clothing, colors and accessories of the reference. Square composition."
            self.set_state("GENERATING")
            self.progress.setRange(0, 0)
            self.log.setText("Ожидание AI API. STOP отменит использование результата; запрос на сервере может продолжиться.")
            self._start_job(Job(lambda _: provider.generate(prompt, reference), self),
                            lambda result: self.set_original(result, "ai"))
        except Exception as exc:
            self.error(str(exc))

    def time_limit(self):
        return [165, 60, 120, 165, None, 240, 300][self.limit.currentIndex()]

    def make_plan(self):
        if not self._require_free():
            return
        if self.original is None:
            self.error("Сначала импортируйте, захватите или сгенерируйте изображение")
            return
        if self.original_source != self.source.currentText():
            self.error("Источник изменён. Для Character выполните CAPTURE, для Text — GENERATE, "
                       "для Image — IMPORT IMAGE.")
            return
        p = self.profile
        full_hd = self.quality.currentText() == "Full HD"
        target_size = (p.canvas.width, p.canvas.height) if p else ((1920, 1080) if full_hd else (512, 512))
        try:
            area = drawing_rect(target_size, self.drawing_format.currentText(),
                                int(self.drawing_scale.currentText().rstrip("%")),
                                (self.drawing_width.value(), self.drawing_height.value()))
            widths = tuple(b.pixels for b in p.brushes) if p else ((1, 3, 9, 18, 36) if full_hd else (3, 9, 18))
            widths = tuple(w for w in widths if w < min(area.width, area.height)-4)
            if not widths:
                raise ValueError("Для такого размера нет подходящей кисти. Увеличьте рисунок или добавьте тонкую кисть.")
        except ValueError as exc:
            self.error(str(exc))
            return
        options = PlanOptions((area.width, area.height),
                              self.quality.currentText(), self.style.currentText(), self.speed.currentText(),
                              self.time_limit(), [s.rgb for s in p.swatches] if p and not p.color_wheel else None,
                              widths,
                              self.crop_fit.isChecked(), self.remove_bg.isChecked(),
                              *(selection_clicks(p) if p else (1, 1)),
                              stroke_style="Shape" if self.brushwork.currentIndex() == 0 else "Scanline")
        original = self.original.copy()
        self.set_state("PROCESSING")
        def process(job):
            plan, processed = build_plan(original, options, job.progress.emit, job.cancel)
            if (area.width, area.height) != target_size:
                plan.drawing_rect = area
                plan.target_canvas_size = target_size
                plan.notes.append(f"Рисунок {area.width}×{area.height} по центру холста {target_size[0]}×{target_size[1]}.")
            return plan, processed, render_placement(plan)
        self._start_job(Job(process, self), self._plan_ready)

    def _plan_ready(self, result):
        self.plan, self.processed, preview = result
        self.processed_view.set_image(self.processed)
        self.draw_view.set_image(preview)
        self.previews.setCurrentIndex(2)
        self.stats.setText(f"Рисунок {self.plan.canvas_size[0]}×{self.plan.canvas_size[1]} px · "
                           f"{len(self.plan.strokes)} штрихов · {len(self.plan.palette)} цветов · "
                           f"оценка {self.plan.estimated_seconds:.1f} с (зависит от игры)")
        self.log.setText("\n".join(self.plan.notes))
        self.store.save_plan(self.plan)
        self.set_state("IDLE")
        self.progress.setValue(100)

    def export_preview(self):
        if self.plan is None:
            self.error("Сначала выполните PREVIEW")
            return
        path, _ = QFileDialog.getSaveFileName(self, "PNG в выбранном размере рисунка", "drawing-preview.png", "PNG (*.png)")
        if path:
            try:
                render_plan(self.plan).save(path, format="PNG")
                self.log.setText(f"PNG сохранён: {self.plan.canvas_size[0]}×{self.plan.canvas_size[1]} px.")
            except Exception as exc:
                self.error(str(exc))

    def save_plan(self):
        if self.plan is None:
            self.error("Сначала выполните PREVIEW")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить план", "drawing-plan.json", "JSON (*.json)")
        if path:
            from app.storage import write_json
            try:
                write_json(Path(path), self.plan.to_dict())
            except Exception as exc:
                self.error(str(exc))

    def load_plan(self):
        if not self._require_free():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Открыть план", str(self.store.root / "plans"), "JSON (*.json)")
        if path:
            try:
                plan = self.store.load_plan(path)
                self.plan = plan
                self.draw_view.set_image(render_placement(plan))
                self.previews.setCurrentIndex(2)
                self.stats.setText(f"Кэш: {plan.canvas_size[0]}×{plan.canvas_size[1]} px · "
                                   f"{len(plan.strokes)} штрихов · {plan.estimated_seconds:.1f} с")
                self.log.setText("План загружен. RUN проверит соответствие текущей калибровке.")
            except Exception as exc:
                self.error(str(exc))

    def _backend(self):
        if self.local_mode and not self.native_test:
            return QtCanvasBackend(self.local_canvas)
        from app.windows import Win32Backend
        return Win32Backend(self.target)

    def run_plan(self):
        if not self._require_free():
            return
        try:
            if not self.plan or not self.profile:
                raise ValueError("Нужны профиль калибровки и PREVIEW")
            if not self.hotkeys_ready:
                raise SafetyError("Глобальная аварийная остановка F9 не зарегистрирована")
            if not self.plan.strokes:
                raise ValueError("План пуст: изображение белое или все детали меньше доступной кисти")
            limit = self.time_limit()
            color_clicks, brush_clicks = selection_clicks(self.profile)
            self.plan.color_clicks, self.plan.brush_clicks = color_clicks, brush_clicks
            self.plan.estimated_seconds = estimate_plan(self.plan.strokes, self.plan.canvas_size, self.plan.timing,
                                                        color_clicks, brush_clicks)
            if limit is not None and self.plan.estimated_seconds > limit:
                raise ValueError("Оценка времени превышает лимит. Увеличьте TIME LIMIT или упростите изображение.")
            if self._get_target() is None:
                return
            executor = DrawingExecutor(self._backend(), self.profile)
            executor.validate_plan(self.plan)
            self._begin_draw(executor, self.plan, limit, False)
        except Exception as exc:
            self.error(str(exc))

    def check_brush_size(self):
        if not self._require_free():
            return
        try:
            p = self.profile
            if not p or not p.brush_slider or not p.brush_slider.readout:
                raise ValueError("Сначала CALIBRATE → профиль игры без доната с проверкой числа размера.")
            if not self.hotkeys_ready:
                raise SafetyError("Нужна рабочая аварийная остановка F9")
            if self._get_target() is None:
                return
            executor = DrawingExecutor(self._backend(), p)
            self.executor = executor
            self._activate_target()
            self._pending_run = True
            self.set_state("CHECKING BRUSH")
            def launch():
                self._pending_run = False
                if executor.stop_event.is_set():
                    self.executor = None
                    self.show()
                    self.icon.show()
                    self.set_state("IDLE")
                    if self._closing:
                        QTimer.singleShot(0, self.quit_app)
                    return
                sizes = [n for n in (1, 6, 16, 1) if n in {b.pixels for b in p.brushes}]
                if not sizes:
                    available = sorted({b.pixels for b in p.brushes})
                    sizes = available[:3]+available[:1]
                plan = Plan((p.canvas.width, p.canvas.height), [], Timing.preset(self.speed.currentText()),
                            0, "brush-check", [])
                job = Job(lambda j: executor.check_brushes(plan, sizes, j.progress.emit), self)
                def finished(message):
                    self.show()
                    self.icon.show()
                    self.log.setText(message)
                    self.set_state("IDLE")
                self._start_job(job, finished)
            QTimer.singleShot(1000, launch)
        except Exception as exc:
            self.error(str(exc))

    def test_draw(self):
        if not self._require_free():
            return
        try:
            if not self.profile:
                raise ValueError("Сначала CALIBRATE или LOCAL CANVAS")
            if not self.hotkeys_ready:
                raise SafetyError("Нужна рабочая аварийная остановка F9")
            if self._get_target() is None:
                return
            description = ("Программа нарисует три полоски: чёрную, красную и зелёную, сверху вниз. "
                           if self.profile.color_wheel else "Программа нарисует короткую линию в центре холста. ")
            if QMessageBox.question(self, "TEST DRAW · реальный ввод", description +
                                    "Выставьте непрозрачность 100%, откройте калиброванную палитру. Продолжить?") != QMessageBox.StandardButton.Yes:
                return
            p = self.profile
            if p.color_wheel:
                widths = sorted(b.pixels for b in p.brushes)
                thin, thick = widths[0], widths[min(1, len(widths)-1)]
                strokes = [Stroke(((.42, y), (.58, y)), color, width)
                           for y, color, width in [(.47, (0, 0, 0), thin),
                                                   (.50, (255, 0, 0), thick), (.53, (0, 255, 0), thin)]]
            else:
                color = min(p.swatches, key=lambda s: sum(s.rgb)).rgb
                strokes = [Stroke(((.42, .50), (.58, .50)), color, min(b.pixels for b in p.brushes))]
            timing = Timing.preset(self.speed.currentText() if p.brush_slider and p.brush_slider.readout else "Safe")
            clicks = selection_clicks(p)
            plan = Plan((p.canvas.width, p.canvas.height), strokes, timing,
                        estimate_plan(strokes, (p.canvas.width, p.canvas.height), timing, *clicks), "test",
                        [s.color for s in strokes], color_clicks=clicks[0], brush_clicks=clicks[1])
            executor = DrawingExecutor(self._backend(), p)
            self._begin_draw(executor, plan, None, True)
        except Exception as exc:
            self.error(str(exc))

    def _begin_draw(self, executor, plan, limit, test):
        self.executor = executor
        self._pending_run = True
        try:
            self._activate_target()
        except Exception:
            self._pending_run = False
            self.executor = None
            raise
        # Give the target time to repaint after app/overlay windows are hidden.
        QTimer.singleShot(1000, lambda: self._launch_draw(executor, plan, limit, test))

    def _launch_draw(self, executor, plan, limit, test):
        self._pending_run = False
        if executor.stop_event.is_set():
            self.executor = None
            self.icon.show()
            if self._closing:
                QTimer.singleShot(0, self.quit_app)
            return
        try:
            snapshot = self._screenshot(self._get_target())
            if not blank_white_canvas(snapshot, self.profile.canvas):
                raise SafetyError("Холст уже закрашен или не белый. Очистите его в игре перед TEST DRAW / RUN. "
                                  "Белые области плана рассчитаны на пустой белый фон.")
            before = snapshot if test else None
            job = DrawJob(lambda j: executor.run(plan, j.stats.emit, j.state.emit, limit, not test), self)
            job.stats.connect(self.live_stats)
            job.state.connect(self.set_state)
            if test:
                done = lambda outcome: self._test_finished(outcome, before, plan)
            else:
                done = lambda outcome: self._draw_finished(outcome, plan, executor.completed)
            self._start_job(job, done)
        except Exception as exc:
            self.executor = None
            self.error(str(exc))

    def _test_finished(self, outcome, before, test_plan=None):
        if outcome != "finished":
            self.show()
            self.log.setText("TEST DRAW остановлен; профиль не подтверждён.")
            return
        try:
            after = self._screenshot(self._get_target())
            r = self.profile.canvas
            if test_plan is not None:
                bounds = (r.x, r.y, r.x+r.width, r.y+r.height)
                a = np.asarray(before.crop(bounds), np.int16)
                b = np.asarray(after.crop(bounds), np.int16)
                changed_mask = np.max(np.abs(a-b), axis=2) > 20
                allowed = np.zeros(changed_mask.shape, dtype=bool)
                for stroke in test_plan.strokes:
                    points = [r.map(p, stroke.width/2+1) for p in stroke.points]
                    padding = max(3, int(np.ceil(stroke.width/2))+2)
                    x0 = max(0, min(p[0] for p in points)-r.x-padding)
                    x1 = min(r.width, max(p[0] for p in points)-r.x+padding+1)
                    y0 = max(0, min(p[1] for p in points)-r.y-padding)
                    y1 = min(r.height, max(p[1] for p in points)-r.y+padding+1)
                    allowed[y0:y1, x0:x1] = True
                outside = int(np.count_nonzero(changed_mask & ~allowed))
                if outside > max(12, np.count_nonzero(changed_mask)*.05):
                    self.profile.verified = False
                    self.store.save_profile(self.profile)
                    self.error("TEST DRAW: след вышел далеко за границы тестовых линий. "
                               "Толщина или инструмент не соответствуют профилю. "
                               "RUN заблокирован; выполните CHECK BRUSH SIZE и проверьте обычную кисть.")
                    return
            # Inspect the actual test-line region, not animated characters/UI.
            box = (r.x + round(r.width * .38), r.y + round(r.height * .46),
                   r.x + round(r.width * .62), r.y + round(r.height * .54))
            a, b = np.asarray(before.crop(box), np.int16), np.asarray(after.crop(box), np.int16)
            changed = int(np.count_nonzero(np.max(np.abs(a-b), axis=2) > 20))
            self.showNormal()
            self.icon.show()
            if changed < 3:
                self.profile.verified = False
                self.store.save_profile(self.profile)
                self.error("На тестовом участке не обнаружено изменения. Проверьте кисть, цвет, палитру, "
                           "координаты и поддержку обычного ввода. Если тестовые штрихи уже были, очистите участок.")
                return
            expected = ("Появились три полоски сверху вниз: чёрная, красная, зелёная? Красная толще остальных? "
                        if self.profile.color_wheel else "В центре холста появилась короткая линия нужного цвета и толщины? ")
            answer = QMessageBox.question(self, "Проверка результата", f"Изменено пикселей: {changed}. " + expected +
                    "Подтвердите визуально; автоматическое сравнение не проверяет все цвета и размеры.")
            self.profile.verified = answer == QMessageBox.StandardButton.Yes
            self.store.save_profile(self.profile)
            self.log.setText("TEST DRAW подтверждён. Очистите холст. Для персонажа: CAPTURE → PREVIEW → RUN."
                             if self.profile.verified else "Результат не подтверждён. Повторите CALIBRATE.")
        except Exception as exc:
            self.error(str(exc))

    def _draw_finished(self, outcome, plan, completed):
        image = self.store.archive_image(render_plan(plan))
        self.store.record("draw", {"source_hash": plan.source_hash, "outcome": outcome,
                                  "completed": completed, "total": len(plan.strokes),
                                  "image": str(image), "preview_only": outcome != "finished"})
        self.showNormal()
        self.log.setText(f"{'Завершено' if outcome == 'finished' else 'Остановлено'}: {completed}/{len(plan.strokes)} штрихов.")

    def live_stats(self, done, total, elapsed, remaining):
        self.progress.setRange(0, 100)
        self.progress.setValue(round(100 * done / max(1, total)))
        self.stats.setText(f"{done}/{total} штрихов · прошло {elapsed:.1f} с · "
                           f"осталось ≈{remaining:.1f} с · {done/max(.01, elapsed):.1f} штр./с")

    def pause(self):
        if self.executor:
            paused = not self.executor.pause_event.is_set()
            if not paused:
                try:
                    self._activate_target()
                except Exception as exc:
                    self.error(str(exc))
                    return
            self.executor.pause(paused)

    def stop(self):
        if self.executor:
            try:
                self.executor.stop()
            except Exception as exc:
                self.log.setText(str(exc))
        if self.job and not self.executor:
            self.job.cancel.set()
            self.log.setText("Отмена запрошена. Ожидается завершение текущего запроса/операции.")

    def show_debug(self):
        if not self._require_free() or not self.profile:
            return
        try:
            state = self._get_target()
            if state:
                if self.debug:
                    self.debug.close()
                self.debug = DebugOverlay(state, self.profile)
                self.debug.show()
                QTimer.singleShot(7000, self.debug.hide)
        except Exception as exc:
            self.error(str(exc))

    def history(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("DRAW HISTORY")
        layout = QVBoxLayout(dialog)
        path = self.store.root / "history.json"
        records = json.loads(path.read_text("utf-8")) if path.exists() else []
        records = records[::-1]
        items = QListWidget()
        view = Preview()
        for record in records:
            items.addItem(f"{record['at'][:19]} · {record['kind']} · {record.get('outcome', '')}")
        def selected(index):
            if 0 <= index < len(records) and records[index].get("image"):
                try:
                    view.set_image(open_image(records[index]["image"]))
                except Exception as exc:
                    QMessageBox.warning(dialog, "History", str(exc))
        items.currentRowChanged.connect(selected)
        layout.addWidget(items)
        layout.addWidget(view)
        use = QPushButton("Использовать изображение")
        def reuse():
            index = items.currentRow()
            if not self.busy() and 0 <= index < len(records) and records[index].get("image"):
                self.load_image(records[index]["image"])
                dialog.accept()
        use.clicked.connect(reuse)
        layout.addWidget(use)
        dialog.resize(580, 420)
        dialog.exec()

    def quit_app(self):
        if self.busy():
            self._closing = True
            self.stop()
            self.log.setText("Остановка… Окно закроется после освобождения ввода и завершения рабочего потока.")
            return
        if self.hotkeys:
            self.hotkeys.close()
        self.icon.close()
        if self.local_canvas:
            self.local_canvas.close()
        if self.debug:
            self.debug.close()
        QApplication.instance().quit()

    def closeEvent(self, event):
        # The floating launcher remains alive when the panel is closed.
        if self.executor:
            self.executor.pause()
        self.hide()
        event.ignore()
