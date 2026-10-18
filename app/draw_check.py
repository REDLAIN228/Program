"""Compare real TEST DRAW captures and preserve canvas-only diagnostics."""
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.storage import write_json


def inspect_test(before, after, profile, plan, directory: Path):
    r = profile.canvas
    bounds = (r.x, r.y, r.x+r.width, r.y+r.height)
    before, after = before.convert("RGB").crop(bounds), after.convert("RGB").crop(bounds)
    changed = np.max(np.abs(np.asarray(before, np.int16)-np.asarray(after, np.int16)), axis=2) > 20
    allowed = Image.new("L", before.size)
    from app.planner import render_plan
    expected = render_plan(plan)
    for stroke in plan.strokes:
        points = [(x-r.x, y-r.y) for x, y in
                  (r.map(point, stroke.width/2+1) for point in stroke.points)]
        for image, color, width in [(allowed, 255, stroke.width+6)]:
            draw = ImageDraw.Draw(image)
            draw.line(points, fill=color, width=width)
            radius = width/2
            for x, y in [points[0], points[-1]]:
                draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
    outside = changed & (np.asarray(allowed) == 0)
    count, stray = int(changed.sum()), int(outside.sum())
    report = dict(changed_pixels=count, outside_pixels=stray, total_strokes=len(plan.strokes),
                  requested_widths=[s.width for s in plan.strokes],
                  requested_opacities=[round(s.opacity*100) for s in plan.strokes],
                  requested_colors=[s.color for s in plan.strokes], canvas=asdict(r),
                  status="outside" if stray > max(12, count*.05) else "empty" if count < 3 else "geometry_ok")
    directory.mkdir(parents=True, exist_ok=True)
    overlay = np.asarray(after).copy()
    overlay[changed & ~outside] = (30, 190, 90)
    overlay[outside] = (240, 40, 80)
    for name, image in [("before", before), ("after", after), ("expected", expected),
                        ("difference", Image.fromarray(overlay))]:
        image.save(directory/f"test-draw-{name}.png")
    write_json(directory/"test-draw.json", report)
    return report
