"""Free-palette (numeric RGB place) plan quality before/after colour merging.

"before" disables merge_close_colors (3.0 behaviour); "after" is 4.0.
Metrics compare the planned Preview with the prepared source; they are not a
Roblox screenshot. Run: python tools/quality_v4.py -> docs/v4-quality.json
"""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import human
from app.imaging import prepare
from app.models import Timing, estimate_plan
from app.planner import PlanOptions, build_plan, render_plan
from app.priority import analyze
from benchmark_v2 import fixtures, image_metrics
from halo_check import portrait


def measure(source, size, mode, merge):
    original = human.MODES[mode]["merge"]
    human.MODES[mode]["merge"] = original if merge else 0
    try:
        started = time.perf_counter()
        plan, _ = build_plan(source, PlanOptions((size, size), style="Custom", engine="Human 3.0", human_mode=mode,
                                                 time_limit=None, brush_widths=(2, 6, 16), detect_faces=False))
        planning = time.perf_counter()-started
    finally:
        human.MODES[mode]["merge"] = original
    expected = prepare(source, (size, size), style="Custom")
    scores = analyze(expected, "Auto", False).scores
    metrics = image_metrics(expected, render_plan(plan), scores)
    return dict(strokes=len(plan.strokes), colors=len(plan.palette), points=sum(len(s.points) for s in plan.strokes),
                planning_seconds=round(planning, 2),
                estimate_turbo7_seconds=round(estimate_plan(plan.strokes, (size, size), Timing.preset("Turbo · 7"), 1, 12), 1),
                pixel_agreement=round(metrics["pixel_agreement"], 4),
                important_agreement=round(metrics["important_agreement"] or 0, 4),
                edge_distance_mean=round(metrics["edge_distance_mean"], 3))


def main():
    cases = {"portrait-512": (portrait(), 512)}
    cases.update({name+"-256": (image, 256) for name, image in fixtures().items()})
    report = dict(scope="Free RGB palette, brushes 2/6/16 px; planned Preview vs prepared source", cases={})
    for name, (image, size) in cases.items():
        for mode in ("FAST", "BALANCED", "MASTERPIECE"):
            row = dict(before=measure(image, size, mode, False), after=measure(image, size, mode, True))
            report["cases"][f"{name} {mode}"] = row
            b, a = row["before"], row["after"]
            print(f"{name:20} {mode:11} strokes {b['strokes']:>4}->{a['strokes']:<4} colors {b['colors']:>2}->{a['colors']:<2} "
                  f"agree {b['pixel_agreement']:.4f}->{a['pixel_agreement']:.4f} "
                  f"important {b['important_agreement']:.3f}->{a['important_agreement']:.3f} "
                  f"edge {b['edge_distance_mean']:.3f}->{a['edge_distance_mean']:.3f} "
                  f"est {b['estimate_turbo7_seconds']}->{a['estimate_turbo7_seconds']}s", flush=True)
    out = Path(__file__).resolve().parents[1]/"docs/v4-quality.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
