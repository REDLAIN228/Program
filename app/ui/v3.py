"""Premium desktop shell reusing the existing controls, jobs and input workflows."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QStackedWidget,
                               QPushButton, QListWidgetItem, QScrollArea, QFormLayout)

from app.ui.discover import DiscoverPage
from app.ui.fill_editor import FillEditor
from app.ui.live_core import LiveArtCore
from app.ui.projects_page import ProjectsPage
from app.ui.instruments import icon


def upgrade_studio(p):
    had_limit = "draw_limit" in p.settings
    p.setWindowTitle("REDLAIN DRAW ENGINE 3.0")
    p.setWindowOpacity(1.)
    brand = p.centralWidget().findChild(QLabel, "brand")
    brand.setText("REDLAIN <span style='color:#c84550'>DRAW ENGINE</span> <span style='color:#77777d'>3.0</span>")
    p.workspace_tagline.setText("PAINT WITH INTENT")
    from pathlib import Path
    asset = Path(__file__).resolve().parents[2]/"assets/redlain-icon.png"
    if asset.exists(): p.setWindowIcon(QIcon(str(asset)))
    logo = QLabel()
    logo.setPixmap(QIcon(str(asset)).pixmap(30, 30))
    p.centralWidget().layout().itemAt(0).layout().insertWidget(0, logo)
    p.progress.hide()  # Kept as a data/progress target for old workflows; no fake loading strip.
    p.timer_ring.hide()
    p.timer_ring.setMaximumSize(0, 0)
    p.human_mode = QComboBox()
    p.human_mode.addItems(["FAST", "BALANCED", "MASTERPIECE"])
    p.human_mode.setCurrentText(p.settings.get("v3_human_mode", "BALANCED"))
    p.engine.addItem("Human 3.0")
    if "studio_engine" not in p.settings:
        p.engine.setCurrentText("Human 3.0")
    for name in ("Agile · 8", "Rapid · 9", "Sprint · 10"):
        p.speed.addItem(name)
    p.speed.setToolTip("10 скоростей. Agile / Rapid / Sprint: сначала SPEED CALIBRATION в Settings. "
                       "Задержки подтверждения игровых контролов сохраняются.")
    for label in p.engine.parentWidget().findChildren(QLabel):
        if label.text() == "VECTOR ENGINE": label.setText("PAINT ENGINE")
    if not had_limit:
        p.limit.setCurrentText("Unlimited")
    forms = p.engine.parentWidget().findChildren(QFormLayout)
    if forms:
        forms[0].insertRow(1, "Human mode", p.human_mode)
    p.human_mode.currentTextChanged.connect(p.invalidate_plan)
    p.human_mode.currentTextChanged.connect(lambda value: p.save_setting("v3_human_mode", value))
    p.fill_editor = FillEditor()
    p.fill_editor.set_settings(p._fill_settings)
    p.fill_editor.settings_changed.connect(p.fill_settings_changed)
    fill_scroll = QScrollArea()
    fill_scroll.setWidgetResizable(True)
    fill_scroll.setWidget(p.fill_editor)
    p.control_pages.addWidget(fill_scroll)
    p._advanced_controls.extend([p.human_mode, p.fill_editor])

    workspace = p.workspace_splitter.widget(1)
    surfaces = QStackedWidget()
    p.workspace_splitter.replaceWidget(1, surfaces)
    p.surfaces = surfaces
    p.dashboard_page = ProjectsPage(dashboard=True)
    p.projects_page = ProjectsPage()
    p.discover_page = DiscoverPage(p.store.root, p.discover_analysis_options)
    p.discover_page.imported.connect(p.import_discovery_image)
    p.discover_page.imported.connect(lambda _: p.navigate_v3("Workspace"))
    p.live_core = LiveArtCore()
    live = QWidget()
    box = QVBoxLayout(live)
    box.addWidget(p.live_core, 1)
    p.live_description = QLabel("Реальные события ввода и подтверждённые мазки. F8 — пауза; F9 — остановка.")
    p.live_description.setWordWrap(True)
    p.live_description.setObjectName("muted")
    box.addWidget(p.live_description)
    for page in (p.dashboard_page, workspace, live, p.discover_page, p.projects_page):
        surfaces.addWidget(page)
    for page in (p.dashboard_page, p.projects_page):
        page.import_requested.connect(p.import_image)
        page.import_requested.connect(lambda: p.navigate_v3("Workspace"))
        page.refresh_requested.connect(p.refresh_project_library)
        page.load_requested.connect(p.load_project)
        page.resume_requested.connect(lambda project_id: p.load_project(project_id, resume=True))

    tools = QHBoxLayout()
    tools.addWidget(QLabel("Inspector"))
    p.inspector_mode = QComboBox()
    for text in ("Image / AI", "Human Engine", "Detail Priority", "Drawing Settings", "Smart Canvas Fill"):
        p.inspector_mode.addItem(text)
    def choose(index):
        target = (0, 1, 2, 3, 5)[index]
        p.control_pages.setCurrentIndex(target)
        p.control_pages.show()
        if target == 2: p.previews.setCurrentIndex(3)
        if target == 5 and p.original is not None:
            size = p.plan.canvas_size if p.plan else (p.profile.canvas.width, p.profile.canvas.height) if p.profile else (534, 530)
            p.fill_editor.set_source(p.original, size, p.crop_fit.isChecked())
    p.inspector_mode.currentIndexChanged.connect(choose)
    tools.addWidget(p.inspector_mode, 1)
    workspace.layout().insertLayout(0, tools)
    layer_row = QHBoxLayout()
    p.layer_select = QComboBox()
    p.layer_select.addItem("All virtual layers", -1)
    p.layer_select.currentIndexChanged.connect(p.show_layer)
    layer_row.addWidget(QLabel("Layers"))
    layer_row.addWidget(p.layer_select, 1)
    p.project_name = QLabel("Untitled artwork")
    p.project_name.setTextFormat(Qt.TextFormat.PlainText)
    layer_row.addWidget(p.project_name)
    workspace.layout().insertLayout(1, layer_row)
    p.project_status = QLabel("Project not saved")
    p.project_status.setObjectName("muted")
    p.project_status.setWordWrap(True)
    # A compact project toolbar remains reachable on every surface.
    project_bar = QHBoxLayout()
    p.project_buttons = {}
    for text, action in (("Save Project", p.save_project), ("Pause & Save", p.pause_and_save),
                         ("Resume", p.resume_project), ("Save As", p.save_project_as),
                         ("Delete Checkpoint", p.delete_project_checkpoint)):
        button = QPushButton(text)
        button.clicked.connect(action)
        project_bar.addWidget(button)
        p.project_buttons[text] = button
    project_bar.addWidget(p.project_status, 1)
    p.centralWidget().layout().insertLayout(1, project_bar)
    settings_page = p.control_pages.widget(4).widget()
    settings_form = settings_page.findChildren(QFormLayout)[0]
    adopt = QPushButton("Use Current Calibration")
    adopt.clicked.connect(p.adopt_project_calibration)
    settings_form.addRow(adopt)
    calibrate_speed = QPushButton("SPEED CALIBRATION · real canvas")
    calibrate_speed.clicked.connect(p.calibrate_speed)
    settings_form.addRow(calibrate_speed)
    legacy_history = QPushButton("Legacy drawing history")
    legacy_history.clicked.connect(p.history)
    settings_form.addRow(legacy_history)
    p._advanced_controls.extend([adopt, calibrate_speed])

    p.navigation.currentRowChanged.disconnect()
    p.navigation.clear()
    entries = [("Dashboard", "dashboard"), ("Workspace", "image"), ("Live Drawing", "vector"),
               ("Discover", "ai"), ("Projects", "history"), ("Settings", "settings")]
    for label, glyph in entries:
        item = QListWidgetItem(icon(glyph), label)
        item.setData(Qt.ItemDataRole.UserRole, label)
        item.setToolTip(label)
        p.navigation.addItem(item)
    def navigate(index):
        if index < 0: return
        p.surfaces.setCurrentIndex(index if index < 5 else 1)
        p.control_pages.setVisible(index in (1, 2, 5))
        if index == 1: p.control_pages.setCurrentIndex(0)
        if index == 2: p.control_pages.setCurrentIndex(3)
        if index == 5: p.control_pages.setCurrentIndex(4)
        if index in (0, 4): p.refresh_project_library()
        if index == 3 and not getattr(p.discover_page, "_initial_search_started", False):
            p.discover_page._initial_search_started = True
            p.discover_page.search_topic("Illustration portrait")
    p.navigation.currentRowChanged.connect(navigate)
    p.navigation.setCurrentRow(0)
    p._v3_loaded = True
    p.engine.currentTextChanged.connect(lambda _: p.v3_engine_controls())
    p.v3_engine_controls()
    p.refresh_project_library()
