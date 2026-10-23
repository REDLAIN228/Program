from dataclasses import replace
import threading

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.human import STAGES
from app.models import Plan
from app.planner import PlanOptions, build_plan, render_plan


def portrait():
    source = Image.new("RGB", (128, 128), "white")
    draw = ImageDraw.Draw(source)
    draw.ellipse((16, 8, 112, 124), fill=(25, 24, 30))
    draw.ellipse((28, 30, 100, 112), fill=(230, 180, 145))
    draw.ellipse((43, 55, 52, 66), fill=(15, 15, 20))
    draw.ellipse((76, 55, 85, 66), fill=(15, 15, 20))
    draw.arc((48, 72, 80, 98), 0, 180, fill=(80, 20, 35), width=3)
    return source


@pytest.mark.parametrize("mode", ["FAST", "BALANCED", "MASTERPIECE"])
def test_human_plan_has_real_ordered_virtual_layers_and_continuous_brush_paths(mode):
    options = PlanOptions((128, 128), engine="Human 3.0", human_mode=mode, time_limit=None,
                          brush_widths=(1, 3, 9, 18), style="Custom", detect_faces=False)
    plan, processed = build_plan(portrait(), options)
    assert plan.engine == "Human 3.0" and 0 < len(plan.strokes) < 100
    assert [s.stage for s in plan.strokes] == sorted(s.stage for s in plan.strokes)
    assert len(plan.analysis["layers"]) == 7 and set(plan._layer_masks) == set(STAGES)
    assert any(len(s.points) > 12 for s in plan.strokes)
    assert all(s.width in options.brush_widths for s in plan.strokes)
    assert Plan.from_dict(plan.to_dict()).to_dict() == plan.to_dict()
    actual = np.asarray(render_plan(plan))
    assert np.min(actual[58:64, 45:50]) < 80  # Eye survives each mode at supported physical size.
    assert processed.size == (128, 128) and plan.metrics["cost_breakdown"]["mouse_presses"] > 0


def test_mode_work_differs_predictably_and_cancel_is_real():
    plans = [build_plan(portrait(), PlanOptions((128, 128), engine="Human 3.0", human_mode=mode,
             time_limit=None, brush_widths=(1, 3, 9, 18), detect_faces=False))[0]
             for mode in ("FAST", "BALANCED", "MASTERPIECE")]
    assert plans[0].estimated_seconds < plans[-1].estimated_seconds
    assert len(plans[0].palette) <= len(plans[-1].palette)
    event = threading.Event()
    event.set()
    with pytest.raises(InterruptedError):
        build_plan(portrait(), PlanOptions(engine="Human 3.0"), cancel=event)


def test_large_mass_uses_calibrated_wide_continuous_strokes_and_preserves_white_hole():
    source = Image.new("RGB", (160, 160), "white")
    draw = ImageDraw.Draw(source)
    draw.rectangle((12, 12, 148, 148), fill=(40, 100, 150))
    draw.ellipse((58, 58, 102, 102), fill="white")
    plan, _ = build_plan(source, PlanOptions((160, 160), engine="Human 3.0", time_limit=None,
                                           brush_widths=(1, 4, 16, 32), detect_faces=False))
    assert len(plan.strokes) < 50 and any(s.width >= 16 for s in plan.strokes)
    assert sum(s.length(plan.canvas_size) for s in plan.strokes) > 1000
    result = render_plan(plan)
    assert result.getpixel((80, 80)) == (255, 255, 255)
    assert max(abs(a-b) for a, b in zip(result.getpixel((35, 35)), (40, 100, 150))) < 20
