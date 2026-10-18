from dataclasses import replace

import numpy as np
import pytest

from app.layout import drawing_rect
from app.models import Plan, Rect, Stroke, Timing
from app.planner import render_plan, render_placement


@pytest.mark.parametrize("format_name,percent,dimensions", [
    ("Весь холст", 100, (555, 555)),
    ("Весь холст", 50, (278, 278)),
    ("Квадрат 1:1", 75, (416, 416)),
    ("Портрет 3:4", 100, (416, 555)),
    ("Альбом 4:3", 100, (555, 416)),
    ("Вертикальный 9:16", 100, (312, 555)),
    ("Широкий 16:9", 100, (555, 312)),
])
def test_formats_fit_and_are_centered_inside_game_canvas(format_name, percent, dimensions):
    area = drawing_rect((555, 555), format_name, percent)
    assert (area.width, area.height) == dimensions
    assert abs(2*area.x+area.width-555) <= 1
    assert abs(2*area.y+area.height-555) <= 1


def test_custom_dimensions_reject_oversized_and_too_small_drawings():
    assert drawing_rect((555, 555), "Свой размер", custom=(200, 300)) == Rect(177, 127, 200, 300)
    for size in [(556, 100), (100, 556), (31, 100)]:
        with pytest.raises(ValueError, match="помещаться"):
            drawing_rect((555, 555), "Свой размер", custom=size)


def test_layout_cache_and_preview_preserve_actual_size_and_white_margins():
    plan = Plan((100, 80), [Stroke(((0., 0.), (1., 1.)), (0, 0, 0), 3)],
                Timing.preset("Turbo · 7"), 1, "test", [(0, 0, 0)],
                drawing_rect=Rect(100, 100, 100, 80), target_canvas_size=(300, 280))
    cached = Plan.from_dict(plan.to_dict())
    assert cached.drawing_area(Rect(80, 100, 300, 280)) == Rect(180, 200, 100, 80)
    assert render_plan(cached).size == (100, 80)  # Export is the chosen size.
    preview = np.asarray(render_placement(cached))
    ys, xs = np.nonzero(np.any(preview < 255, axis=2))
    assert len(xs) > 0 and xs.min() >= 100 and xs.max() < 200
    assert ys.min() >= 100 and ys.max() < 180
    with pytest.raises(ValueError, match="другому"):
        cached.drawing_area(Rect(80, 100, 301, 280))
    for area in [Rect(-1, 100, 100, 80), Rect(250, 100, 100, 80), Rect(100, 100, 101, 80)]:
        with pytest.raises(ValueError):
            Plan.from_dict(replace(plan, drawing_rect=area).to_dict())


def test_four_extra_speed_steps_reduce_motion_time_without_reducing_control_waits():
    names = ["Normal", "Fast", "Turbo · 5", "Turbo · 6", "Turbo · 7"]
    stroke = Stroke(((0., 0.), (1., 1.)), (0, 0, 0), 3)
    times = [stroke.seconds((555, 555), Timing.preset(name)) for name in names]
    assert all(a > b for a, b in zip(times, times[1:]))
    assert Timing.preset(names[-1]).control_speed > Timing.preset(names[0]).control_speed
    assert Timing.preset(names[-1]).control_hold == Timing.preset(names[0]).control_hold
    assert Timing.preset(names[-1]).control_settle == Timing.preset(names[0]).control_settle
