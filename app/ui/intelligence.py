"""Studio actions kept separate from existing import/calibration/input workflows."""
from dataclasses import replace
import time
import math

import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QInputDialog

from app.planner import build_plan, render_plan, render_placement
from app.priority import analyze, heatmap
from app.smart_timer import DrawingClock
from app.ui.common import Job
from app.ui.instruments import minutes
from app.vector import path_metrics


class StudioActions:
    def init_studio(self):
        self.priority_regions = []
        self.priority_result = None
        self._source_key = None
        self._analysis_pending = False
        self._last_options = None
        self._round_clock = None
        self._last_clock = None
        self._last_eta = None
        self._simulation_frames = []
        self._simulation_index = 0
        self._analysis_timer = QTimer(self)
        self._analysis_timer.setSingleShot(True)
        self._analysis_timer.timeout.connect(self.analyze_priorities)
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(200)
        self._clock_timer.timeout.connect(self.update_clock)
        self._simulation_timer = QTimer(self)
        self._simulation_timer.setInterval(100)
        self._simulation_timer.timeout.connect(self.simulation_step)

    def restore_studio(self):
        for key, widget in [("studio_engine", self.engine), ("studio_accuracy", self.vector_accuracy),
                            ("studio_priority_mode", self.priority_mode), ("studio_brush_policy", self.brush_policy)]:
            value = self.settings.get(key)
            if value and widget.findText(value) >= 0:
                widget.setCurrentText(value)
        self.intelligence.setValue(int(self.settings.get("studio_intelligence", 75)))
        self.brush_opacity.setValue(int(self.settings.get("studio_opacity", 100)))
        self.game_delay.setValue(int(self.settings.get("studio_game_delay", 250)))
        self.detect_faces.setChecked(bool(self.settings.get("studio_detect_faces", True)))
        self.smart_finish.setChecked(bool(self.settings.get("studio_smart_finish", True)))
        self.safety_buffer.setValue(int(self.settings.get("studio_buffer", 8)))
        self.custom_time.setValue(int(self.settings.get("studio_custom_time", 180)))
        self.overlay_enabled.setChecked(bool(self.settings.get("studio_overlay", False)))
        self.animations_enabled.setChecked(bool(self.settings.get("studio_animations", True)))
        self.intelligence_label.setText(f"DETAIL INTELLIGENCE · {self.intelligence.value()}%")
        self.custom_time.setEnabled(self.limit.currentData() == "custom")
        self._clock_timer.start()

    def save_studio_options(self):
        if not hasattr(self, "engine"):
            return
        self.settings.update(studio_engine=self.engine.currentText(), studio_accuracy=self.vector_accuracy.currentText(),
                             studio_priority_mode=self.priority_mode.currentText(), studio_intelligence=self.intelligence.value(),
                             studio_detect_faces=self.detect_faces.isChecked(), studio_smart_finish=self.smart_finish.isChecked(),
                             studio_buffer=self.safety_buffer.value(), studio_custom_time=self.custom_time.value())
        self.settings["studio_brush_policy"] = self.brush_policy.currentText()
        self.settings["studio_opacity"] = self.brush_opacity.value()
        self.settings["studio_game_delay"] = self.game_delay.value()

    def studio_image_changed(self, path):
        self._source_key = path.stem
        self.priority_regions = list(self.settings.get("image_priority_regions", {}).get(self._source_key, []))
        self.priority_result = None
        self._last_clock = self._last_eta = None
        self._analysis_pending = True
        self._analysis_timer.start(250)
        self._simulation_timer.stop()
        self._simulation_frames = []

    def intelligence_changed(self, *_):
        self.intelligence_label.setText(f"DETAIL INTELLIGENCE · {self.intelligence.value()}%")
        self.invalidate_plan()
        if self._loading:
            return
        if self.original is not None:
            self._analysis_pending = True
            self._analysis_timer.start(300)

    def analyze_priorities(self):
        if self.original is None:
            self.log.setText("Сначала загрузите изображение через Image Import или CAPTURE.")
            return
        if self.busy():
            self._analysis_pending = True
            return
        self._analysis_pending = False
        image = self.original.copy()
        mode, detect, regions = self.priority_mode.currentText(), self.detect_faces.isChecked(), tuple(self.priority_regions)
        strength = self.intelligence.value()
        def process(job):
            result = analyze(image, mode, detect, regions)
            if job.cancel.is_set():
                raise InterruptedError()
            result_scores = result.scores if strength else np.full_like(result.scores, 50)
            return result, heatmap(image, result_scores)
        self.set_state("ANALYZING")
        self._start_job(Job(process, self), self.apply_analysis)

    def apply_analysis(self, result):
        analysis, image = result
        self.priority_result = analysis
        self.priority_view.set_image(image)
        self.priority_info.setText(analysis.method+f"\nОбластей: {len(analysis.regions)}; ручных: {len(self.priority_regions)}.\n"
                                   "Красный ≥85 · оранжевый ≥65 · жёлтый ≥40 · серый — низкий.")
        if self._state == "ANALYZING":
            self.set_state("IDLE")

    def set_priority_selection(self, selected):
        self.priority_view.selection_mode = selected
        self.previews.setCurrentIndex(3)

    def add_priority_region(self, box):
        if self.busy() or self.original is None:
            return
        self.priority_regions.append((*box, self.region_score.value()))
        self.priority_regions = self.priority_regions[-100:]
        self.persist_priority_regions()

    def undo_priority_region(self):
        if self.priority_regions and not self.busy():
            self.priority_regions.pop()
            self.persist_priority_regions()

    def clear_priority_regions(self):
        if not self.busy():
            self.priority_regions = []
            self.persist_priority_regions()

    def persist_priority_regions(self):
        if self._source_key:
            records = self.settings.setdefault("image_priority_regions", {})
            records[self._source_key] = self.priority_regions
            self.settings["image_priority_regions"] = dict(list(records.items())[-20:])
        self.intelligence_changed()

    def timer_changed(self, *_):
        if not hasattr(self, "custom_time"):
            return
        self.custom_time.setEnabled(self.limit.currentData() == "custom" and not self.busy())
        self._round_clock = None
        self._last_clock = None
        self.invalidate_plan()

    def configured_limit(self):
        data = self.limit.currentData()
        return float(self.custom_time.value()) if data == "custom" else (float(data) if data is not None else None)

    def sync_round_clock(self):
        if self.busy():
            return
        self._round_clock = DrawingClock(self.configured_limit())
        self._last_clock = None
        self.log.setText("Отсчёт синхронизирован вручную. Пауза приложения не продлевает раунд.")

    def reset_round_clock(self):
        if self.executor:
            self._reset_on_finish = True
            self.stop()
        self._round_clock = None
        self._last_clock = None
        self._last_eta = None
        self.timer_ring.display(0, self.configured_limit(), "READY TO DRAW")

    def save_timer_preset(self):
        if self.busy():
            return
        name, ok = QInputDialog.getText(self, "Пресет таймера", "Название:")
        if not ok or not name.strip():
            return
        value = self.configured_limit()
        if value is None:
            return
        name = name.strip()[:40]
        label = f"{name} · {int(value)} s"
        presets = self.settings.setdefault("timer_presets", {})
        presets[label] = int(value)
        presets = dict(list(presets.items())[-20:])
        self.settings["timer_presets"] = presets
        if self.limit.findText(label) < 0:
            self.limit.addItem(label, value)
        self.limit.setCurrentText(label)
        self.store.save_settings(self.settings)

    def update_clock(self):
        executor = self.executor
        clock = executor.clock if executor and executor.clock else self._round_clock
        snapshot = clock.snapshot() if clock else self._last_clock
        if snapshot is None:
            self.timer_ring.display(0, self.configured_limit(), "READY TO DRAW")
            return
        remaining = snapshot["remaining"]
        total = (getattr(executor, "total_strokes", 0) if executor and executor.clock else
                 self._last_clock.get("total", 0) if self._last_clock else 0)
        done = len(executor.executed_indices) if executor else (self._last_clock.get("strokes", 0) if self._last_clock else 0)
        progress = min(1., done/max(1, total))
        if hasattr(self, "live_core") and self.live_core.plan is not None and total == len(self.live_core.plan.strokes):
            progress = self.live_core.fraction
        if not executor and self._last_clock:
            progress = min(1., self._last_clock.get("progress", 0))
        eta = self._last_eta
        pen_seconds = executor._pen_seconds if executor else snapshot.get("draw_seconds", 0.)
        if executor and executor._pen_started is not None:
            pen_seconds += time.monotonic()-executor._pen_started
        risk = 0 if remaining is None or eta is None else (2 if eta > remaining else 1 if eta > remaining*.8 else 0)
        if remaining is not None and remaining <= self.safety_buffer.value():
            risk = 2
        caption = "PAUSED · ROUND RUNNING" if executor and executor.pause_event.is_set() else self._state
        self.timer_ring.display(progress, remaining, caption, risk)
        self.clock_stats.setText(f"{progress*100:.0f}% · {done}/{total} штрихов\n"
                                 f"Всего {minutes(snapshot['elapsed'])} · кисть {minutes(pen_seconds)} · "
                                 f"пауза {minutes(snapshot['paused'])}\n"
                                 f"Прогноз завершения: {minutes(snapshot['elapsed']+eta) if eta is not None else '—'} · "
                                 f"до дедлайна {minutes(remaining)}")
        if hasattr(self.icon, "update_status"):
            self.icon.update_status(self._state, progress, remaining)

    def update_comparison(self, *_):
        if self.original is None or self.plan is None:
            return
        if self._source_key != self.plan.source_hash:
            self.log.setText("Для Before/After импортируйте исходник именно этого плана.")
            return
        result = getattr(self.plan, "_comparison_output", None)
        original = getattr(self.plan, "_comparison_original", None)
        if result is None or original is None:
            from app.imaging import prepare
            result = render_placement(self.plan)
            original = Image.new("RGB", result.size, "white")
            fitted = prepare(self.original, self.plan.canvas_size, self.crop_fit.isChecked(), "Custom")
            area = self.plan.drawing_rect
            original.paste(fitted, (area.x, area.y) if area else (0, 0))
            result.thumbnail((1000, 1000))
            original = original.resize(result.size, Image.Resampling.LANCZOS)
            self.plan._comparison_output, self.plan._comparison_original = result, original
        position = round(result.width*self.before_after.value()/100)
        comparison = result.copy()
        comparison.paste(original.crop((0, 0, position, original.height)), (0, 0))
        ImageDraw.Draw(comparison).line((position, 0, position, result.height), fill="#E73558", width=2)
        self.comparison_view.set_image(comparison)
        self.previews.setCurrentIndex(6)

    def compare_engines(self):
        if not self._require_free() or self.original is None or self._last_options is None:
            self.log.setText("Сначала постройте PREVIEW.")
            return
        image, options = self.original.copy(), self._last_options
        def process(job):
            started = time.monotonic()
            old, _ = build_plan(image, replace(options, engine="Legacy", time_limit=None), cancel=job.cancel)
            old_seconds = time.monotonic()-started
            started = time.monotonic()
            new, _ = build_plan(image, replace(options, engine="Vector 2.0", time_limit=None), cancel=job.cancel)
            new_seconds = time.monotonic()-started
            a, b = render_plan(old), render_plan(new)
            a.thumbnail((600, 600)); b.thumbnail((600, 600))
            preview = Image.new("RGB", (a.width+b.width+12, max(a.height, b.height)+28), "#131720")
            preview.paste(a, (0, 28)); preview.paste(b, (a.width+12, 28))
            draw = ImageDraw.Draw(preview)
            draw.text((8, 7), "OLD ENGINE", fill="white")
            draw.text((a.width+20, 7), "VECTOR ENGINE 2.0", fill="white")
            return old, new, preview, old_seconds, new_seconds
        def ready(result):
            old, new, image, old_seconds, new_seconds = result
            self.comparison_view.set_image(image)
            self.previews.setCurrentIndex(6)
            text = []
            for name, plan, seconds in [("OLD", old, old_seconds), ("V2", new, new_seconds)]:
                metrics = path_metrics(plan.strokes, plan.canvas_size)
                text.append(f"{name}: {metrics['strokes']} штрихов · {metrics['points']} точек · "
                            f"рисование {metrics['draw_length']:.0f}px · переходы {metrics['travel_length']:.0f}px · "
                            f"оценка {plan.estimated_seconds:.1f}s · расчёт {seconds:.2f}s")
            self.vector_stats.setText("\n\n".join(text)+"\nСравнение без лимита; это реальные планы, не измерение Roblox.")
            self.set_state("IDLE")
        self.set_state("COMPARING")
        self._start_job(Job(process, self), ready)

    def prepare_simulation(self):
        if not self._require_free():
            return
        if self.plan is None:
            self.log.setText("Сначала загрузите изображение и нажмите PREVIEW.")
            return
        if self._simulation_frames:
            self._simulation_index = 0
            self._simulation_timer.start()
            self.previews.setCurrentIndex(7)
            return
        plan = self.plan
        def process(job):
            from app.raster import draw_stroke
            factor = min(1., 640/max(plan.canvas_size))
            size = tuple(max(1, round(n*factor)) for n in plan.canvas_size)
            image = Image.new("RGB", size, "white")
            draw = ImageDraw.Draw(image)
            frames = [image.copy()]
            step = max(1, math.ceil(len(plan.strokes)/24))
            for index, stroke in enumerate(plan.strokes):
                if job.cancel.is_set():
                    raise InterruptedError()
                draw_stroke(draw, stroke, plan.canvas_size, size, stroke.color)
                if index % step == 0:
                    frames.append(image.copy())
            frames.append(image.copy())
            return frames
        def ready(frames):
            self._simulation_frames = frames
            self._simulation_index = 0
            self._simulation_timer.start()
            self.previews.setCurrentIndex(7)
            self.set_state("IDLE")
        self.set_state("SIMULATING")
        self._start_job(Job(process, self), ready)

    def simulation_step(self):
        if self._simulation_index >= len(self._simulation_frames):
            self._simulation_timer.stop()
            return
        self.simulation_view.set_image(self._simulation_frames[self._simulation_index])
        self._simulation_index += 1
