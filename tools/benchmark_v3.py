"""Same-fixture, actual Qt input comparison: previous engines vs all Human modes.

No Roblox, SendInput or network timing claim is made by this benchmark.
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PIL import Image
from app.automation import DrawingExecutor
from app.imaging import prepare
from app.models import Rect, Timing
from app.planner import PlanOptions, build_plan, render_plan
from app.priority import analyze
from app.ui.test_canvas import TestCanvas, QtCanvasBackend, COLORS
from app.vector import path_metrics
from benchmark_v2 import fixtures, image_metrics


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    root = Path(__file__).resolve().parents[1]
    output = root/"artifacts/v3-benchmark"
    output.mkdir(parents=True, exist_ok=True)
    canvas = TestCanvas()
    canvas.show()
    canvas.activateWindow()
    app.processEvents()
    profile = canvas.profile(False)
    profile.canvas = Rect(profile.canvas.x, profile.canvas.y, 128, 128)
    profile.verified = True  # Known app-owned widget, never a game profile.
    report = dict(scope="Actual app-local Qt mouse-event delivery; Linux CPU; no Roblox/SendInput validation",
                  timing="event=.0001, settle=.0001, pps=1e6, sample=40; identical to v2 baseline, not a user speed preset",
                  before_commit="ee7c55d1062efd412c3767b2eec2194e68c1e1db", cases={})
    for name, source in fixtures().items():
        expected = prepare(source, (128, 128), style="Custom")
        priority = analyze(expected, "Auto", False).scores
        entries = {}
        for engine, mode in (("Legacy", "BALANCED"), ("Vector 2.0", "BALANCED"),
                             ("Human 3.0", "FAST"), ("Human 3.0", "BALANCED"), ("Human 3.0", "MASTERPIECE")):
            label = engine if engine != "Human 3.0" else engine+" "+mode
            started = time.monotonic()
            plan, _ = build_plan(source, PlanOptions((128, 128), style="Custom", engine=engine, human_mode=mode,
                                  time_limit=None, palette=COLORS, brush_widths=(3, 9, 18), detect_faces=False))
            planning = time.monotonic()-started
            preview = render_plan(plan)
            metrics = {**path_metrics(plan.strokes, plan.canvas_size), "planning_seconds": planning,
                       "estimated_Normal_seconds": plan.estimated_seconds,
                       "preview_accuracy": image_metrics(expected, preview, priority)}
            plan = replace(plan, timing=Timing(.0001, .0001, 1e6, 40), smart_finish=False)
            canvas.clear()
            canvas.activateWindow()
            app.processEvents()
            executor = DrawingExecutor(QtCanvasBackend(canvas), profile)
            outcomes, failures = [], []
            def run():
                try: outcomes.append(executor.run(plan))
                except Exception as exc: failures.append(str(exc))
            thread = threading.Thread(target=run)
            started = time.monotonic()
            thread.start()
            while thread.is_alive():
                app.processEvents()
                time.sleep(.0005)
            thread.join()
            metrics["local_execution_seconds"] = time.monotonic()-started
            r = profile.canvas
            actual = canvas.screenshot().crop((r.x, r.y, r.x+r.width, r.y+r.height))
            metrics.update(local_accuracy=image_metrics(expected, actual, priority),
                           actual_input=executor.telemetry.snapshot(), outcomes=outcomes, errors=failures,
                           received_segments=canvas.received_segments)
            slug = label.replace(" ", "-")
            preview.save(output/f"{name}-{slug}-preview.png")
            actual.save(output/f"{name}-{slug}-actual.png")
            entries[label] = metrics
            print(name, label, len(plan.strokes), "strokes", f"{metrics['local_execution_seconds']:.3f}s",
                  f"accuracy={metrics['local_accuracy']['pixel_agreement']:.3f}", flush=True)
            if outcomes != ["finished"] or failures or not canvas.received_segments:
                raise RuntimeError(f"Input benchmark failed: {name} {label}: {failures}")
        report["cases"][name] = entries
        (output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    canvas.close()
    (root/"docs/v3-benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print("Saved", output/"report.json")


if __name__ == "__main__": main()
