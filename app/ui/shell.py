"""REDLAIN 4.0 workspace: three sections, one action bar, honest status.

The controller logic (jobs, executor, projects) is unchanged and still lives in
MainWindow/V3Actions/StudioActions. This module only arranges the existing
control widgets, so project options and old plans keep their meaning:

    Рисование  — import, size/placement, mode, game check, large Preview + Live Core
    Проекты    — open / continue / copies / checkpoints (Dashboard merged here)
    Настройки  — profile + calibration tools, animations/performance, extensions

Controls that left the main flow (AI generation, Discover, legacy engines,
manual priority map, simulation views) stay reachable from Settings/advanced
sections or the "Виды" menu; nothing that still works is silently deleted.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Property, QEasingCurve, QEvent, QObject, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFormLayout, QFrame,
                               QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout,
                               QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
                               QVBoxLayout, QWidget)

from app.ui.assistant import AssistantPanel
from app.ui.backdrop import AnimatedBackdrop
from app.ui.common import pixmap
from app.ui.motion import MOTION_LABELS, MOTION_LEVELS, Animator, MotionSettings, WindowMotion

ASSETS = Path(__file__).resolve().parents[2]/"assets"
VERSION = "4.0"

NAV = (("draw", "Рисование"), ("projects", "Проекты"), ("settings", "Настройки"), ("discover", "Discover"))
NAV_ALIASES = {"Workspace": "draw", "Live Drawing": "draw", "Dashboard": "projects", "Projects": "projects",
               "Settings": "settings", "Discover": "discover"}
MODE_TEXT = {
    "FAST": "До 12 цветов, крупные пятна, контур ±0,9 px, без доводки покрытия. Быстрее всего; мелкие детали упрощаются.",
    "BALANCED": "До 24 цветов, контур ±0,4 px, до 24 доводочных мазков. Рекомендуется для большинства картинок.",
    "MASTERPIECE": "До 64 цветов, контур ±0,15 px, до 256 доводочных мазков. Дольше; детали ограничены физической кистью.",
}
DRAWING_STATES = {"DRAWING", "SMART FINISH", "CHECKING BRUSH"}

SHELL_STYLE = """
QFrame#card { background: #161618; border: 1px solid #262629; border-radius: 14px; }
QFrame#assistantCard { background: #131315; border: 1px solid #2a2326; border-radius: 12px; }
QFrame#actionBar { background: #141416; border: 1px solid #2a2a2e; border-radius: 14px; }
QLabel#brand { font-size: 17px; font-weight: 600; letter-spacing: 1px; background: transparent; }
QLabel#eyebrow { color: #8d8d94; font-size: 10px; font-weight: 700; letter-spacing: 1.4px; background: transparent; }
QLabel#assistantTitle { font-size: 13px; font-weight: 600; color: #f4efea; }
QLabel#chip { background: #1f1c1e; border: 1px solid #3a2c30; border-radius: 10px; padding: 3px 10px; color: #f0c6ca; }
QLabel#reason { color: #f2a0a8; }
QLabel#okText { color: #9fd3ac; }
QPushButton#nav { background: transparent; border: 0; border-radius: 9px; padding: 7px 14px; color: #9a9aa1; font-size: 12px; }
QPushButton#nav:hover { background: #1f1f22; color: #e9e5e1; }
QPushButton#nav:checked { background: #2b2023; color: #ffffff; }
QPushButton#segment { border-radius: 8px; padding: 6px 10px; }
QPushButton#segment:checked { background: #3a2226; border-color: #c84550; color: #fff; }
QPushButton#ghost { background: transparent; border: 1px solid transparent; padding: 4px 6px; }
QPushButton#ghost:hover { border-color: #3a3a40; }
QPushButton#primary { font-size: 13px; padding: 10px 18px; }
QPushButton#primary:disabled { background: #24191b; border-color: #3a2a2e; color: #7b6a6d; }
QPushButton#danger:disabled { color: #6a5357; }
QPushButton::menu-indicator { width: 0; image: none; }
QPushButton:focus { border-color: #d65d69; }
QPushButton:pressed { background: #2f2427; }
QPushButton#primary:pressed { background: #8f2d38; }
QPushButton#sectionToggle { background: transparent; border: 0; text-align: left; padding: 8px 2px; color: #cfcac6; font-weight: 600; }
QPushButton#sectionToggle:hover { color: #ffffff; }
QFrame#toast { background: #1d1b1d; border: 1px solid #4a2f35; border-radius: 10px; }
QScrollArea#inspector, QScrollArea#inspector > QWidget > QWidget { background: #161618; }
QLabel { background: transparent; }
"""


def _label(text, name=None, wrap=True):
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def _button(text, action, name=None, tip=None):
    button = QPushButton(text)
    button.clicked.connect(action)
    if name:
        button.setObjectName(name)
    if tip:
        button.setToolTip(tip)
    return button


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")


class Collapsible(QWidget):
    """Section whose body opens/closes with a height animation."""

    def __init__(self, title, animator, expanded=False, parent=None):
        super().__init__(parent)
        self.animator, self.title = animator, title
        self.toggle = QPushButton()
        self.toggle.setObjectName("sectionToggle")
        self.toggle.setCheckable(True)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 4)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toggle)
        layout.addWidget(self.body)
        self.toggle.toggled.connect(self.set_expanded)
        self.toggle.setChecked(expanded)
        self.set_expanded(expanded, animate=False)

    def set_expanded(self, expanded, animate=True):
        self.toggle.setText(("▾  " if expanded else "▸  ")+self.title)
        target = self.body.sizeHint().height() if expanded else 0
        if expanded:
            self.body.show()

        def finish():
            if expanded:
                self.body.setMaximumHeight(16777215)
            else:
                self.body.hide()
        if not animate:
            self.body.setMaximumHeight(16777215 if expanded else 0)
            self.body.setVisible(expanded)
            return
        self.animator.animate(self.body, b"maximumHeight", target, 200,
                              start=self.body.height() if self.body.isVisible() else 0, finished=finish)


class Toast(QFrame):
    """Single reusable in-window notification (never stacks timers)."""

    def __init__(self, animator, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self.animator = animator
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.text = _label("", None)
        self.text.setMaximumWidth(380)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.addWidget(self.text)
        self.effect = QGraphicsOpacityEffect(self)
        self.effect.setOpacity(0.)
        self.setGraphicsEffect(self.effect)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.hide()

    def show_message(self, text, ms=3600):
        self.text.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        self.move(parent.width()-self.width()-22, 70)
        self.show()
        self.raise_()
        self.animator.animate(self.effect, b"opacity", 1., 160, start=self.effect.opacity())
        self.timer.start(ms)

    def dismiss(self):
        self.animator.animate(self.effect, b"opacity", 0., 220, start=self.effect.opacity(), finished=self.hide)


class Intro(QWidget):
    """Launch reveal over the real workspace; never delays input or loading."""

    def __init__(self, animator, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.logo = QPixmap(str(ASSETS/"redlain-icon.png"))
        self._progress = 0.
        self.animator = animator
        self.setGeometry(parent.rect())

    def get_progress(self):
        return self._progress

    def set_progress(self, value):
        self._progress = float(value)
        self.update()

    progress = Property(float, get_progress, set_progress)

    def play(self):
        self.show()
        self.raise_()
        self.animator.animate(self, b"progress", 1., 650, start=0., easing=QEasingCurve.Type.InOutCubic,
                              finished=self.deleteLater)

    def paintEvent(self, event):
        t = self._progress
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        fade = max(0., min(1., (t-.45)/.55))
        p.setOpacity(1-fade)
        p.fillRect(self.rect(), QColor("#0e0e10"))
        size = 74+18*min(1., t/.45)
        rect = QRect(round(self.width()/2-size/2), round(self.height()/2-size/2-12), round(size), round(size))
        p.setOpacity((1-fade)*min(1., t/.25))
        p.drawPixmap(rect, self.logo)
        p.setPen(QColor("#f1ece8"))
        font = p.font()
        font.setPointSize(11)
        font.setLetterSpacing(font.SpacingType.AbsoluteSpacing, 3)
        p.setFont(font)
        p.drawText(QRect(0, rect.bottom()+14, self.width(), 24), Qt.AlignmentFlag.AlignHCenter, "REDLAIN  DRAW ENGINE")


class Shell:
    def __init__(self, p):
        self.p = p
        self.motion = MotionSettings(p.settings, p.save_setting)
        self.animator = Animator(self.motion, p)
        self.window_motion = WindowMotion(p, self.animator)
        self.page_names = []
        self._compact = False
        self._full_geometry = None
        self._last_save_text = ""
        p.setStyleSheet(p.styleSheet()+SHELL_STYLE)
        p.setWindowTitle(f"REDLAIN DRAW ENGINE {VERSION}")
        icon_path = ASSETS/"redlain-icon.png"
        if icon_path.exists():
            p.setWindowIcon(QIcon(str(icon_path)))
        self._retire_previous_layout()
        self.root = AnimatedBackdrop(self.motion)
        outer = QVBoxLayout(self.root)
        outer.setContentsMargins(16, 10, 16, 12)
        outer.setSpacing(10)
        outer.addLayout(self._header())
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        self._add_page("draw", self._draw_page())
        self._add_page("projects", self._projects_page())
        self._add_page("settings", self._settings_page())
        self._add_page("discover", self._discover_page())
        outer.addWidget(self._action_bar())
        p.setCentralWidget(self.root)
        self.root.opaque_provider = self._opaque_cards
        self.toast = Toast(self.animator, self.root)
        self.navigate("draw", animate=False)
        self._apply_extensions()
        p._advanced_controls = [w for w in p._advanced_controls if w is not None]+self._extra_controls
        self.refresh_timer = QTimer(p)
        self.refresh_timer.setInterval(400)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()
        self.perf_timer = QTimer(p)
        self.perf_timer.setInterval(1000)
        self.perf_timer.timeout.connect(self._refresh_perf)
        self.perf_timer.start()
        QShortcut(QKeySequence("Ctrl+1"), p, activated=lambda: self.navigate("draw"))
        QShortcut(QKeySequence("Ctrl+2"), p, activated=lambda: self.navigate("projects"))
        QShortcut(QKeySequence("Ctrl+3"), p, activated=lambda: self.navigate("settings"))
        QShortcut(QKeySequence("Ctrl+M"), p, activated=self.toggle_compact)
        QShortcut(QKeySequence("Ctrl+O"), p, activated=p.import_image)
        QShortcut(QKeySequence("Ctrl+Return"), p, activated=p.make_plan)
        self.refresh()

    # ----- old layers -------------------------------------------------------
    def _retire_previous_layout(self):
        """Keep every control that logic references; drop the old containers."""
        p = self.p
        for hover in getattr(p, "_hover_animations", []):
            hover.animation.stop()
            hover.button.removeEventFilter(hover)
            hover.enabled = lambda: False
            hover.button.setStyleSheet("")
        p._hover_animations = []
        if hasattr(p, "_panel_animation"):
            p._panel_animation.stop()
        self.holder = QWidget(p)
        self.holder.hide()
        old = p.takeCentralWidget()
        referenced = []
        for value in vars(p).values():
            values = value.values() if isinstance(value, dict) else value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, QWidget) and item is not old:
                    referenced.append(item)
        for widget in referenced:
            ancestor = widget.parentWidget()
            while ancestor is not None and ancestor is not old:
                ancestor = ancestor.parentWidget()
            if ancestor is old:
                widget.setParent(self.holder)
        old.deleteLater()
        self._extra_controls = []

    # ----- header / navigation ---------------------------------------------
    def _header(self):
        p = self.p
        row = QHBoxLayout()
        row.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(QIcon(str(ASSETS/"redlain-icon.png")).pixmap(26, 26))
        row.addWidget(logo)
        brand = QLabel(f"REDLAIN <span style='color:#c84550'>DRAW ENGINE</span> "
                       f"<span style='color:#6f6f76'>{VERSION}</span>")
        brand.setObjectName("brand")
        row.addWidget(brand)
        row.addSpacing(18)
        self.nav_group = QButtonGroup(p)
        self.nav_group.setExclusive(True)
        self.nav_buttons = {}
        for key, text in NAV:
            button = QPushButton(text)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, name=key: self.navigate(name))
            self.nav_group.addButton(button)
            self.nav_buttons[key] = button
            row.addWidget(button)
        row.addStretch()
        p.status.setObjectName("chip")
        p.status.setStyleSheet("")
        row.addWidget(p.status)
        self.compact_button = _button("Компактно", self.toggle_compact, "ghost",
                                      "Компактный режим: Preview, статус и кнопки запуска (Ctrl+M)")
        self.compact_button.setCheckable(True)
        row.addWidget(self.compact_button)
        row.addWidget(_button("Скрыть в иконку", self.hide_to_launcher, "ghost",
                              "Окно сворачивается в плавающую иконку; клик по ней открывает панель"))
        return row

    def _add_page(self, name, widget):
        self.page_names.append(name)
        self.pages.addWidget(widget)

    def navigate(self, name, animate=True):
        name = NAV_ALIASES.get(name, name)
        if name not in self.page_names:
            return
        index = self.page_names.index(name)
        self.nav_buttons[name].setChecked(True)
        if index == self.pages.currentIndex():
            return
        old = self.pages.currentWidget()
        if animate and self.motion.duration(180) and old is not None and self.pages.isVisible():
            # Cross-fade from a snapshot: cheap, and the live page is interactive at once.
            shot = QLabel(self.pages)
            shot.setPixmap(old.grab())
            shot.setGeometry(old.geometry())
            shot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            effect = QGraphicsOpacityEffect(shot)
            shot.setGraphicsEffect(effect)
            shot.show()
            self.pages.setCurrentIndex(index)
            shot.raise_()
            previous = getattr(self, "_page_shot", None)
            if previous is not None:
                self.animator.stop(previous.graphicsEffect(), b"opacity")
                previous.deleteLater()
            self._page_shot = shot
            def done():
                if getattr(self, "_page_shot", None) is shot:
                    self._page_shot = None
                shot.deleteLater()
            self.animator.animate(effect, b"opacity", 0., 180, start=1., finished=done)
        else:
            self.pages.setCurrentIndex(index)
        if name == "projects":
            self.p.refresh_project_library()
        if name == "discover" and not getattr(self.p.discover_page, "_initial_search_started", False):
            self.p.discover_page._initial_search_started = True
            self.p.discover_page.search_topic("Illustration portrait")

    # ----- drawing page -----------------------------------------------------
    def _draw_page(self):
        p = self.p
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        left = Card()
        self.preview_card = left
        self.root_opaque = [left]
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 12, 14, 12)
        lv.setSpacing(8)
        bar = QHBoxLayout()
        self.view_group = QButtonGroup(p)
        self.view_buttons = {}
        for key, text in (("source", "Исходник"), ("preview", "Preview"), ("live", "Процесс")):
            button = QPushButton(text)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, name=key: self.show_view(name))
            self.view_group.addButton(button)
            self.view_buttons[key] = button
            bar.addWidget(button)
        views = QMenu(p)
        for index, text in ((1, "Обработанное изображение"), (3, "Карта приоритета"), (4, "Контуры (вектор)"),
                            (5, "Порядок мазков"), (6, "До / после"), (7, "Симуляция рисования")):
            views.addAction(text, lambda i=index: self.show_view(i))
        views.addSeparator()
        views.addAction("Запустить симуляцию", p.prepare_simulation)
        views.addAction("Сравнить движки", p.compare_engines)
        views.addAction("Экспорт Preview PNG", p.export_preview)
        more = QPushButton("Виды ▾")
        more.setObjectName("ghost")
        more.setMenu(views)
        bar.addWidget(more)
        bar.addStretch()
        for text, action, tip in (("−", lambda: self._current_preview().zoom(1/1.2), "Уменьшить"),
                                  ("+", lambda: self._current_preview().zoom(1.2), "Увеличить"),
                                  ("Вписать", lambda: self._current_preview().fit_image(), "Вписать в окно")):
            bar.addWidget(_button(text, action, "ghost", tip))
        preview_button = p.actions["PREVIEW"]
        preview_button.setText("PREVIEW")
        preview_button.setToolTip("Построить план мазков и честный Preview (Ctrl+Enter)")
        bar.addWidget(preview_button)
        lv.addLayout(bar)
        self.canvas_stack = QStackedWidget()
        p.previews.setParent(None)
        self.canvas_stack.addWidget(p.previews)
        self.canvas_stack.addWidget(p.live_core)
        # 1366×768 at 150% DPI leaves ~480 logical px: RUN must stay on screen.
        p.live_core.setMinimumSize(240, 150)
        for view in (p.previews.widget(i) for i in range(p.previews.count())):
            view.setMinimumSize(160, 120)
        lv.addWidget(self.canvas_stack, 1)
        self.compare_row = QWidget()
        compare = QHBoxLayout(self.compare_row)
        compare.setContentsMargins(0, 0, 0, 0)
        compare.addWidget(QLabel("До / после"))
        compare.addWidget(p.before_after, 1)
        compare.addWidget(p.simulate_button)
        lv.addWidget(self.compare_row)
        self.compare_row.hide()  # Only for the before/after and simulation views.
        p.previews.currentChanged.connect(self._preview_changed)
        info = QHBoxLayout()
        p.stats.setObjectName("muted")
        info.addWidget(p.stats, 1)
        lv.addLayout(info)
        details = Collapsible("Подробности плана и журнал", self.animator)
        p.log.setMaximumHeight(96)
        details.body_layout.addWidget(p.log)
        details.body_layout.addWidget(p.clock_stats)
        details.body_layout.addWidget(p.vector_stats)
        lv.addWidget(details)
        row.addWidget(left, 1)
        self.inspector = self._inspector()
        row.addWidget(self.inspector)
        self.root_opaque.append(self.inspector)
        return page

    def _current_preview(self):
        return self.p.previews.currentWidget()

    def show_view(self, name):
        p = self.p
        if name == "live":
            self.canvas_stack.setCurrentIndex(1)
            self.view_buttons["live"].setChecked(True)
            return
        self.canvas_stack.setCurrentIndex(0)
        index = {"source": 0, "preview": 2}.get(name, name)
        p.previews.setCurrentIndex(index)
        self._preview_changed(index)

    def _preview_changed(self, index):
        self.compare_row.setVisible(index in (6, 7))
        key = {0: "source", 2: "preview"}.get(index)
        if self.canvas_stack.currentIndex() == 1 and key:
            self.canvas_stack.setCurrentIndex(0)
        if key:
            self.view_buttons[key].setChecked(True)
        else:
            checked = self.view_group.checkedButton()
            if checked:
                self.view_group.setExclusive(False)
                checked.setChecked(False)
                self.view_group.setExclusive(True)

    def _section(self, layout, title):
        label = _label(title.upper(), "eyebrow", False)
        layout.addSpacing(6)
        layout.addWidget(label)

    def _inspector(self):
        p = self.p
        scroll = QScrollArea()
        scroll.setObjectName("inspector")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(300)
        scroll.setMaximumWidth(380)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea#inspector { border: 1px solid #262629; border-radius: 14px; }")
        content = QWidget()
        box = QVBoxLayout(content)
        box.setContentsMargins(14, 12, 14, 14)
        box.setSpacing(6)
        self.assistant = AssistantPanel(self.motion)
        self.assistant.setMinimumHeight(250)
        box.addWidget(self.assistant)

        self._section(box, "1 · Изображение")
        grid = QGridLayout()
        importer = p.actions["IMPORT IMAGE"]
        importer.setText("Импорт…")
        importer.setToolTip("Открыть PNG/JPG/WebP (Ctrl+O) или перетащите файл в окно")
        grid.addWidget(importer, 0, 0)
        grid.addWidget(_button("Вставить", p.paste_image, tip="Изображение из буфера обмена (Ctrl+V)"), 0, 1)
        grid.addWidget(_button("Обрезать", p.crop_image, tip="Две противоположные точки на исходнике"), 1, 0)
        capture = p.actions["CAPTURE"]
        capture.setText("Захват игры")
        capture.setToolTip("Снимок области персонажа, выделенной в CALIBRATE")
        grid.addWidget(capture, 1, 1)
        box.addLayout(grid)

        self._section(box, "2 · Размер на холсте")
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow("Формат", p.drawing_format)
        form.addRow("Масштаб", p.drawing_scale)
        size = QHBoxLayout()
        size.addWidget(p.drawing_width)
        size.addWidget(QLabel("×"))
        size.addWidget(p.drawing_height)
        form.addRow("Свой размер", size)
        box.addLayout(form)
        p.drawing_format.setToolTip("«Весь холст» + 100% — рисунок занимает весь откалиброванный холст.")

        self._section(box, "3 · Режим рисунка")
        modes = QHBoxLayout()
        self.mode_group = QButtonGroup(p)
        self.mode_buttons = {}
        for mode in ("FAST", "BALANCED", "MASTERPIECE"):
            button = QPushButton(mode)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, m=mode: p.human_mode.setCurrentText(m))
            self.mode_group.addButton(button)
            self.mode_buttons[mode] = button
            modes.addWidget(button)
        box.addLayout(modes)
        self.mode_text = _label("", "muted")
        box.addWidget(self.mode_text)
        p.human_mode.currentTextChanged.connect(self._sync_mode)
        self._sync_mode(p.human_mode.currentText())
        form = QFormLayout()
        form.addRow("Скорость", p.speed)
        form.addRow("Лимит времени", p.limit)
        box.addLayout(form)

        self._section(box, "4 · Игра")
        form = QFormLayout()
        form.addRow("Профиль", p.profile_combo)
        box.addLayout(form)
        self.profile_state = _label("", "muted")
        box.addWidget(self.profile_state)
        pair = QHBoxLayout()
        calibrate = p.actions["CALIBRATE"]
        calibrate.setText("Калибровка")
        calibrate.setToolTip("Выбрать окно Roblox и отметить холст/палитру/кисти")
        pair.addWidget(calibrate)
        pair.addWidget(p.actions["TEST DRAW"])
        box.addLayout(pair)

        advanced = Collapsible("Расширенные настройки", self.animator)
        f = QFormLayout()
        f.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        f.addRow("Движок", p.engine)
        f.addRow("Стиль обработки", p.style)
        f.addRow("Качество (Legacy/Vector)", p.quality)
        f.addRow("Точность Vector", p.vector_accuracy)
        f.addRow("Заполнение (Legacy/Vector)", p.brushwork)
        f.addRow("Размер кисти", p.brush_policy)
        f.addRow("Непрозрачность", p.brush_opacity)
        f.addRow("Задержка игры", p.game_delay)
        f.addRow(p.crop_fit)
        f.addRow(p.remove_bg)
        f.addRow("Слой Preview", p.layer_select)
        f.addRow(_label("Приоритет деталей", "eyebrow", False))
        f.addRow(p.intelligence_label)
        f.addRow(p.intelligence)
        f.addRow("Композиция", p.priority_mode)
        f.addRow(p.detect_faces)
        f.addRow("Приоритет области", p.region_score)
        f.addRow(p.select_region)
        regions = QHBoxLayout()
        regions.addWidget(_button("Отменить область", p.undo_priority_region))
        regions.addWidget(_button("Сбросить", p.clear_priority_regions))
        f.addRow(regions)
        f.addRow(_button("Обновить карту приоритета", p.analyze_priorities))
        fill = _button("Smart Canvas Fill · поля…", self.open_fill_editor,
                       tip="Чем заполнить добавленные поля, если формат не совпадает с картинкой")
        f.addRow(fill)
        advanced.body_layout.addLayout(f)
        box.addWidget(advanced)
        self._extra_controls.append(fill)
        box.addStretch()
        scroll.setWidget(content)
        return scroll

    def _sync_mode(self, mode):
        if mode in self.mode_buttons:
            self.mode_buttons[mode].setChecked(True)
        self.mode_text.setText(MODE_TEXT.get(mode, ""))

    def open_fill_editor(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        p = self.p
        dialog = QDialog(p)
        dialog.setWindowTitle("Smart Canvas Fill")
        layout = QVBoxLayout(dialog)
        holder = p.fill_editor.parentWidget()
        p.fill_editor.setParent(dialog)
        layout.addWidget(p.fill_editor, 1)
        if p.original is not None:
            size = (p.plan.canvas_size if p.plan else (p.profile.canvas.width, p.profile.canvas.height)
                    if p.profile else (534, 530))
            p.fill_editor.set_source(p.original, size, p.crop_fit.isChecked())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(760, 620)
        dialog.exec()
        p.fill_editor.setParent(holder if holder is not None else self.holder)

    # ----- projects page ----------------------------------------------------
    def _projects_page(self):
        p = self.p
        page = Card()
        box = QVBoxLayout(page)
        box.setContentsMargins(18, 14, 18, 14)
        top = QHBoxLayout()
        title = QVBoxLayout()
        title.addWidget(_label("ТЕКУЩИЙ ПРОЕКТ", "eyebrow", False))
        p.project_name.setStyleSheet("font-size: 15px; font-weight: 600;")
        title.addWidget(p.project_name)
        title.addWidget(p.project_status)
        top.addLayout(title, 1)
        for key, text in (("Save Project", "Сохранить"), ("Save As", "Копия…"), ("Delete Checkpoint", "Удалить прогресс")):
            button = p.project_buttons[key]
            button.setText(text)
            top.addWidget(button)
        box.addLayout(top)
        p.projects_page.setParent(None)
        box.addWidget(p.projects_page, 1)
        p.projects_page.import_requested.connect(lambda: self.navigate("draw"))
        self.root_opaque.append(page)
        return page

    # ----- settings page ----------------------------------------------------
    def _settings_page(self):
        p = self.p
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        grid = QGridLayout(content)
        grid.setSpacing(12)
        scroll.setWidget(content)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        game = Card()
        g = QVBoxLayout(game)
        g.addWidget(_label("ИГРОВОЙ ПРОФИЛЬ И КАЛИБРОВКА", "eyebrow", False))
        g.addWidget(_label("Готовые профили рассчитаны на клиентскую область 1366×768. При другом размере окна, "
                           "масштабе или DPI выполните «Калибровку».", "muted"))
        p.popup_profile.setText("Новый плейс · RGB v4 · числовые поля")
        p.ready_profile.setText("Старый плейс · ползунки (бесплатно)")
        g.addWidget(p.popup_profile)
        g.addWidget(p.ready_profile)
        brush = _button("Проверить размер кисти", p.check_brush_size, tip="Рисует и проверяет несколько размеров кисти")
        adopt = _button("Применить текущую калибровку к проекту", p.adopt_project_calibration,
                        tip="Для Resume после изменения положения окна: физический размер холста должен совпадать")
        speed = _button("Калибровка скорости · 4 линии", p.calibrate_speed,
                        tip="Измеряет, какие скорости игра реально принимает на чистом холсте")
        for button in (brush, adopt, speed):
            g.addWidget(button)
        self._extra_controls.extend([brush, adopt, speed])
        g.addStretch()

        motion = Card()
        m = QVBoxLayout(motion)
        m.addWidget(_label("АНИМАЦИИ И ПРОИЗВОДИТЕЛЬНОСТЬ", "eyebrow", False))
        self.motion_combo = QComboBox()
        for level in MOTION_LEVELS:
            self.motion_combo.addItem(MOTION_LABELS[level], level)
        self.motion_combo.setCurrentIndex(MOTION_LEVELS.index(self.motion.level))
        self.motion_combo.currentIndexChanged.connect(
            lambda i: self.motion.set("level", self.motion_combo.itemData(i)))
        form = QFormLayout()
        form.addRow("Движение", self.motion_combo)
        m.addLayout(form)
        for key, text, tip in (("background", "Анимированный фон", "Мягкий свет и линии позади панелей"),
                               ("assistant", "REDLAIN Assistant", "Персонаж-художник реагирует на реальные события"),
                               ("low_power", "Режим слабого ПК", "Декор не чаще 15 кадров/с и короткие переходы")):
            box = QCheckBox(text)
            box.setToolTip(tip)
            box.setChecked(getattr(self.motion, key))
            box.toggled.connect(lambda value, k=key: self.motion.set(k, value))
            m.addWidget(box)
        p.overlay_enabled.setText("Иконка прогресса во время рисования")
        m.addWidget(p.overlay_enabled)
        self.perf_label = _label("", "muted")
        m.addWidget(self.perf_label)
        m.addWidget(_label("Во время ввода в игру фон и ассистент останавливаются, окно скрывается до начала мазков. "
                           "Ассистент — 2.5D-иллюстрация QPainter, не 3D-модель; GPU не требуется.", "muted"))
        m.addStretch()

        timer = Card()
        t = QVBoxLayout(timer)
        t.addWidget(_label("ТАЙМЕР РАУНДА", "eyebrow", False))
        form = QFormLayout()
        form.addRow("Свой лимит", p.custom_time)
        form.addRow("Запас", p.safety_buffer)
        t.addLayout(form)
        t.addWidget(p.smart_finish)
        row = QHBoxLayout()
        row.addWidget(_button("Синхронизировать", p.sync_round_clock))
        row.addWidget(_button("Сброс", p.reset_round_clock))
        t.addLayout(row)
        t.addWidget(_button("Сохранить пресет таймера", p.save_timer_preset))
        t.addStretch()

        tools = Card()
        k = QVBoxLayout(tools)
        k.addWidget(_label("ИНСТРУМЕНТЫ", "eyebrow", False))
        for text, action, tip in (("Локальный тестовый холст", p.open_test_canvas, "Проверка без Roblox"),
                                  ("Показать разметку профиля", p.show_debug, "Наложение на 7 секунд"),
                                  ("Загрузить старый план…", p.load_plan, "Планы 2.0/3.0 по-прежнему читаются"),
                                  ("Сохранить план…", p.save_plan, None),
                                  ("История рисунков", p.history, None)):
            button = _button(text, action, tip=tip)
            k.addWidget(button)
        k.addStretch()

        extensions = Card()
        e = QVBoxLayout(extensions)
        e.addWidget(_label("РАСШИРЕНИЯ · НЕОБЯЗАТЕЛЬНО", "eyebrow", False))
        self.discover_box = QCheckBox("Discover · поиск в Wikimedia Commons")
        self.discover_box.setToolTip("Нужен доступ к commons.wikimedia.org; ключ не нужен. "
                                     "Интеграция проверена на тестовом транспорте, не в каждой сети.")
        self.discover_box.setChecked(bool(p.settings.get("ext_discover", False)))
        self.discover_box.toggled.connect(lambda value: (p.save_setting("ext_discover", value), self._apply_extensions()))
        e.addWidget(self.discover_box)
        self.ai_box = QCheckBox("Генерация картинки по описанию (ваш Images API-ключ)")
        self.ai_box.setToolTip("Запросы платные и уходят внешнему провайдеру. Для рисования не требуется.")
        self.ai_box.setChecked(bool(p.settings.get("ext_ai", False)))
        self.ai_box.toggled.connect(lambda value: (p.save_setting("ext_ai", value), self._apply_extensions()))
        e.addWidget(self.ai_box)
        self.ai_panel = QWidget()
        a = QVBoxLayout(self.ai_panel)
        a.setContentsMargins(0, 0, 0, 0)
        p.prompt.setMaximumHeight(70)
        a.addWidget(p.prompt)
        row = QHBoxLayout()
        generate = p.actions["GENERATE"]
        generate.clicked.disconnect()
        generate.clicked.connect(self._generate_from_text)
        row.addWidget(generate)
        ai_settings = _button("Ключ и модель…", p.ai_settings)
        row.addWidget(ai_settings)
        a.addLayout(row)
        e.addWidget(self.ai_panel)
        e.addStretch()
        self._extra_controls.append(ai_settings)

        grid.addWidget(game, 0, 0)
        grid.addWidget(motion, 0, 1)
        grid.addWidget(timer, 1, 0)
        grid.addWidget(tools, 1, 1)
        grid.addWidget(extensions, 2, 0, 1, 2)
        grid.setRowStretch(3, 1)
        return scroll

    def _generate_from_text(self):
        self.p.source.setCurrentText("Text")
        self.p.generate()

    def _discover_page(self):
        p = self.p
        page = Card()
        box = QVBoxLayout(page)
        box.setContentsMargins(14, 12, 14, 12)
        box.addWidget(_label("Необязательное расширение: изображения Wikimedia Commons с лицензией и атрибуцией. "
                             "Без сети поиск недоступен; остальные функции от него не зависят.", "muted"))
        p.discover_page.setParent(None)
        box.addWidget(p.discover_page, 1)
        return page

    def _apply_extensions(self):
        enabled = self.discover_box.isChecked()
        self.nav_buttons["discover"].setVisible(enabled)
        if not enabled and self.page_names[self.pages.currentIndex()] == "discover":
            self.navigate("settings", animate=False)
        self.ai_panel.setVisible(self.ai_box.isChecked())

    # ----- action bar ---------------------------------------------------------
    def _action_bar(self):
        p = self.p
        bar = QFrame()
        bar.setObjectName("actionBar")
        bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        p.run_button.setText("▶  RUN")
        p.run_button.setToolTip("Рисовать в выбранном окне. Окно программы скроется до первого мазка.")
        p.run_button.setMinimumWidth(120)
        glow = QGraphicsDropShadowEffect(p.run_button)
        glow.setOffset(0, 0)
        glow.setBlurRadius(0)
        glow.setColor(QColor(200, 69, 80, 150))
        p.run_button.setGraphicsEffect(glow)
        self.run_glow = glow
        p.run_button.installEventFilter(self._hover_filter())
        row.addWidget(p.run_button)
        p.pause_button.clicked.disconnect()
        p.pause_button.clicked.connect(self.primary_pause)
        p.pause_button.setMinimumWidth(150)
        row.addWidget(p.pause_button)
        p.stop_button.setText("■  STOP · F9")
        row.addWidget(p.stop_button)
        status = QVBoxLayout()
        status.setSpacing(0)
        self.reason = _label("", "reason")
        self.save_line = _label("", "muted")
        status.addWidget(self.reason)
        status.addWidget(self.save_line)
        row.addLayout(status, 1)
        self.root_opaque.append(bar)
        return bar

    def _hover_filter(self):
        shell = self

        class Glow(QObject):
            def eventFilter(self, watched, event):
                if event.type() in (QEvent.Type.Enter, QEvent.Type.Leave) and watched.isEnabled():
                    shell.animator.animate(shell.run_glow, b"blurRadius",
                                           22. if event.type() == QEvent.Type.Enter else 0., 160,
                                           start=shell.run_glow.blurRadius())
                return False
        self._glow_filter = Glow(self.p)
        return self._glow_filter

    def primary_pause(self):
        p = self.p
        if p.executor and not p.executor.pause_event.is_set():
            p.pause_and_save()
        elif p.executor:
            p.pause()
        else:
            p.resume_project()

    # ----- state ----------------------------------------------------------------
    def run_blockers(self):
        p = self.p
        if p.busy():
            return ["Идёт операция — дождитесь её или нажмите STOP"]
        reasons = []
        resumable = p._resume_payload is not None and p.plan is p._resume_payload["plan"]
        if p.original is None and not resumable:
            reasons.append("Импортируйте изображение")
        elif p.plan is None:
            reasons.append("Нажмите PREVIEW, чтобы построить план")
        elif not p.plan.strokes:
            reasons.append("План пуст: картинка белая или детали мельче кисти")
        if p.profile is None:
            reasons.append("Выберите профиль игры или выполните «Калибровку»")
        elif not p.profile.verified:
            reasons.append("Профиль не подтверждён: выполните TEST DRAW")
        if not p.hotkeys_ready:
            reasons.append("Не зарегистрирована аварийная остановка F9")
        return reasons

    def refresh(self):
        p = self.p
        if not p.isVisible():
            return  # Hidden/drawing: the launcher icon keeps its 3.0 rules.
        if p.isMinimized():
            p.icon.show()
            return
        if p.icon.isVisible() and not p.icon.popup.isVisible():
            p.icon.hide()  # The open panel already has every control; no always-on-top overlap.
        blockers = self.run_blockers()
        p.run_button.setEnabled(not blockers)
        self.reason.setText(("RUN недоступен: "+blockers[0]) if blockers else "Готово к запуску · окно скроется перед вводом")
        name = "reason" if blockers else "okText"
        if self.reason.objectName() != name:
            self.reason.setObjectName(name)
            self.reason.style().unpolish(self.reason)
            self.reason.style().polish(self.reason)
        executor = p.executor
        if executor and not executor.pause_event.is_set():
            text, enabled = "❚❚  PAUSE & SAVE · F8", True
        elif executor:
            text, enabled = "▶  RESUME · F8", True
        else:
            state = p._project_last_state or {}
            saved = p._resume_payload is not None or state.get("cursor", 0) > 0
            text, enabled = "▶  RESUME проекта", saved and not p.busy()
        p.pause_button.setText(text)
        p.pause_button.setEnabled(enabled)
        p.stop_button.setEnabled(bool(p.executor or p.job or p._pending_run))
        for mode, button in self.mode_buttons.items():
            button.setEnabled(p.human_mode.isEnabled())
        profile = p.profile
        self.profile_state.setText(
            "Профиль не выбран" if profile is None else
            f"{profile.client_size[0]}×{profile.client_size[1]} · DPI {profile.dpi} · "
            + ("подтверждён TEST DRAW" if profile.verified else "нужен TEST DRAW"))
        save = p.project_status.text()
        if save != self._last_save_text:
            self._last_save_text = save
            self.save_line.setText("Проект: "+save)
        self._update_assistant_hint(blockers)

    def _update_assistant_hint(self, blockers):
        p = self.p
        if p.plan is not None and not blockers:
            minutes = p.plan.estimated_seconds/60
            hint = (f"План готов: {len(p.plan.strokes):,} мазков, оценка ≈{minutes:.1f} мин (уточняется по ходу). "
                    "Очистите холст в игре и нажмите RUN.")
        elif blockers:
            hint = blockers[0]+"."
        else:
            hint = "Готов."
        self.assistant.set_hint(hint)

    def on_state(self, state):
        p = self.p
        message = ""
        if state == "ERROR":
            message = p.log.toPlainText().strip().split("\n")[0][:220]
        elif state == "PAUSED":
            reason = p.executor.pause_reason if p.executor else ""
            message = (("Автопауза: "+reason) if reason else "Пауза. Мышь отпущена.")+" F8 — продолжить, F9 — стоп."
        elif state in DRAWING_STATES:
            message = "Рисую в игре. F8 — пауза с сохранением, F9 — остановка."
        elif state == "PROCESSING":
            message = "Строю план мазков. Это расчёт на CPU, без процентов «для вида»."
        elif state in ("FINISHED", "FINISHED PARTIAL", "TIME LIMIT"):
            message = "Готово." if state == "FINISHED" else "Остановлено с частичным результатом."
        self.assistant.set_state(state, message)
        self.motion.set_external_input(state in DRAWING_STATES)
        if state in ("DRAWING", "PAUSED", "FINISHED", "FINISHED PARTIAL") and p.live_core.plan is not None:
            self.show_view("live")
        self.refresh()

    def engine_event(self, event):
        p = self.p
        color = stage = None
        plan = p.live_core.plan
        index = event.get("index")
        if plan is not None and isinstance(index, int) and 0 <= index < len(plan.strokes) and event["type"] == "stroke_start":
            from app.human import STAGES
            stroke = plan.strokes[index]
            color, stage = stroke.color, f"{stroke.stage+1:02d} {STAGES[stroke.stage]}"
        self.assistant.engine_event(event, color, stage or "")
        if event["type"] == "stroke_complete" and getattr(p.live_core, "map_pixmap", None) is not None:
            self._easel_dirty = True

    def sync_easel(self):
        """Easel shows real content: revealed strokes, the plan preview or the source."""
        p = self.p
        core = p.live_core
        if core.plan is not None and core.done and getattr(core, "map_pixmap", None) is not None:
            self.assistant.set_easel(core.map_pixmap)
        elif p.plan is not None and getattr(p.plan, "_project_preview", None) is not None:
            self.assistant.set_easel(self._thumb(p.plan._project_preview))
        elif p.original is not None:
            self.assistant.set_easel(self._thumb(p.original))
        else:
            self.assistant.set_easel(None)

    def reveal_preview(self):
        """A freshly built plan fades in over the card instead of popping."""
        if not self.motion.duration(220) or not self.canvas_stack.isVisible():
            return
        previous = getattr(self, "_preview_veil", None)
        if previous is not None:
            self.animator.stop(previous.graphicsEffect(), b"opacity")
            previous.deleteLater()
        veil = QLabel(self.canvas_stack)
        veil.setStyleSheet("background: #161618; border-radius: 10px;")
        veil.setGeometry(self.canvas_stack.rect())
        veil.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        effect = QGraphicsOpacityEffect(veil)
        veil.setGraphicsEffect(effect)
        veil.show()
        veil.raise_()
        self._preview_veil = veil

        def done():
            if self._preview_veil is veil:
                self._preview_veil = None
            veil.deleteLater()
        self.animator.animate(effect, b"opacity", 0., 260, start=1., finished=done)

    def _thumb(self, image):
        key = id(image)
        if getattr(self, "_thumb_key", None) != key:
            small = image.copy()
            small.thumbnail((160, 160))
            self._thumb_cache, self._thumb_key = pixmap(small), key
        return self._thumb_cache

    def image_changed(self):
        self.sync_easel()
        self.assistant.react_preparing("Смотрю изображение. Выберите размер и режим, затем PREVIEW.")

    def save_status(self, status, message=""):
        self.assistant.save_status(status, message)
        if status == "failed":
            self.toast.show_message("Сохранение не подтверждено: "+message, 6000)
        elif status == "saved" and message:
            self.toast.show_message(message)

    def notify(self, text):
        self.toast.show_message(text)

    def _refresh_perf(self):
        if getattr(self, "_easel_dirty", False):
            self._easel_dirty = False
            self.sync_easel()
        if self.page_names[self.pages.currentIndex()] != "settings" or not self.p.isVisible():
            return
        bg = (f"фон {1000//self.root._timer.interval()} к/с, {self.root.paint_cost_ms():.2f} мс/кадр"
              if self.root.running() else "фон остановлен")
        view = self.assistant.view
        ast = (f"ассистент {1000//view._timer.interval()} к/с, {view.paint_cost_ms():.2f} мс/кадр"
               if view.running() else "ассистент: кадры не идут (скрыт или выключен)")
        if view.degraded:
            ast += " (упрощён: долгая отрисовка)"
        self.perf_label.setText("Измерено сейчас: "+bg+" · "+ast)

    # ----- window modes -----------------------------------------------------------
    def _opaque_cards(self):
        cards = getattr(self, "_cards", None)
        if cards is None:
            cards = self._cards = [w for w in self.root.findChildren(QFrame) if w.objectName() in ("card", "actionBar")]
            cards.append(self.inspector)
        return cards

    def resized(self):
        if getattr(self, "toast", None) and self.toast.isVisible():
            self.toast.move(self.root.width()-self.toast.width()-22, 70)
        intro = getattr(self, "_intro", None)
        if intro is not None:
            intro.setGeometry(self.root.rect())
        compact_layout = self.p.width() < 900
        self.inspector.setMaximumWidth(330 if compact_layout else 380)

    def toggle_compact(self):
        p = self.p
        self._compact = not self._compact
        self.compact_button.setChecked(self._compact)
        if p.isMaximized() or p.isFullScreen():
            p.showNormal()
        if self._compact:
            self._full_geometry = p.geometry()
            self.navigate("draw")
            self.inspector.hide()
            area = p.screen().availableGeometry()
            width, height = min(560, area.width()-40), min(640, area.height()-60)
            right = min(p.geometry().right(), area.right()-10)
            target = QRect(right-width, max(area.top()+30, p.geometry().top()), width, height)
        else:
            self.inspector.show()
            target = self._full_geometry or p.geometry()
        for key, button in self.nav_buttons.items():
            button.setVisible(not self._compact and (key != "discover" or self.discover_box.isChecked()))
        self.animator.animate(p, b"geometry", target, 220, start=p.geometry())

    def hide_to_launcher(self):
        p = self.p
        if p.executor:
            p.executor.pause()
        self.window_motion.conceal(lambda: p.icon.show())

    def reveal(self):
        self.window_motion.reveal()
        self.sync_decorations()

    def sync_decorations(self):
        self.root.sync()
        self.assistant.view.sync()
        if self.p.isMinimized():
            self.p.icon.show()

    def play_intro(self):
        if self.motion.duration(650) and self.motion.level == "full":
            self._intro = Intro(self.animator, self.root)
            self._intro.destroyed.connect(lambda: setattr(self, "_intro", None))
            self._intro.play()

    def close_resources(self):
        for timer in (self.refresh_timer, self.perf_timer, self.root._timer, self.toast.timer):
            timer.stop()
        self.assistant.close_resources()


def install_shell(p):
    p.shell = Shell(p)
    return p.shell
