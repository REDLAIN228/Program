"""Count paint that lands outside the source silhouette, per Human stage.

"Halo" = planned pixels that differ from white where the prepared source is
white (background). Run: python tools/halo_check.py
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image, ImageDraw

from app.human import STAGES
from app.imaging import prepare
from app.planner import PlanOptions, build_plan, render_plan


def portrait(size=240):
    image = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(image)
    d.ellipse((30, 20, 210, 230), fill=(20, 20, 28))
    d.ellipse((50, 50, 190, 210), fill=(244, 190, 168))
    d.ellipse((80, 100, 105, 130), fill=(20, 20, 28))
    d.ellipse((135, 100, 160, 130), fill=(20, 20, 28))
    return image


def halo(source, canvas=512, widths=(3, 9, 18), mode="BALANCED"):
    from benchmark_v2 import fixtures, image_metrics
    plan, _ = build_plan(source, PlanOptions((canvas, canvas), style="Custom", engine="Human 3.0", human_mode=mode,
                                             time_limit=None, brush_widths=widths, detect_faces=False))
    expected = np.asarray(prepare(source, (canvas, canvas), style="Custom"), np.int16)
    background = np.min(expected, axis=2) >= 245
    result = dict(strokes=len(plan.strokes), total_outside=0, stages={})
    rendered = np.asarray(render_plan(plan), np.int16)
    painted = np.max(np.abs(rendered-255), axis=2) > 30
    result["total_outside"] = int(np.count_nonzero(painted & background))
    result["outside_fraction_of_background"] = round(float(np.mean(painted[background])), 5)
    agreement = np.max(np.abs(rendered-expected), axis=2) < 30
    result["pixel_agreement"] = round(float(np.mean(agreement)), 4)
    for stage, name in enumerate(STAGES):
        subset = [s for s in plan.strokes if s.stage == stage]
        if not subset:
            continue
        layer = np.asarray(render_plan(replace(plan, strokes=subset)), np.int16)
        mark = np.max(np.abs(layer-255), axis=2) > 30
        result["stages"][name] = dict(strokes=len(subset), outside=int(np.count_nonzero(mark & background)))
    return result


def main():
    from benchmark_v2 import fixtures
    report = {"portrait-512": halo(portrait())}
    for name, image in fixtures().items():
        report[name+"-128"] = halo(image, 128)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
