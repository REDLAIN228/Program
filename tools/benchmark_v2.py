"""Reproducible CPU plans + actual app-local Qt event delivery; never Roblox input.

Run: QT_QPA_PLATFORM=offscreen .venv/bin/python tools/benchmark_v2.py
Windows: use the interpreter from logs/python-path.txt. Qt delivery is still local,
not SendInput. Default outputs: artifacts/v2-benchmark/report.json and PNG fixtures.
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

from app.automation import DrawingExecutor
from app.imaging import prepare
from app.models import Rect, Timing
from app.planner import PlanOptions, build_plan, render_plan
from app.priority import analyze
from app.smart_timer import fit_budget
from app.ui.test_canvas import TestCanvas, QtCanvasBackend, COLORS
from app.vector import path_metrics


def fixtures():
    portrait = Image.new("RGB", (128, 128), "white")
    d = ImageDraw.Draw(portrait)
    d.ellipse((20, 8, 108, 118), fill=COLORS[0])
    d.ellipse((28, 30, 100, 110), fill=COLORS[7])
    d.ellipse((40, 51, 53, 68), fill=COLORS[0])
    d.ellipse((75, 51, 88, 68), fill=COLORS[0])
    d.arc((51, 75, 77, 95), 0, 180, fill=COLORS[0], width=3)
    landscape = Image.new("RGB", (128, 128), COLORS[5])
    d = ImageDraw.Draw(landscape)
    d.ellipse((88, 9, 111, 32), fill=COLORS[3])
    d.polygon(((0, 90), (37, 36), (92, 104)), fill=COLORS[11])
    d.polygon(((42, 105), (93, 48), (128, 105)), fill=COLORS[4])
    d.rectangle((0, 105, 128, 128), fill=COLORS[8])
    texture = Image.new("RGB", (128, 128), "white")
    d = ImageDraw.Draw(texture)
    for x in range(8, 120, 10):
        d.arc((x-25, 10, x+35, 120), 280, 80, fill=COLORS[(x//10)%6], width=3)
    d.rectangle((22, 42, 106, 79), fill=COLORS[10])
    d.text((30, 55), "ANIME 2.0", fill=COLORS[0])
    return dict(portrait=portrait, landscape=landscape, texture_text=texture)


def image_metrics(expected, actual, priority):
    a, b = np.asarray(expected).astype(float), np.asarray(actual).astype(float)
    agreement = np.max(np.abs(a-b), axis=2) < 30
    important = cv2.resize(priority, expected.size) >= 85
    edge_a = cv2.Canny(cv2.cvtColor(a.astype(np.uint8), cv2.COLOR_RGB2GRAY), 60, 140)
    edge_b = cv2.Canny(cv2.cvtColor(b.astype(np.uint8), cv2.COLOR_RGB2GRAY), 60, 140)
    da, db = cv2.distanceTransform(255-edge_a, cv2.DIST_L2, 3), cv2.distanceTransform(255-edge_b, cv2.DIST_L2, 3)
    distances = np.concatenate((db[edge_a > 0], da[edge_b > 0]))
    return dict(pixel_agreement=float(np.mean(agreement)),
                interior_pixel_agreement=float(np.mean(agreement[4:-4, 4:-4])),
                important_agreement=float(np.mean(agreement[important])) if np.any(important) else None,
                edge_distance_mean=float(np.mean(distances)) if len(distances) else 0.,
                edge_distance_max=float(np.max(distances)) if len(distances) else 0.)


def main():
    application = QApplication([])
    application.setQuitOnLastWindowClosed(False)
    root = Path(__file__).resolve().parents[1]/"artifacts/v2-benchmark"
    root.mkdir(parents=True, exist_ok=True)
    canvas = TestCanvas()
    canvas.show()
    canvas.activateWindow()
    application.processEvents()
    profile = canvas.profile(False)
    # Draw a real 128x128 region inside the known local canvas; ordinary Qt mouse
    # events must reach the widget, change its pixels, and finish without errors.
    profile.canvas = Rect(profile.canvas.x, profile.canvas.y, 128, 128)
    profile.verified = True
    report = dict(scope="CPU planning and app-local Qt event delivery only; no Roblox or SendInput validation",
                  local_timing="event=.0001s, settle=.0001s, 1e6 px/s, samples=40px; accelerated app-local test only",
                  metric_note="Full-frame metrics include the executor's required unpainted safety inset. Interior agreement excludes 4px on each side. The actual local canvas supports 3/9/18px brushes, so 1px text cannot be reproduced exactly.",
                  cases={})
    for name, source in fixtures().items():
        source.save(root/f"{name}-source.png")
        expected = prepare(source, (128, 128), style="Custom")
        priority = analyze(expected, "Auto", False).scores
        case = {}
        for engine in ("Legacy", "Vector 2.0"):
            started = time.monotonic()
            plan, _ = build_plan(source, PlanOptions((128, 128), style="Custom", engine=engine, time_limit=None,
                                                     palette=COLORS, brush_widths=(3, 9, 18), detect_faces=False))
            planning = time.monotonic()-started
            preview = render_plan(plan)
            entry = {**path_metrics(plan.strokes, plan.canvas_size), "plan_seconds": planning,
                     "estimated_seconds_at_Normal": plan.estimated_seconds,
                     "preview_accuracy": image_metrics(expected, preview, priority)}
            plan = replace(plan, timing=Timing(.0001, .0001, 1000000, 40), smart_finish=False)
            canvas.clear()
            canvas.activateWindow()
            application.processEvents()
            executor = DrawingExecutor(QtCanvasBackend(canvas), profile)
            result, errors = [], []
            def draw():
                try:
                    result.append(executor.run(plan))
                except Exception as exc:
                    errors.append(str(exc))
            started = time.monotonic()
            worker = threading.Thread(target=draw)
            worker.start()
            while worker.is_alive():
                application.processEvents()
                time.sleep(.0005)
            worker.join()
            entry["local_execution_seconds"] = time.monotonic()-started
            actual = canvas.screenshot().crop((profile.canvas.x, profile.canvas.y,
                                               profile.canvas.x+128, profile.canvas.y+128))
            entry["local_accuracy"] = image_metrics(expected, actual, priority)
            entry["outcomes"], entry["errors"] = result, errors
            entry["received_segments"] = canvas.received_segments
            slug = engine.replace(" ", "-")
            preview.save(root/f"{name}-{slug}-preview.png")
            actual.save(root/f"{name}-{slug}-local.png")
            case[engine] = entry
            print(name, engine, entry["strokes"], f"{entry['local_execution_seconds']:.2f}s", flush=True)
            if result != ["finished"] or errors or not canvas.received_segments:
                raise RuntimeError(f"App-local execution failed: {name} {engine}: {errors}")
        limited, _ = build_plan(source, PlanOptions((128, 128), style="Custom", engine="Vector 2.0", time_limit=None,
                                                   palette=COLORS, brush_widths=(3, 9, 18), detect_faces=False))
        deadline = case["Legacy"]["estimated_seconds_at_Normal"]+8
        limited = fit_budget(limited, deadline)
        case["time_budget_v2"] = dict(limit_seconds=deadline, safety_buffer=limited.safety_buffer,
                                       estimated_seconds=limited.estimated_seconds, strokes=len(limited.strokes),
                                       feasible=limited.metrics.get("budget_feasible", True),
                                       preview_accuracy=image_metrics(expected, render_plan(limited), priority),
                                       scope="CPU plan only; not executed in the local benchmark")
        report["cases"][name] = case
    canvas.close()
    (root/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved", root/"report.json")


if __name__ == "__main__":
    main()
