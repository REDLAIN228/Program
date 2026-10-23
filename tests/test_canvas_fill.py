import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.canvas_fill import MODES, FillSettings, apply_canvas_fill, padding_layout


@pytest.mark.parametrize("mode", MODES)
def test_fill_changes_only_added_padding_and_preserves_real_white_objects(mode):
    source = Image.new("RGB", (80, 120), (35, 65, 95))
    ImageDraw.Draw(source).ellipse((20, 25, 60, 80), fill="white")
    none, mask, _ = apply_canvas_fill(source, (160, 120))
    result, actual_mask, info = apply_canvas_fill(source, (160, 120), dict(mode=mode, text="REDLAIN"))
    original_pixels = np.asarray(mask) == 0
    assert np.array_equal(np.asarray(result)[original_pixels], np.asarray(none)[original_pixels])
    assert np.array_equal(np.asarray(mask), np.asarray(actual_mask))
    assert info["padding_pixels"] == 80*120
    assert result.getpixel((80, 50)) == (255, 255, 255)
    if mode not in ("NONE", "CUSTOM TEXT", "REDLAIN BRANDING", "PATTERN FILL"):
        assert result.getpixel((0, 0)) != (255, 255, 255)


def test_no_padding_or_crop_never_decorates_source():
    source = Image.new("RGB", (80, 80), "white")
    for crop in (False, True):
        result, mask, info = apply_canvas_fill(source, (80, 80), dict(mode="REDLAIN BRANDING"), crop)
        assert not np.any(np.asarray(mask)) and not info["padding_pixels"]
        assert np.all(np.asarray(result) == 255)
    rect, mask = padding_layout((40, 80), (160, 120), True)
    assert (rect.width, rect.height) == (160, 120) and not np.any(np.asarray(mask))


def test_text_location_and_settings_roundtrip_are_real_pixels():
    source = Image.new("RGB", (80, 40), (15, 25, 35))
    settings = FillSettings(mode="CUSTOM TEXT", text="R", x=.2, y=.1, color=(190, 20, 30), font_size=18)
    result, mask, info = apply_canvas_fill(source, (120, 120), settings)
    red = (np.asarray(result)[:, :, 0] > 120) & (np.asarray(result)[:, :, 1] < 80)
    assert np.count_nonzero(red) > 5 and np.all(np.asarray(mask)[red] > 0)
    assert FillSettings.from_dict(settings.to_dict()) == settings
    with pytest.raises(ValueError): FillSettings.from_dict(dict(mode="fake AI outpainting"))
    with pytest.raises(ValueError): FillSettings.from_dict(dict(font_size=999999))
