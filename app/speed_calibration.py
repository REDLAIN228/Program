"""Measured acceptance of long mouse strokes on the actual selected canvas."""
from dataclasses import replace
import hashlib
import json

import numpy as np
from PIL import Image, ImageDraw

from app.models import Plan, Stroke, Timing, estimate_plan

CANDIDATES = ("Safe", "Normal", "Rapid · 9", "Sprint · 10")
# 2: waits are precise on Windows (app.precise_wait). Earlier acceptance was
# measured while every short wait lasted ~15.6 ms, i.e. at a slower real speed.
TIMING_MODEL = 2


def profile_key(profile):
    data = profile.to_dict()
    data.pop("verified", None)
    data.pop("name", None)
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:24]


def calibration_plan(profile, game_delay=.25):
    color = (0, 0, 0) if profile.dynamic_color else min(profile.swatches, key=lambda s: sum(s.rgb)).rgb
    brush = min(b.pixels for b in profile.brushes)
    size = profile.canvas.width, profile.canvas.height
    strokes = []
    for index, speed in enumerate(CANDIDATES):
        y = .22+index*.18
        points = ((.12, y), (.32, y), (.46, y+.035), (.65, y-.025), (.86, y))
        strokes.append(Stroke(points, color, brush, kind="contour", stage=5))
    timing = replace(Timing.preset("Safe"), game_delay=game_delay)
    plan = Plan(size, strokes, timing, estimate_plan(strokes, size, timing), "speed-calibration", [color])
    plan.analysis["speed_calibration"] = list(CANDIDATES)
    return plan


def inspect_calibration(before, after, profile, plan, durations=()):
    from app.raster import pixel_points
    r = profile.canvas
    image = np.asarray(after.convert("RGB").crop((r.x, r.y, r.x+r.width, r.y+r.height)), dtype=np.int16)
    samples = []
    allowed = Image.new("L", (r.width, r.height))
    for index, stroke in enumerate(plan.strokes):
        expected = Image.new("L", (r.width, r.height))
        points = pixel_points(stroke, plan.canvas_size, expected.size)
        ImageDraw.Draw(expected).line(points, fill=255, width=1)
        target = np.asarray(expected) > 0
        matching = np.max(np.abs(image-np.asarray(stroke.color)), axis=2) < 65
        coverage = float(np.mean(matching[target])) if np.any(target) else 0.
        ImageDraw.Draw(allowed).line(points, fill=255, width=stroke.width+8)
        samples.append(dict(speed=CANDIDATES[index], coverage=coverage, accepted=coverage >= .88,
                            seconds=durations[index] if index < len(durations) else None))
    original = np.asarray(before.convert("RGB").crop((r.x, r.y, r.x+r.width, r.y+r.height)), np.int16)
    changed = np.max(np.abs(image-original), axis=2) > 20
    stray = int(np.count_nonzero(changed & (np.asarray(allowed) == 0)))
    geometry_ok = stray <= max(12, int(changed.sum())*.04)
    accepted = [row["speed"] for row in samples if row["accepted"] and geometry_ok]
    # Require the baseline to work too; a lone fast-looking trace is not enough.
    recommendation = accepted[-1] if accepted and samples[0]["accepted"] else None
    return dict(samples=samples, geometry_ok=geometry_ok, outside_pixels=stray,
                recommended_speed=recommendation, profile=profile_key(profile), timing_model=TIMING_MODEL,
                scope="Actual screenshot acceptance of these four strokes; not a universal game guarantee")
