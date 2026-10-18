from pathlib import Path
from dataclasses import replace

import pytest
from PIL import Image

from app.models import Plan, Stroke, Timing
from app.planner import PlanOptions, build_plan, render_plan
from app.size_ocr import read_percent


def test_percent_labels_one_through_one_hundred_and_touching_four():
    sheet = Image.open(Path(__file__).parent/"fixtures"/"opacity-labels.png")
    for value in range(1, 101):
        assert read_percent(sheet.crop((0, (value-1)*21, 46, value*21))) == value


def test_opacity_ocr_rejects_missing_sign_gray_text_and_clipped_labels():
    sheet = Image.open(Path(__file__).parent/"fixtures"/"opacity-labels.png")
    label = sheet.crop((0, 0, 46, 21))
    assert read_percent(label.convert("L").convert("RGB")) is None
    assert read_percent(label.crop((6, 0, 46, 21))) is None
    no_sign = label.copy()
    no_sign.paste("white", (10, 0, 46, 21))
    assert read_percent(no_sign) is None
    assert read_percent(Image.new("RGB", (46, 21), "white")) is None


def test_preview_composites_opacity_and_accumulates_overlapping_strokes():
    stroke = Stroke(((.2, .5), (.8, .5)), (0, 0, 0), 3, opacity=.5)
    plan = Plan((64, 64), [stroke], Timing(), 1, "x", [])
    once = render_plan(plan).getpixel((32, 32))[0]
    twice = render_plan(replace(plan, strokes=[stroke, stroke])).getpixel((32, 32))[0]
    assert 126 <= once <= 128
    assert 62 <= twice <= 65
    assert Plan.from_dict(plan.to_dict()).strokes[0].opacity == .5


@pytest.mark.parametrize("engine", ["Legacy", "Vector 2.0"])
def test_real_plan_preview_uses_requested_opacity_and_game_delay(engine):
    plan, _ = build_plan(Image.new("RGB", (48, 48), (0, 0, 0)),
                         PlanOptions((48, 48), time_limit=None, brush_widths=(1, 6),
                                     opacity=50, game_delay=.35, engine=engine))
    assert plan.strokes and all(stroke.opacity == .5 for stroke in plan.strokes)
    assert plan.timing.game_delay == .35
    assert render_plan(plan).getpixel((24, 24)) != (0, 0, 0)
