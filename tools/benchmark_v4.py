"""Executor pacing before/after on this OS, with a real user speed preset.

Same fixtures, same plans, same profile, same "Turbo · 7" timing. The only
difference between the two columns is how the executor waits:
  legacy  — threading.Event.wait (3.0 behaviour),
  precise — app.precise_wait.PreciseWaiter (4.0).
Input goes to an in-memory simulated paint window (SimGame), not Roblox and
not SendInput, so no game registration claim is made. The Win32 guard cost
is measured separately by tools/guard_cost.py.

Run: python tools/benchmark_v4.py  ->  docs/v4-benchmark.json
"""
import contextlib
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

from app.automation import DrawingExecutor, WindowState
from app.imaging import prepare
from app.models import Rect, Timing, estimate_plan
from app.planner import PlanOptions, build_plan, render_plan
from app.priority import analyze
from app.ui.test_canvas import COLORS, TestCanvas
from app.vector import path_metrics
from benchmark_v2 import fixtures, image_metrics

PRESET = "Turbo · 7"


class LegacyWaiter:
    """3.0 behaviour: Event.wait rounds short timeouts to the OS tick."""
    def __init__(self, stop_event):
        self.stop_event = stop_event

    def wait(self, seconds):
        return self.stop_event.wait(max(0., seconds))

    pace = wait

    def reset_pace(self):
        pass

    @staticmethod
    def high_resolution():
        return contextlib.nullcontext()


class SimGame:
    """Swatch/brush paint window in memory. Every move while pressed is a segment."""
    external_input = False

    def __init__(self, profile):
        self.profile = profile
        self.origin = (100, 100)
        self.state = WindowState(1, "SimGame", profile.target_class, profile.target_process,
                                 Rect(*self.origin, *profile.client_size), profile.dpi)
        r = profile.canvas
        self.image = Image.new("RGB", (r.width, r.height), "white")
        self.draw = ImageDraw.Draw(self.image)
        self.color, self.width = COLORS[0], profile.brushes[0].pixels
        self.pressed = False
        self.position = self.last = None
        self.segments = 0

    def _local(self, x, y):
        return x-self.origin[0], y-self.origin[1]

    def snapshot(self):
        return self.state

    def is_foreground(self):
        return True

    def point_belongs_to_target(self, x, y):
        return self.state.client.contains(x, y)

    def _canvas_point(self, x, y):
        lx, ly = self._local(x, y)
        r = self.profile.canvas
        return (lx-r.x, ly-r.y) if r.contains(lx, ly) else None

    def _paint(self, a, b):
        w = self.width
        self.draw.line([a, b], fill=self.color, width=w)
        for x, y in (a, b):
            self.draw.ellipse((x-w/2, y-w/2, x+w/2, y+w/2), fill=self.color)
        self.segments += 1

    def move(self, x, y):
        self.position = (x, y)
        if self.pressed:
            point = self._canvas_point(x, y)
            if point is not None and self.last is not None:
                self._paint(self.last, point)
            self.last = point

    def down(self):
        self.pressed = True
        local = self._local(*self.position)
        for swatch in self.profile.swatches:
            if math.dist(local, swatch.point) <= 2:
                self.color = swatch.rgb
                return
        for brush in self.profile.brushes:
            if math.dist(local, brush.point) <= 2:
                self.width = brush.pixels
                return
        self.last = self._canvas_point(*self.position)
        if self.last is not None:
            self._paint(self.last, self.last)

    def up(self):
        self.pressed = False
        self.last = None

    def sample(self, x, y):
        local = self._local(x, y)
        if self.profile.color_indicator and math.dist(local, self.profile.color_indicator) <= 1:
            return self.color
        for anchor in self.profile.anchors:
            if math.dist(local, anchor.point) <= 1:
                return anchor.rgb
        point = self._canvas_point(x, y)
        return self.image.getpixel(point) if point else (0, 0, 0)


def execute(plan, profile, waiter):
    game = SimGame(profile)
    executor = DrawingExecutor(game, profile)
    if waiter == "legacy":
        executor._waiter = LegacyWaiter(executor.stop_event)
    started = time.perf_counter()
    outcome = executor.run(plan)
    seconds = time.perf_counter()-started
    telemetry = executor.telemetry.snapshot()
    return game, dict(outcome=outcome, seconds=round(seconds, 3),
                      pen_seconds=round(executor.run_metrics["draw_seconds"], 3),
                      predicted_seconds=round(plan.estimated_seconds, 3),
                      mouse_moves=telemetry["mouse_moves"], mouse_presses=telemetry["mouse_presses"],
                      wait_calls=telemetry["wait_calls"], wait_seconds=round(telemetry["wait_seconds"], 3),
                      received_segments=game.segments)


def main():
    app = QApplication.instance() or QApplication([])
    canvas = TestCanvas()
    profile = canvas.profile(False)
    profile.canvas = Rect(profile.canvas.x, profile.canvas.y, 128, 128)
    profile.verified = True
    timing = Timing.preset(PRESET)
    report = dict(scope="Executor pacing on this OS with an in-memory paint window; not Roblox, not SendInput",
                  os=f"{platform.system()} {platform.release()}", python=platform.python_version(),
                  timing=PRESET, cases={})
    for name, source in fixtures().items():
        expected = prepare(source, (128, 128), style="Custom")
        priority = analyze(expected, "Auto", False).scores
        cases = {}
        for engine, mode in (("Vector 2.0", "BALANCED"), ("Human 3.0", "FAST"),
                             ("Human 3.0", "BALANCED"), ("Human 3.0", "MASTERPIECE")):
            label = engine if engine != "Human 3.0" else f"{engine} {mode}"
            started = time.perf_counter()
            plan, _ = build_plan(source, PlanOptions((128, 128), style="Custom", engine=engine, human_mode=mode,
                                  time_limit=None, palette=COLORS, brush_widths=(3, 9, 18), detect_faces=False))
            planning = time.perf_counter()-started
            plan = replace(plan, timing=timing, smart_finish=False,
                           estimated_seconds=estimate_plan(plan.strokes, plan.canvas_size, timing, 1, 1))
            preview = render_plan(plan)
            row = dict(strokes=len(plan.strokes), planning_seconds=round(planning, 3),
                       path=path_metrics(plan.strokes, plan.canvas_size),
                       preview_vs_source=image_metrics(expected, preview, priority))
            for waiter in ("legacy", "precise"):
                game, result = execute(plan, profile, waiter)
                result["received_vs_preview"] = image_metrics(preview, game.image, priority)
                result["received_vs_source"] = image_metrics(expected, game.image, priority)
                row[waiter] = result
            row["speedup"] = round(row["legacy"]["seconds"]/row["precise"]["seconds"], 2)
            cases[label] = row
            print(name, label, row["strokes"], "strokes", f"legacy {row['legacy']['seconds']}s",
                  f"precise {row['precise']['seconds']}s", f"x{row['speedup']}",
                  f"agree {row['precise']['received_vs_source']['pixel_agreement']:.3f}", flush=True)
        report["cases"][name] = cases
    out = Path(__file__).resolve().parents[1]/"docs/v4-benchmark.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print("Saved", out)
    del app


if __name__ == "__main__":
    main()
