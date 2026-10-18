from PIL import Image, ImageDraw

from app.slider import blue_thumb, white_marker


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


def test_white_hsv_marker_is_found_on_a_dark_square_and_value_strip():
    for size, center in [((90, 91), (80, 75)), ((17, 169), (8, 153))]:
        image = Image.new("RGB", size, (25, 25, 25))
        draw = ImageDraw.Draw(image)
        x, y = center
        draw.ellipse((x-4, y-4, x+4, y+4), fill="black")
        draw.ellipse((x-2, y-2, x+2, y+2), fill="white")
        assert white_marker(image, (600, 120)) == (600+x, 120+y)


def test_marker_detection_rejects_white_background_and_ambiguous_markers():
    image = Image.new("RGB", (90, 90), "white")
    assert white_marker(image, (0, 0)) is None
    draw = ImageDraw.Draw(image)
    for x, y in [(20, 20), (60, 60)]:
        draw.ellipse((x-4, y-4, x+4, y+4), fill="black")
        draw.ellipse((x-2, y-2, x+2, y+2), fill="white")
    assert white_marker(image, (0, 0)) is None
    assert white_marker(image, (0, 0), lambda point: point[0] < 40) == (20, 20)
