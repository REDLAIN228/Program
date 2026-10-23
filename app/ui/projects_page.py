from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QFrame

from app.ui.common import pixmap


class ProjectsPage(QWidget):
    load_requested = Signal(str)
    resume_requested = Signal(str)
    import_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, dashboard=False, parent=None):
        super().__init__(parent)
        self.dashboard = dashboard
        self.rows = []
        box = QVBoxLayout(self)
        title = QLabel("YOUR NEXT MASTERPIECE" if dashboard else "PROJECT LIBRARY")
        title.setObjectName("heroTitle")
        box.addWidget(title)
        subtitle = QLabel("Планируйте как художник. Продолжайте с сохранённого мазка." if dashboard else
                          "Исходники, слои и контрольные точки хранятся на вашем компьютере.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("muted")
        box.addWidget(subtitle)
        row = QHBoxLayout()
        for text, signal in (("Import Image", self.import_requested), ("Refresh Projects", self.refresh_requested)):
            button = QPushButton(text)
            button.clicked.connect(signal.emit)
            row.addWidget(button)
        row.addStretch()
        box.addLayout(row)
        self.continue_title = QLabel("CONTINUE YOUR MASTERPIECE")
        self.continue_title.setObjectName("sectionTitle")
        box.addWidget(self.continue_title)
        self.continue_button = QPushButton("Нет незавершённых проектов")
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self.continue_latest)
        box.addWidget(self.continue_button)
        self.list = QListWidget()
        self.list.setSpacing(8)
        self.list.setObjectName("projectList")
        self.list.itemDoubleClicked.connect(self.load_selected)
        box.addWidget(self.list, 1)
        controls = QHBoxLayout()
        for text, action in (("Open in Workspace", self.load_selected), ("Resume", self.resume_selected)):
            button = QPushButton(text)
            button.clicked.connect(action)
            controls.addWidget(button)
        box.addLayout(controls)
        self.empty = QLabel("Здесь пока нет проектов. Импортируйте изображение, создайте PREVIEW и нажмите Save Project.")
        self.empty.setWordWrap(True)
        box.addWidget(self.empty)

    def set_rows(self, rows, thumbnails):
        self.rows = rows
        self.list.clear()
        shown = rows[:4] if self.dashboard else rows
        for project in shown:
            state = project["checkpoint"]
            done, total = len(state["executed"]), project["total"]
            used_stages = sum(n > 0 for n in project.get("stage_counts", [1]*7))
            card = QFrame()
            card.setObjectName("projectCard")
            line = QHBoxLayout(card)
            image = QLabel()
            image.setFixedSize(90, 86)
            if project["id"] in thumbnails:
                image.setPixmap(pixmap(thumbnails[project["id"]]).scaled(90, 86, Qt.AspectRatioMode.KeepAspectRatio,
                                                                      Qt.TransformationMode.SmoothTransformation))
            line.addWidget(image)
            try:
                updated = datetime.fromisoformat(project["updated"]).astimezone().strftime("%d.%m.%Y %H:%M")
            except ValueError:
                updated = project["updated"]
            info = QLabel(f"{project['title']}\n{project['engine']}  ·  {done:,}/{total:,} мазков\n"
                          f"Этапов завершено: {len(state.get('completed_stages', []))}/{used_stages} используемых  ·  {updated}")
            info.setTextFormat(Qt.TextFormat.PlainText)
            info.setWordWrap(True)
            line.addWidget(info, 1)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, project["id"])
            item.setSizeHint(card.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, card)
        latest = next((row for row in rows if 0 < row["checkpoint"]["cursor"] < row["total"]), None)
        self.latest_id = latest["id"] if latest else None
        self.continue_button.setEnabled(latest is not None)
        self.continue_button.setText(f"Resume · {latest['title']} · {len(latest['checkpoint']['executed'])}/{latest['total']} мазков"
                                     if latest else "Нет незавершённых проектов")
        self.empty.setVisible(not rows)

    def continue_latest(self):
        if getattr(self, "latest_id", None):
            self.resume_requested.emit(self.latest_id)

    def load_selected(self, *_):
        item = self.list.currentItem()
        if item: self.load_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def resume_selected(self, *_):
        item = self.list.currentItem()
        if item: self.resume_requested.emit(item.data(Qt.ItemDataRole.UserRole))
