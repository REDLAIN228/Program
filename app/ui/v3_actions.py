"""Project lifecycle and 3.0 UI integration around the existing input runner."""
from dataclasses import asdict, replace
from pathlib import Path
import time
import weakref
import queue

from PIL import Image
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QDialogButtonBox,
                               QInputDialog, QMessageBox)

from app.automation import DrawingExecutor, SafetyError
from app.layout import drawing_rect
from app.models import Plan, Rect
from app.planner import render_placement
from app.projects import ProjectStore, ProjectWriter, compare_canvas, image_digest
from app.ui.common import Job, Preview


class V3Actions:
    def v3_engine_controls(self):
        human = self.engine.currentText() == "Human 3.0"
        free = not self.busy()
        self.quality.setEnabled(free and not human)
        self.vector_accuracy.setEnabled(free and not human)
        self.brushwork.setEnabled(free and not human)
        self.human_mode.setEnabled(free and human)
        self.quality.setToolTip("Legacy / Vector 2.0 используют это качество. Human 3.0 управляется режимами FAST / BALANCED / MASTERPIECE.")
    def navigate_v3(self, name):
        for index in range(self.navigation.count()):
            if self.navigation.item(index).data(Qt.ItemDataRole.UserRole) == name:
                self.navigation.setCurrentRow(index)
                return

    def init_v3(self):
        from app.event_log import EventJournal
        self.journal = EventJournal(self.store.root)
        self.project_store = ProjectStore(self.store.root)
        self._project_id = self._project_plan = self._resume_payload = None
        self._project_last_state = None
        self._project_writer = None
        self._project_library_job = None
        self._project_title = "Untitled artwork"
        self._v3_loaded = False
        self._last_save_error = ""
        self._source_provenance = {}
        self._fill_settings = self.settings.get("v3_canvas_fill", {})
        self._writer_messages = queue.SimpleQueue()
        self._writer_timer = QTimer(self)
        self._writer_timer.setInterval(80)
        self._writer_timer.timeout.connect(self.poll_project_writer)

    def poll_project_writer(self):
        for _ in range(32):
            try:
                kind, operation, payload = self._writer_messages.get_nowait()
            except queue.Empty:
                return
            if kind == "saved": self.project_saved(operation, payload)
            else: self.project_failed(payload)

    def writer(self):
        if self._project_writer is None:
            target = weakref.ref(self)
            def completed(operation, data):
                panel = target()
                if panel is not None:
                    panel._writer_messages.put(("saved", operation, data))
            def failed(message):
                panel = target()
                if panel is not None:
                    panel._last_save_error = message
                    panel._writer_messages.put(("failed", "", message))
            self._project_writer = ProjectWriter(self.project_store, completed, failed)
            writer = self._project_writer
            self.destroyed.connect(lambda: writer.close())
            self._writer_timer.start()
        return self._project_writer

    def project_options(self):
        return dict(mode=self.human_mode.currentText(), engine=self.engine.currentText(),
                    quality=self.quality.currentText(), speed=self.speed.currentText(),
                    canvas_fill=dict(self._fill_settings), format=self.drawing_format.currentText(),
                    scale=self.drawing_scale.currentText(), crop=self.crop_fit.isChecked(),
                    brush_policy=self.brush_policy.currentText(), opacity=self.brush_opacity.value(),
                    custom_width=self.drawing_width.value(), custom_height=self.drawing_height.value(),
                    style=self.style.currentText(), remove_background=self.remove_bg.isChecked(),
                    detail_intelligence=self.intelligence.value(), priority_mode=self.priority_mode.currentText(),
                    detect_faces=self.detect_faces.isChecked(), priority_regions=list(self.priority_regions),
                    vector_accuracy=self.vector_accuracy.currentText(), safety_buffer=self.safety_buffer.value(),
                    smart_finish=self.smart_finish.isChecked(), limit=self.limit.currentText(), custom_time=self.custom_time.value(),
                    source_provenance=self._source_provenance,
                    game_delay=self.game_delay.value())

    def ensure_project(self, plan=None):
        plan = plan or self.plan
        if plan is None or self.profile is None:
            raise ValueError("Для проекта нужны исходник, профиль и PREVIEW")
        if self._project_id and self._project_plan is plan:
            return self._project_id
        source = self.original
        if source is None or image_digest(source) != plan.source_hash:
            path = self.store.root/"images"/(plan.source_hash+".png")
            if not path.exists():
                raise ValueError("Для сохранения импортируйте исходное изображение этого плана")
            with Image.open(path) as image:
                source = image.convert("RGB").copy()
        project_id = self.project_store.new_id()
        self._project_id, self._project_plan = project_id, plan
        self._project_last_state = dict(cursor=0, executed=[], skipped=[], status="ready", metrics={}, controls={})
        preview = getattr(plan, "_project_preview", None)
        if preview is None:
            # PREVIEW normally supplies this; cache-only imports retain the existing renderer.
            preview = render_placement(plan)
        processed = self.processed if self.processed is not None else preview
        self.writer().submit("create", project_id, self._project_title, source.copy(), processed.copy(), preview.copy(),
                             plan, self.profile, self.project_options())
        self.project_status.setText("Saving project…")
        return project_id

    def save_project(self):
        try:
            project_id = self.ensure_project(self._active_plan if self.executor else None)
            if self.executor:
                self.executor.request_checkpoint()
                self.project_status.setText("Сохранение после освобождения мыши…")
            else:
                state = self._project_last_state or dict(cursor=0, executed=[], skipped=[], status="ready", metrics={}, controls={})
                self.writer().submit("save_checkpoint", project_id, state)
        except Exception as exc:
            self.project_failed(str(exc))

    def pause_and_save(self):
        if self.executor:
            self.executor.pause(True)
            self.executor.request_checkpoint()
        self.save_project()

    def project_checkpoint_sink(self, project_id):
        writer = self.writer()
        target = weakref.ref(self)
        def save(state, canvas):
            panel = target()
            if panel is not None and panel._project_id == project_id:
                panel._project_last_state = state
                if panel._resume_payload is not None:
                    panel._resume_payload["state"] = state
                    if canvas is not None:
                        panel._resume_payload["canvas"] = canvas
                        panel._resume_payload["manifest"]["canvas_cursor"] = state["cursor"]
            writer.submit("save_checkpoint", project_id, state, canvas)
        return save

    def project_saved(self, operation, data):
        if operation == "cache_plan":
            return  # A cache write is not a saved project/checkpoint notification.
        self.journal.write("project_saved", operation=operation, project=data.get("id") if isinstance(data, dict) else self._project_id,
                           cursor=data.get("checkpoint", {}).get("cursor") if isinstance(data, dict) else None)
        self._last_save_error = ""
        self._quit_without_save = False
        if isinstance(data, dict) and data.get("id") == self._project_id:
            if data.get("checkpoint") is not None:
                saved_cursor = data["checkpoint"]["cursor"]
                self.project_status.setText(f"Saved · {saved_cursor:,}/{data['total']:,} мазков")
            self._project_title = data.get("title", self._project_title)
            self.project_name.setText(self._project_title)
            if self._resume_payload is not None:
                self._resume_payload["manifest"] = data
        elif operation == "save_as" and isinstance(data, dict):
            self.project_status.setText("Saved copy · "+data["title"])
        self.refresh_project_library()

    def project_failed(self, message):
        self.journal.write("save_failed", message=message)
        self._last_save_error = message
        if self.executor:
            self.executor.pause(True)
        self.project_status.setText("SAVE ERROR · "+message)
        self.log.setText("Сохранение не подтверждено: "+message+"\nНе закрывайте программу, пока ошибка не исправлена.")

    def refresh_project_library(self):
        if not hasattr(self, "projects_page") or self._project_library_job:
            return
        def process(job):
            rows = self.project_store.recent()
            thumbnails = {}
            for row in rows[:100]:
                if job.cancel.is_set(): raise InterruptedError()
                try:
                    image = self.project_store.get_image(row["assets"]["preview"])
                    image.thumbnail((120, 120))
                    thumbnails[row["id"]] = image
                except (ValueError, OSError):
                    pass
            return rows, thumbnails
        job = Job(process, self)
        self._project_library_job = job
        def ready(result):
            self.projects_page.set_rows(*result)
            self.dashboard_page.set_rows(*result)
        job.result.connect(ready)
        job.failed.connect(lambda message: self.project_status.setText(message))
        def finished():
            self._project_library_job = None
            job.deleteLater()
        job.finished.connect(finished)
        job.start()

    def save_project_as(self):
        if self.busy() and not (self.executor and self.executor.pause_event.is_set()):
            self.log.setText("Для Save As сначала нажмите Pause & Save.")
            return
        if not self._project_id:
            title, ok = QInputDialog.getText(self, "Save Project", "Название проекта:", text=self._project_title)
            if ok and title.strip():
                self._project_title = title.strip()
                self.save_project()
            return
        title, ok = QInputDialog.getText(self, "Save As", "Название копии проекта:", text=self._project_title+" · copy")
        if ok and title.strip():
            project_id = self._project_id
            if self.executor:
                self.writer().submit("save_checkpoint", project_id, self.executor.checkpoint_snapshot())
            self.writer().submit("save_as", project_id, title.strip())

    def delete_project_checkpoint(self):
        if self.busy() or not self._project_id:
            self.log.setText("Удалять контрольную точку можно только вне активного запуска.")
            return
        if QMessageBox.question(self, "Delete Checkpoint", "Удалить сохранённый прогресс этого проекта? "
                                "Исходник и план сохранятся; следующий запуск начнёт рисунок заново.") == QMessageBox.StandardButton.Yes:
            self.writer().submit("delete_checkpoint", self._project_id)
            self._project_last_state = dict(cursor=0, executed=[], skipped=[], status="ready", metrics={}, controls={})
            self._resume_payload = None
            self.live_core.set_plan(self.plan)

    def load_project(self, project_id, resume=False):
        if not self._require_free(): return
        self.set_state("LOADING")
        def process(job):
            payload = self.project_store.load(project_id)
            done_plan = replace(payload["plan"], strokes=[payload["plan"].strokes[i] for i in payload["state"]["executed"]])
            payload["completed_preview"] = render_placement(done_plan)
            from app.ui.live_core import prepare_restored_core
            payload["plan"]._restored_core = prepare_restored_core(payload["plan"], payload["state"]["executed"], payload["preview"])
            return payload
        def ready(payload):
            self._loading = True
            self._project_id = project_id
            self._project_plan = payload["plan"]
            self._project_last_state = payload["state"]
            self._resume_payload = payload
            self._project_title = payload["manifest"]["title"]
            self.project_name.setText(self._project_title)
            self.source.setCurrentText("Image")
            self.original_source = "Image"
            self.original = payload["source"]
            self._source_key = payload["plan"].source_hash
            self._cached_request = self._cached_result = None
            self._analysis_pending = False
            self._analysis_timer.stop()
            self.original_view.set_image(self.original)
            self.profile = payload["profile"]
            self.profiles[self.profile.name] = self.profile
            self.refresh_profiles()
            options = payload["manifest"].get("options", {})
            self.engine.setCurrentText(payload["plan"].engine)
            self.human_mode.setCurrentText(options.get("mode", "BALANCED"))
            self.quality.setCurrentText(options.get("quality", self.quality.currentText()))
            self.speed.setCurrentText(options.get("speed", self.speed.currentText()))
            self.drawing_format.setCurrentText(options.get("format", self.drawing_format.currentText()))
            self.drawing_scale.setCurrentText(options.get("scale", self.drawing_scale.currentText()))
            self.drawing_width.setValue(options.get("custom_width", self.drawing_width.value()))
            self.drawing_height.setValue(options.get("custom_height", self.drawing_height.value()))
            self.crop_fit.setChecked(options.get("crop", self.crop_fit.isChecked()))
            self.brush_policy.setCurrentText(options.get("brush_policy", self.brush_policy.currentText()))
            self.brush_opacity.setValue(options.get("opacity", self.brush_opacity.value()))
            self.game_delay.setValue(options.get("game_delay", self.game_delay.value()))
            self.style.setCurrentText(options.get("style", self.style.currentText()))
            self.remove_bg.setChecked(options.get("remove_background", self.remove_bg.isChecked()))
            self.intelligence.setValue(options.get("detail_intelligence", self.intelligence.value()))
            self.priority_mode.setCurrentText(options.get("priority_mode", self.priority_mode.currentText()))
            self.detect_faces.setChecked(options.get("detect_faces", self.detect_faces.isChecked()))
            self.priority_regions = options.get("priority_regions", [])
            self.vector_accuracy.setCurrentText(options.get("vector_accuracy", self.vector_accuracy.currentText()))
            self.safety_buffer.setValue(options.get("safety_buffer", self.safety_buffer.value()))
            self.smart_finish.setChecked(options.get("smart_finish", self.smart_finish.isChecked()))
            self.limit.setCurrentText(options.get("limit", "Unlimited"))
            self.custom_time.setValue(options.get("custom_time", self.custom_time.value()))
            self._source_provenance = options.get("source_provenance", {})
            self._fill_settings = options.get("canvas_fill", {})
            self.fill_editor.set_settings(self._fill_settings)
            self._loading = False
            self._plan_ready((payload["plan"], payload["processed"], payload["preview"]))
            self.project_status.setText(f"Loaded · {payload['state']['cursor']}/{len(self.plan.strokes)}")
            self._v3_resume_after_load = resume
            self.navigate_v3("Live Drawing" if resume else "Workspace")
            self.set_state("READY TO RESUME" if payload["state"]["cursor"] else "IDLE")
        job = Job(process, self)
        self._start_job(job, ready)

    def resume_project(self):
        if self.executor:
            if self.executor.pause_event.is_set(): self.pause()
            return
        if self._resume_payload is None:
            if self._project_id and self._project_last_state and self._project_last_state.get("cursor", 0):
                self.load_project(self._project_id, resume=True)
                return
            self.navigate_v3("Projects")
            return
        if not self._require_free(): return
        try:
            payload = self._resume_payload
            if payload["state"]["cursor"] >= len(payload["plan"].strokes):
                raise ValueError("Все штрихи проекта уже выполнены")
            target = self._choose_target()
            if target is None: return
            p = self.profile
            expected = (p.client_size, p.dpi, p.target_class, p.target_process.casefold())
            actual = ((target.client.width, target.client.height), target.dpi, target.window_class, target.process.casefold())
            if expected != actual:
                raise SafetyError(f"Окно не соответствует проекту. Нужно {p.client_size[0]}×{p.client_size[1]}, DPI {p.dpi}, "
                                  f"{p.target_process}/{p.target_class}; сейчас {target.client.width}×{target.client.height}, "
                                  f"DPI {target.dpi}, {target.process}/{target.window_class}. "
                                  "Верните прежний режим окна или выполните CALIBRATE и Use Current Calibration.")
            executor = DrawingExecutor(self._backend(), p)
            executor.validate_plan(payload["plan"])
            self.plan = payload["plan"]
            self._begin_draw(executor, self.plan, None, False)
        except Exception as exc:
            self.error(str(exc))

    def confirm_project_canvas(self, screenshot, profile):
        payload = self._resume_payload
        r = profile.canvas
        current = screenshot.crop((r.x, r.y, r.x+r.width, r.y+r.height))
        data = payload["manifest"]
        comparison = compare_canvas(payload["canvas"], current, data.get("canvas_cursor"), payload["state"]["cursor"])
        if comparison["status"] == "match":
            return True
        dialog = QDialog(self)
        dialog.setWindowTitle("Resume · подтвердите игровой холст")
        box = QVBoxLayout(dialog)
        label = QLabel("Нельзя достоверно подтвердить состояние игрового холста. Слева сохранённый результат, справа текущий. "
                       "Продолжайте только если это та же работа, масштаб и положение совпадают. "
                       "При потере рисунка сервером продолжение с середины его не восстановит.")
        label.setWordWrap(True)
        box.addWidget(label)
        row = QHBoxLayout()
        for image in (payload["canvas"] or payload["completed_preview"], current):
            view = Preview()
            thumbnail = image.copy()
            thumbnail.thumbnail((420, 360))
            view.set_image(thumbnail)
            row.addWidget(view)
        box.addLayout(row, 1)
        confirmed = QCheckBox("Подтверждаю: открыта та же работа, положение и масштаб холста совпадают")
        box.addWidget(confirmed)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Resume remaining strokes")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        confirmed.toggled.connect(buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        dialog.resize(880, 550)
        accepted = bool(dialog.exec())
        if accepted: self._activate_target()
        return accepted

    def adopt_project_calibration(self):
        if self.busy() or self._resume_payload is None or self.profile is None:
            self.log.setText("Откройте сохранённый проект, выполните CALIBRATE и выберите Use Current Calibration.")
            return
        try:
            plan = self._resume_payload["plan"]
            plan.drawing_area(self.profile.canvas)
            old = self._resume_payload["profile"]
            if self.profile.target_process.casefold() != old.target_process.casefold():
                raise ValueError("Процесс новой калибровки не соответствует игре проекта")
            if QMessageBox.question(self, "Калибровка проекта", "Использовать новые координаты для оставшихся мазков? "
                                    "Физический размер холста должен остаться прежним. Перед вводом будет проверка изображения.") != QMessageBox.StandardButton.Yes:
                return
            self.profile.verified = old.verified
            self._resume_payload["profile"] = self.profile
            self.writer().submit("update_profile", self._project_id, self.profile)
            self._project_plan = plan
            self._plan_ready((plan, self._resume_payload["processed"], self._resume_payload["preview"]))
        except Exception as exc:
            self.error(str(exc))

    def v3_plan_ready(self, result):
        plan, processed, preview = result
        plan._project_preview = preview
        if self._project_plan is not plan:
            self._project_id = self._project_plan = self._resume_payload = None
            self._project_last_state = None
        executed = self._project_last_state.get("executed", []) if self._project_last_state else []
        self.live_core.set_plan(plan, executed)
        if self.original is not None:
            self.fill_editor.set_source(self.original, plan.canvas_size, self.crop_fit.isChecked())
        self.layer_select.blockSignals(True)
        self.layer_select.clear()
        self.layer_select.addItem("All virtual layers", -1)
        from app.human import STAGES
        for stage, name in enumerate(STAGES):
            self.layer_select.addItem(f"{stage+1:02d} · {name}", stage)
        self.layer_select.blockSignals(False)
        if plan.analysis.get("fill", {}).get("padding_pixels", 0):
            self.project_status.setText("Есть добавленные поля · откройте Smart Canvas Fill")

    def fill_settings_changed(self, settings):
        self._fill_settings = settings
        self.settings["v3_canvas_fill"] = settings
        self.invalidate_plan()

    def show_layer(self, *_):
        if self.plan is None or self.busy(): return
        stage = self.layer_select.currentData()
        plan = self.plan
        def render(job):
            return render_placement(plan if stage == -1 else replace(plan, strokes=[s for s in plan.strokes if s.stage == stage]))
        self._start_job(Job(render, self), lambda image: self.draw_view.set_image(image))

    def discover_analysis_options(self):
        p = self.profile
        return dict(canvas_size=(p.canvas.width, p.canvas.height) if p else (534, 530),
                    widths=tuple(sorted(b.pixels for b in p.brushes)) if p else (1, 2, 4, 8, 16, 32),
                    palette=[s.rgb for s in p.swatches] if p and not p.dynamic_color else None)

    def import_discovery_image(self, path):
        if not self._require_free(): return
        self.load_image(path)
        if self.discover_page.selected is not None:
            from dataclasses import asdict
            self._source_provenance = asdict(self.discover_page.selected)

    def background_jobs_running(self):
        return any(job and job.isRunning() for job in
                   (self._project_library_job, self.discover_page.job, self.fill_editor.job))

    def stop_background_jobs(self):
        for job in (self._project_library_job, self.discover_page.job, self.fill_editor.job):
            if job: job.cancel.set()

    def close_resources(self):
        """Release workers/timers while QApplication still exists."""
        self._closing = False
        if self.executor:
            self.executor.stop()
        if self.job:
            self.job.cancel.set()
        self.stop_background_jobs()
        for timer in (self._clock_timer, self._analysis_timer, self._simulation_timer,
                      self.live_core._timer, self.fill_editor._timer, self._rebalance_timer, self._writer_timer):
            timer.stop()
        self.live_core._complete_animation.stop()
        self.timer_ring.animation.stop()
        if hasattr(self, "_panel_animation"):
            self._panel_animation.stop()
        for hover in getattr(self, "_hover_animations", []):
            hover.animation.stop()
            hover.button.removeEventFilter(hover)
            hover.enabled = lambda: False
        self._hover_animations = []
        if self._project_writer:
            self._project_writer.close()
        self.journal.close()

    def engine_event(self, event):
        self.live_core.consume(event)

    def v3_job_finished(self):
        self.v3_engine_controls()
        if getattr(self, "_v3_resume_after_load", False):
            self._v3_resume_after_load = False
            QTimer.singleShot(0, self.resume_project)

    def calibrate_speed(self):
        from app.speed_calibration import calibration_plan
        if not self._require_free(): return
        try:
            if not self.profile or not self.hotkeys_ready:
                raise ValueError("Нужны профиль и рабочая остановка F9")
            if self._get_target() is None: return
            if QMessageBox.question(self, "Калибровка скорости", "На чистом холсте будут нарисованы четыре длинных штриха "
                                    "с разной скоростью. Программа измерит принятые линии и предложит рабочую скорость. "
                                    "Ничего не очищается автоматически. Продолжить?") != QMessageBox.StandardButton.Yes:
                return
            self._speed_calibration = True
            plan = calibration_plan(self.profile, self.game_delay.value()/1000)
            self._begin_draw(DrawingExecutor(self._backend(), self.profile), plan, None, True)
        except Exception as exc:
            self.error(str(exc))
