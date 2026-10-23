from pathlib import Path
import random

from PySide6.QtCore import QSize, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QFrame, QToolButton, QSplitter)

from app.discover import CommonsClient, TOPICS, difficulty
from app.ui.common import Job, Preview, pixmap


class DiscoverPage(QWidget):
    imported = Signal(str)

    def __init__(self, root, analysis_options=lambda: {}, parent=None):
        super().__init__(parent)
        self.client = CommonsClient(root)
        self.analysis_options = analysis_options
        self.job = None
        self.selected = self.selected_path = None
        layout = QVBoxLayout(self)
        title = QLabel("DISCOVER  /  IMAGES WORTH DRAWING")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        search = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Anime character, portrait, fantasy…")
        self.query.returnPressed.connect(self.search)
        search.addWidget(self.query, 1)
        for text, action in (("Search", self.search), ("Surprise Me", self.surprise),
                             ("Favorites", self.show_favorites), ("Cancel", self.cancel)):
            button = QPushButton(text)
            button.clicked.connect(action)
            search.addWidget(button)
        layout.addLayout(search)
        topics = QHBoxLayout()
        for topic in ("Anime", "Portrait", "Pixel art", "Fantasy", "Dark aesthetic"):
            button = QPushButton(topic)
            button.clicked.connect(lambda _, value=topic: self.search_topic(value))
            topics.addWidget(button)
        layout.addLayout(topics)
        self.message = QLabel("Реальный поиск Wikimedia Commons. Доступность изображений зависит от запроса.")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        splitter = QSplitter()
        self.cards = QWidget()
        self.grid = QGridLayout(self.cards)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.cards)
        splitter.addWidget(scroll)
        details = QWidget()
        side = QVBoxLayout(details)
        self.preview = Preview()
        side.addWidget(self.preview, 1)
        self.attribution = QLabel("Выберите изображение для просмотра автора, лицензии и оценки сложности.")
        self.attribution.setWordWrap(True)
        self.attribution.setTextFormat(Qt.TextFormat.PlainText)
        side.addWidget(self.attribution)
        self.analysis = QLabel("")
        self.analysis.setWordWrap(True)
        side.addWidget(self.analysis)
        self.import_button = QPushButton("Import to Workspace")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.import_selected)
        side.addWidget(self.import_button)
        for text, action in (("Preview", self.preview_selected), ("Save to Favorites", self.favorite),
                             ("Open Original", self.open_original)):
            button = QPushButton(text)
            button.clicked.connect(action)
            side.addWidget(button)
        splitter.addWidget(details)
        splitter.setSizes([550, 330])
        layout.addWidget(splitter, 1)

    def _start(self, function, ready):
        if self.job:
            self.message.setText("Дождитесь запроса или нажмите Cancel.")
            return
        job = Job(function, self)
        self.job = job
        job.result.connect(ready)
        job.failed.connect(self.message.setText)
        job.progress.connect(lambda _, text: self.message.setText(text))
        def finished():
            self.job = None
            job.deleteLater()
        job.finished.connect(finished)
        job.start()

    def cancel(self):
        if self.job:
            self.job.cancel.set()
            self.message.setText("Отмена запроса…")

    def search_topic(self, topic):
        self.query.setText(topic)
        self.search()

    def surprise(self):
        self.search_topic(random.choice(TOPICS))

    def search(self):
        query = self.query.text()
        def request(job):
            rows, cached = self.client.search(query, cancel=job.cancel)
            return self._thumbnails(rows, job), cached
        self.message.setText("Поиск в Wikimedia Commons…")
        self._start(request, lambda result: self._show_rows(result[0], "Кеш поиска" if result[1] else "Wikimedia Commons"))

    def _thumbnails(self, rows, job):
        result = []
        for index, item in enumerate(rows):
            if job.cancel.is_set(): raise InterruptedError()
            try:
                image, _ = self.client.download(item, thumbnail=True, cancel=job.cancel)
                image.thumbnail((220, 160))
            except (RuntimeError, ValueError, OSError):
                image = None  # Keep real metadata, show a truthful missing-thumbnail label.
            result.append((item, image))
            job.progress.emit((index+1)/max(1, len(rows)), f"Миниатюры {index+1}/{len(rows)}")
        return result

    def _show_rows(self, rows, source):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for index, (item, image) in enumerate(rows):
            card = QFrame()
            card.setObjectName("discoveryCard")
            layout = QVBoxLayout(card)
            picture = QToolButton()
            picture.setToolTip(item.title)
            if image:
                picture.setIcon(QIcon(pixmap(image)))
                picture.setIconSize(QSize(220, 160))
            else:
                picture.setText("Миниатюра недоступна")
            picture.clicked.connect(lambda _, row=item: self.select(row))
            layout.addWidget(picture)
            label = QLabel(item.title[:100]+"\n"+item.license)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)
            self.grid.addWidget(card, index//2, index%2)
        self.message.setText(f"{source} · {len(rows)} изображений" if rows else "Изображения не найдены. Попробуйте другой запрос.")

    def show_favorites(self):
        self._start(lambda job: self._thumbnails(self.client.favorites(), job),
                    lambda rows: self._show_rows(rows, "Избранное · доступно из кеша"))

    def select(self, item):
        if self.job:
            self.message.setText("Дождитесь текущего запроса или нажмите Cancel.")
            return
        options = dict(self.analysis_options())
        self.selected, self.selected_path = item, None
        self.import_button.setEnabled(False)
        self.attribution.setText(f"{item.title}\n{item.source}\nАвтор: {item.author}\nЛицензия: {item.license}\n{item.page}")
        self.message.setText("Загрузка и реальное планирование сложности…")
        def request(job):
            image, path = self.client.download(item, cancel=job.cancel)
            return image, path, difficulty(image, cancel=job.cancel, **options)
        def ready(result):
            image, path, analysis = result
            self.selected_path = path
            self.preview.set_image(image)
            self.import_button.setEnabled(True)
            self.analysis.setText(f"{analysis['colors']} цветов · {analysis['shape_complexity']} сложность\n"
                                  f"≈{analysis['strokes']} мазков · ≈{analysis['estimated_seconds']/60:.1f} мин\n"
                                  f"Рекомендация: {analysis['recommended_mode']}\n{analysis['note']}")
            self.message.setText("Изображение загружено; оценка относится к плану, не к измерению Roblox.")
        self._start(request, ready)

    def preview_selected(self):
        if self.selected and self.selected_path is None:
            self.select(self.selected)
        else:
            self.preview.fit_image()

    def import_selected(self):
        if self.selected_path:
            self.imported.emit(str(self.selected_path))

    def favorite(self):
        if self.selected:
            item = self.selected
            self._start(lambda job: (self.client.download(item, cancel=job.cancel), self.client.favorite(item)),
                        lambda _: self.message.setText("Сохранено в избранное вместе с изображением для работы без сети."))

    def open_original(self):
        if self.selected:
            QDesktopServices.openUrl(QUrl(self.selected.page))
