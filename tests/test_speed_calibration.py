from dataclasses import replace

from PIL import Image

from app.models import Timing
from app.planner import render_plan
from app.speed_calibration import CANDIDATES, calibration_plan, inspect_calibration, profile_key


def test_long_stroke_acceptance_uses_actual_capture_geometry_and_coverage(profile):
    plan = calibration_plan(profile)
    before = Image.new("RGB", profile.client_size, "white")
    after = before.copy()
    after.paste(render_plan(plan), (profile.canvas.x, profile.canvas.y))
    report = inspect_calibration(before, after, profile, plan, [1., .8, .5, .4])
    assert report["geometry_ok"] and report["recommended_speed"] == CANDIDATES[-1]
    assert all(row["coverage"] > .9 for row in report["samples"])
    empty = inspect_calibration(before, before, profile, plan)
    assert empty["recommended_speed"] is None
    moved = replace(profile, dpi=144)
    assert profile_key(moved) != profile_key(profile)
    moved = replace(profile, verified=False)
    assert profile_key(moved) == profile_key(profile)
    assert Timing.preset("Sprint · 10").control_speed > Timing.preset("Turbo · 7").control_speed
