from PIL import Image, ImageDraw

from app.slider import blue_thumb


def test_slider_thumb_is_found_at_both_ends_and_middle():
    for center in [10, 75, 140]:
        strip = Image.new("RGB", (151, 1), (230, 240, 255))
        draw = ImageDraw.Draw(strip)
        draw.line((10, 0, center, 0), fill=(140, 190, 255))
        draw.line((center-8, 0, center+8, 0), fill=(50, 150, 255))
        assert blue_thumb(strip, (580, 404)) == (580+center, 404)


def test_missing_or_ambiguous_slider_thumb_is_rejected():
    strip = Image.new("RGB", (151, 1), "white")
    assert blue_thumb(strip, (580, 404)) is None
    draw = ImageDraw.Draw(strip)
    draw.line((20, 0, 35, 0), fill=(50, 150, 255))
    draw.line((90, 0, 105, 0), fill=(50, 150, 255))
    assert blue_thumb(strip, (580, 404)) is None
