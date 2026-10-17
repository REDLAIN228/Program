import threading

import numpy as np
from PIL import Image, ImageDraw
import pytest

from app.models import estimate_plan
from app.planner import PlanOptions, build_plan, rdp, render_plan


def artwork():
    image = Image.new("RGB", (180, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, 150, 150), fill=(240, 54, 82))
    draw.rectangle((60, 60, 120, 120), fill=(20, 20, 28))
    return image


def test_stroke_plan_reproduces_regions_without_per_pixel_moves(tmp_path):
    options = PlanOptions((360, 360), palette=[(255, 255, 255), (240, 54, 82), (20, 20, 28)],
                          time_limit=None, brush_widths=(3, 9, 18))
    progress = []
    plan, processed = build_plan(artwork(), options, lambda p, _: progress.append(p))
    result = render_plan(plan)
    assert result.getpixel((90, 90)) == (240, 54, 82)
    assert result.getpixel((180, 180)) == (20, 20, 28)
    assert result.getpixel((5, 5)) == (255, 255, 255)
    expected = np.asarray(artwork().resize((360, 360), Image.Resampling.NEAREST))
    actual = np.asarray(result)
    agreement = np.mean(np.max(np.abs(actual.astype(float) - expected), axis=2) < 30)
    assert agreement > .91
    assert len(plan.strokes) < 1000
    assert len(plan.strokes) < 360 * 360 / 100
    assert {s.width for s in plan.strokes} <= {3, 9, 18}
    assert all(len(s.points) >= 2 for s in plan.strokes)
    assert any(s.priority == 1 for s in plan.strokes)
    assert progress[-1] == 1
    assert progress == sorted(progress)
    assert plan.estimated_seconds == estimate_plan(plan.strokes, (360, 360), plan.timing)
    from app.storage import Store
    store = Store(tmp_path)
    assert store.load_plan(store.save_plan(plan)).strokes == plan.strokes


def test_white_image_is_empty_and_budget_limit_is_honest():
    white, _ = build_plan(Image.new("RGB", (100, 100), "white"), PlanOptions())
    assert white.strokes == []
    plan, _ = build_plan(artwork(), PlanOptions(time_limit=.001))
    assert plan.estimated_seconds > .001
    assert any("превышает лимит" in note for note in plan.notes)


def test_cancel_is_observed():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        build_plan(artwork(), PlanOptions(), cancel=cancel)


def test_rdp_preserves_corners():
    points = np.array([(0, 0), (1, .01), (2, 0), (3, 0), (3, 3)], np.float32)
    simplified = rdp(points, .1)
    assert len(simplified) == 3
    assert np.allclose(simplified, [(0, 0), (3, 0), (3, 3)])
