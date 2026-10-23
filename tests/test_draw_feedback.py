from PIL import Image, ImageDraw
import pytest

from app.draw_feedback import InkProbe
from app.models import Rect


CANVAS = Rect(10, 20, 200, 160)
POINTS = [(30, 60), (190, 60)]


def probe_for(image, color=(20, 20, 28), width=3, opacity=1):
    return InkProbe.capture(lambda r: image.crop((r.x, r.y, r.x+r.width, r.y+r.height)),
                            POINTS, color, width, opacity, CANVAS)


def crop(image, probe):
    r = probe.region
    return image.crop((r.x, r.y, r.x+r.width, r.y+r.height))


def test_unchanged_canvas_or_wrong_color_does_not_prove_ink():
    image = Image.new("RGB", (240, 200), "white")
    probe = probe_for(image)
    assert not probe.visible(crop(image, probe))
    ImageDraw.Draw(image).line(POINTS, fill=(255, 0, 0), width=3)
    assert not probe.visible(crop(image, probe))


@pytest.mark.parametrize("width,opacity", [(1, 1), (3, 1), (16, 1), (3, .5)])
def test_visible_stroke_including_transparency_passes(width, opacity):
    image = Image.new("RGB", (240, 200), "white")
    probe = probe_for(image, width=width, opacity=opacity)
    color = tuple(round(255*(1-opacity)+c*opacity) for c in (20, 20, 28))
    ImageDraw.Draw(image).line(POINTS, fill=color, width=width)
    assert probe.visible(crop(image, probe))


def test_cursor_motion_and_whole_screen_dimming_are_not_ink():
    image = Image.new("RGB", (240, 200), "white")
    probe = probe_for(image)
    ImageDraw.Draw(image).ellipse((185, 55, 195, 65), outline=(20, 20, 28))
    assert not probe.visible(crop(image, probe))
    assert not probe.visible(Image.new("RGB", (probe.region.width, probe.region.height), (120, 120, 120)))


def test_existing_ink_tiny_dots_and_faint_strokes_are_inconclusive():
    image = Image.new("RGB", (240, 200), (20, 20, 28))
    assert probe_for(image) is None
    image = Image.new("RGB", (240, 200), "white")
    assert probe_for(image, opacity=.01) is None
    assert InkProbe.capture(lambda r: image.crop((r.x, r.y, r.x+r.width, r.y+r.height)),
                            [(50, 50)], (0, 0, 0), 1, 1, CANVAS) is None


def test_probe_never_captures_outside_calibrated_canvas():
    regions = []
    def capture(r):
        regions.append(r)
        assert CANVAS.contains(r.x, r.y) and CANVAS.contains(r.x+r.width-1, r.y+r.height-1)
        return Image.new("RGB", (r.width, r.height), "white")
    assert InkProbe.capture(capture, [(11, 21), (208, 178)], (0, 0, 0), 16, 1, CANVAS)
    assert len(regions) == 1
