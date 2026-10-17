import threading

import cv2
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


def test_shape_brushwork_preserves_holes_and_uses_curved_closed_paths():
    source = Image.new("RGB", (180, 180), "white")
    draw = ImageDraw.Draw(source)
    draw.ellipse((15, 15, 165, 165), fill=(20, 20, 28))
    draw.ellipse((65, 65, 115, 115), fill="white")
    plan, _ = build_plan(source, PlanOptions((360, 360), time_limit=None,
                                            palette=[(255, 255, 255), (20, 20, 28)]))
    actual = np.asarray(render_plan(plan))
    expected = np.asarray(source.resize((360, 360), Image.Resampling.NEAREST))
    assert np.mean(np.max(np.abs(actual.astype(float)-expected), axis=2) < 30) > .95
    interior = cv2.erode((expected[:, :, 0] < 30).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    assert np.all(np.max(actual[interior], axis=1) < 30), "Unpainted gaps inside a solid shape"
    assert render_plan(plan).getpixel((180, 180)) == (255, 255, 255)
    fills = [s for s in plan.strokes if s.priority == 1]
    assert fills and any(s.points[0] == s.points[-1] for s in fills)
    assert any(len(s.points) > 8 and len({p[1] for p in s.points}) > 8 for s in fills)
    stages = [s.priority for s in plan.strokes]
    assert stages == sorted(stages) and set(stages) == {0, 1, 2}


def test_scanline_mode_is_still_available_explicitly():
    plan, _ = build_plan(artwork(), PlanOptions((180, 180), time_limit=None, stroke_style="Scanline"))
    assert any("Построчное" in note for note in plan.notes)
    assert render_plan(plan).getpixel((90, 90)) == (20, 20, 28)


def test_small_adaptive_palette_keeps_dark_and_colored_regions_distinct():
    from app.planner import _quantize
    image = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 40, 90), fill=(0, 0, 0))
    draw.rectangle((45, 10, 70, 90), fill=(20, 160, 220))
    draw.rectangle((75, 10, 95, 90), fill=(240, 190, 160))
    labels, palette = _quantize(image, None, 8)
    assert palette[labels[50, 20]] == (0, 0, 0)
    assert palette[labels[50, 50]] == (20, 160, 220)
    assert palette[labels[0, 0]] == (255, 255, 255)
