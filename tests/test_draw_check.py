import json

from PIL import Image, ImageDraw

from app.automation import WindowState
from app.draw_check import inspect_test
from app.game_profile import screenshot_profile
from app.models import Plan, Rect, Stroke, Timing
from app.planner import render_plan


def captures():
    state = WindowState(1, "Roblox", "Game", "RobloxPlayerBeta.exe", Rect(0, 0, 1366, 768), 96)
    profile = screenshot_profile(state)
    strokes = [Stroke(((.42, y), (.58, y)), color, width)
               for y, color, width in [(.47, (0, 0, 0), 1), (.5, (255, 0, 0), 2), (.53, (0, 255, 0), 1)]]
    plan = Plan((555, 555), strokes, Timing(), 1, "test", [])
    before = Image.new("RGB", (1366, 768), "white")
    after = before.copy()
    after.paste(render_plan(plan), (profile.canvas.x, profile.canvas.y))
    return profile, plan, before, after


def test_exact_test_lines_are_accepted_and_diagnostics_contain_only_canvas(tmp_path):
    profile, plan, before, after = captures()
    report = inspect_test(before, after, profile, plan, tmp_path)
    assert report["status"] == "geometry_ok" and report["outside_pixels"] == 0
    assert Image.open(tmp_path/"test-draw-after.png").size == (555, 555)
    assert json.loads((tmp_path/"test-draw.json").read_text())["requested_widths"] == [1, 2, 1]


def test_thick_brush_and_connector_tails_are_not_hidden_by_test_tolerance(tmp_path):
    profile, plan, before, after = captures()
    for name, width, endpoint in [("fat", 40, (.58, .5)), ("tail", 2, (.9, .9))]:
        broken = after.copy()
        r = profile.canvas
        ImageDraw.Draw(broken).line([r.map((.42, .5), 2), r.map(endpoint, 2)], fill="red", width=width)
        report = inspect_test(before, broken, profile, plan, tmp_path/name)
        assert report["status"] == "outside" and report["outside_pixels"] > 12


def test_empty_test_canvas_is_not_reported_as_success(tmp_path):
    profile, plan, before, _ = captures()
    assert inspect_test(before, before, profile, plan, tmp_path)["status"] == "empty"
