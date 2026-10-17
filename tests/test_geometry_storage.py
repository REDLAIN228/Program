from dataclasses import replace

import pytest
from PIL import Image

from app.imaging import open_image, prepare
from app.models import Calibration, Plan, Rect, Stroke, Timing
from app.storage import Store


def test_mapping_insets_brush_and_supports_negative_monitor_origin():
    rect = Rect(-400, 50, 200, 100)
    assert rect.map((0, 0), 5) == (-395, 55)
    assert rect.map((1, 1), 5) == (-206, 144)
    assert rect.map((.5, .5), 5) == (-300, 100)


@pytest.mark.parametrize("point", [(-.1, 0), (1.1, .5), (float("nan"), 0), (0, float("inf"))])
def test_mapping_rejects_unsafe_points(point):
    with pytest.raises(ValueError):
        Rect(0, 0, 100, 100).map(point)


def test_profile_roundtrip_and_bounds(profile):
    assert Calibration.from_dict(profile.to_dict()).to_dict() == profile.to_dict()
    with pytest.raises(ValueError):
        replace(profile, canvas=Rect(390, 390, 80, 80)).validate()
    with pytest.raises(ValueError):
        replace(profile, swatches=[]).validate()


def test_store_atomic_profiles_plans_and_history(tmp_path, profile):
    store = Store(tmp_path)
    store.save_profile(profile)
    profile.name = "second"
    store.save_profile(profile)
    assert set(store.profiles()) == {"test", "second"}
    plan = Plan((300, 280), [Stroke(((0., 0.), (1., 1.)), (20, 20, 28), 3)],
                Timing(), 1, "abc123", [(20, 20, 28)])
    loaded = store.load_plan(store.save_plan(plan))
    assert loaded.strokes == plan.strokes
    assert loaded.estimated_seconds > 0
    store.record("draw", {"completed": 1})
    assert '"completed": 1' in (tmp_path / "history.json").read_text()
    assert not list(tmp_path.glob(".saving-*"))
    with pytest.raises(ValueError):
        store.save_settings({"api_key": "never-store-this"})


def test_plan_rejects_nonfinite_timing_and_unsafe_strokes():
    plan = Plan((300, 280), [Stroke(((0., 0.), (1., 1.)), (20, 20, 28), 3)],
                Timing(), 1, "a", [(20, 20, 28)]).to_dict()
    plan["timing"]["event"] = -1
    with pytest.raises(ValueError):
        Plan.from_dict(plan)
    plan["timing"]["event"] = .01
    plan["strokes"][0]["points"] = [(2, .5)]
    with pytest.raises(ValueError):
        Plan.from_dict(plan)


def test_letterbox_is_white_and_alpha_is_composited():
    image = Image.new("RGBA", (100, 50), (255, 0, 0, 255))
    prepared = prepare(image, (100, 100))
    assert prepared.getpixel((50, 2)) == (255, 255, 255)
    assert prepared.getpixel((50, 50)) == (255, 0, 0)
    blank = prepare(Image.new("RGBA", (50, 50), (0, 0, 0, 0)), (50, 50))
    assert blank.getpixel((25, 25)) == (255, 255, 255)


@pytest.mark.parametrize("extension", ["png", "jpg", "webp"])
def test_image_import_formats(tmp_path, extension):
    path = tmp_path / ("sample." + extension)
    Image.new("RGB", (32, 48), "red").save(path)
    assert open_image(str(path)).size == (32, 48)
