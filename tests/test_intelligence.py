from dataclasses import replace
import threading

import cv2
import numpy as np
from PIL import Image, ImageDraw
import pytest

from app.models import Plan, Stroke, Timing, estimate_plan
from app.planner import PlanOptions, build_plan, render_plan
from app.priority import analyze, project_regions, heatmap
from app.smart_timer import DrawingClock, fit_budget, learned_factor
from app.vector import refine, optimize, merge_compatible


def portrait():
    image = Image.new("RGB", (160, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((20, 12, 140, 146), fill=(30, 30, 35))
    draw.ellipse((31, 33, 129, 135), fill=(245, 195, 160))
    draw.ellipse((48, 61, 65, 81), fill=(10, 10, 15))
    draw.ellipse((94, 61, 111, 81), fill=(10, 10, 15))
    draw.arc((65, 95, 95, 115), 0, 180, fill=(10, 10, 15), width=2)
    return image


def test_manual_priority_can_raise_and_lower_and_works_without_faces():
    image = portrait()
    result = analyze(image, "Portrait", False, ((.25, .3, .5, .3, 100), (0., 0., .12, .12, 0)))
    assert result.scores[70, 80] == 100
    assert result.scores[5, 5] == 0
    assert result.scores.min() >= 0 and result.scores.max() <= 100
    assert "эвристика" in result.method and "выключен" in result.method
    assert heatmap(image, result.scores).size == image.size
    logo = Image.new("RGB", (120, 80), "white")
    ImageDraw.Draw(logo).text((20, 30), "ANIME", fill="black")
    assert np.ptp(analyze(logo, "Auto", False).scores) > 10


def test_priority_rectangles_follow_letterbox_and_center_crop():
    assert project_regions(((0, 0, 1, 1, 100),), (200, 100), (100, 100)) == ((0., .25, 1., .5, 100),)
    assert project_regions(((0, 0, .1, 1, 100),), (200, 100), (100, 100), crop=True) == ()


def test_optional_bundled_cpu_models_load_without_a_download():
    result = analyze(portrait(), "Full Character", True)
    assert "HOG/SVM" in result.method
    assert "OpenCV Haar" in result.method
    assert result.scores.shape == (160, 160)


def test_bezier_refinement_preserves_sharp_corners_and_adapts_point_density():
    straight = np.array([(x, .01*np.sin(x)) for x in range(50)], np.float32)
    assert len(refine(straight, .6)) == 2
    corner = np.array([(0, 0), (20, 0), (20, 20)], np.float32)
    assert np.any(np.all(refine(corner, .5) == (20, 0), axis=1))
    curve = np.array([(x, .04*x*x) for x in range(30)], np.float32)
    sampled = refine(curve, .5)
    # Every Bézier sample stays close to the source curve, including the ends.
    assert np.allclose(sampled[0], curve[0]) and np.allclose(sampled[-1], curve[-1])
    assert max(np.min(np.linalg.norm(curve-point, axis=1)) for point in sampled) < 2


def test_layer_optimizer_never_swaps_overlapping_colors_or_joins_disconnected_lines():
    strokes = [Stroke(((.1, .1), (.9, .9)), (10, 10, 10), 3, priority=1),
               Stroke(((.9, .1), (.1, .9)), (240, 40, 40), 3, priority=1),
               Stroke(((.02, .02), (.03, .02)), (10, 10, 10), 3, priority=1)]
    output, _ = optimize(strokes, (100, 100), np.full((100, 100), 50), "Ultra", 100, threading.Event())
    first = next(i for i, s in enumerate(output) if s.color == (10, 10, 10) and s.length((100, 100)) > 30)
    second = next(i for i, s in enumerate(output) if s.color == (240, 40, 40))
    assert first < second
    assert len(output) == 3
    assert any(s.length((100, 100)) < 5 for s in output)


def test_vector_pipeline_preserves_eyes_holes_and_uses_only_calibrated_widths():
    source = portrait()
    options = PlanOptions((160, 160), quality="Full HD", time_limit=None, engine="Vector 2.0",
                          brush_widths=(1, 3, 9, 18), detect_faces=False, style="Custom",
                          priority_regions=((.25, .3, .5, .3, 100),), vector_accuracy="Precision")
    plan, processed = build_plan(source, options)
    result = render_plan(plan)
    assert max(result.getpixel((56, 70))) < 40
    assert max(result.getpixel((102, 70))) < 40
    assert min(result.getpixel((80, 80))) > 100
    assert result.getpixel((4, 4)) == (255, 255, 255)
    assert {s.width for s in plan.strokes} <= {1, 3, 9, 18}
    assert max(s.importance for s in plan.strokes) == 100
    assert plan.analysis["method"] and plan.engine == "Vector 2.0"
    assert Plan.from_dict(plan.to_dict()).strokes == plan.strokes
    cancel = threading.Event(); cancel.set()
    with pytest.raises(InterruptedError):
        build_plan(source, options, cancel=cancel)


def test_compatible_merge_requires_a_color_safe_connector_even_across_tiny_gaps():
    strokes = [Stroke(((.2, .5), (.46, .5)), (0, 0, 0), 3, priority=1),
               Stroke(((.54, .5), (.8, .5)), (0, 0, 0), 3, priority=1)]
    labels = np.zeros((100, 100), np.uint8)
    palette = [(0, 0, 0), (255, 255, 255)]
    assert len(merge_compatible(strokes, labels, palette, (100, 100), threading.Event())) == 1
    labels[:, 49:53] = 1
    assert len(merge_compatible(strokes, labels, palette, (100, 100), threading.Event())) == 2


def test_smart_budget_retains_critical_contours_and_rejects_impossible_deadline():
    important = Stroke(((.4, .4), (.6, .4)), (0, 0, 0), 1, priority=2, importance=100)
    background = [Stroke(((.1, y/100), (.9, y/100)), (0, 0, 0), 1, priority=3, importance=10)
                  for y in range(10, 90)]
    strokes = [important]+background
    timing = Timing.preset("Normal")
    plan = Plan((160, 160), strokes, timing, estimate_plan(strokes, (160, 160), timing),
                "x", [(0, 0, 0)], safety_buffer=1, smart_finish=True)
    fitted = fit_budget(plan, 3)
    assert important in fitted.strokes and len(fitted.strokes) < len(strokes)
    assert fitted.estimated_seconds <= 2
    impossible = fit_budget(replace(plan, notes=[], metrics={}), .001)
    assert impossible.strokes == strokes and impossible.metrics["budget_feasible"] is False


def test_budget_does_not_remove_only_the_inner_half_of_a_fill_component():
    strokes = [Stroke(((.2, .2), (.8, .2)), (0, 0, 0), 9, priority=1, importance=30, component_id=7),
               Stroke(((.2, .3), (.8, .3)), (0, 0, 0), 9, priority=1, importance=30, component_id=7),
               Stroke(((.4, .4), (.6, .4)), (0, 0, 0), 1, priority=2, importance=100)]
    timing = Timing.preset("Normal")
    plan = Plan((160, 160), strokes, timing, estimate_plan(strokes, (160, 160), timing), "x", [], smart_finish=True)
    result = fit_budget(plan, .9)
    assert strokes[2] in result.strokes
    assert (strokes[0] in result.strokes) == (strokes[1] in result.strokes)


def test_monotonic_round_deadline_is_not_extended_by_pause_and_measurements_are_scoped():
    now = [100.]
    clock = DrawingClock(30, lambda: now[0])
    now[0] += 5; clock.pause()
    now[0] += 10
    assert clock.snapshot() == dict(elapsed=15., active=5., paused=10., remaining=15.)
    clock.resume(); now[0] += 20
    assert clock.snapshot()["remaining"] == 0 and clock.snapshot()["active"] == 25
    assert learned_factor([], "roblox") == (1., 0)
    records = [dict(key="roblox", actual=12, predicted=10, strokes=4),
               dict(key="local", actual=1000, predicted=10, strokes=4)]
    assert learned_factor(records, "roblox") == (1.2, 1)
