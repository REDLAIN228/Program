import json
from pathlib import Path

from PIL import Image

from app.size_ocr import number_field_state, read_size


FIXTURES = Path(__file__).parent/"fixtures"


def test_blue_size_labels_including_fonts_outside_template_training():
    expected = json.loads((FIXTURES/"brush-size-labels.json").read_text())
    sheet = Image.open(FIXTURES/"brush-size-labels.png")
    for index, value in enumerate(expected):
        actual = read_size(sheet.crop((0, index*20, 38, (index+1)*20)))
        # Ambiguity is permitted to stop automation; a confident wrong size is not.
        assert actual in (None, value)
    for index in range(22):  # The separately rendered Noto Sans examples must all read.
        assert read_size(sheet.crop((0, index*20, 38, (index+1)*20))) == expected[index]


def test_missing_gray_and_clipped_readouts_are_rejected():
    assert read_size(Image.new("RGB", (38, 20), "white")) is None
    sheet = Image.open(FIXTURES/"brush-size-labels.png")
    label = sheet.crop((0, 40, 38, 60))
    assert read_size(label.convert("L").convert("RGB")) is None
    # Put the blue text against the edge of the expected readout region.
    a = label.convert("RGB")
    import numpy as np
    pixels = np.asarray(a, int)
    mask = pixels[:, :, 2]-pixels[:, :, 0] > 65
    ys, xs = np.nonzero(mask)
    clipped = a.crop((xs.min(), ys.min(), xs.max()+1, ys.max()+1))
    assert read_size(clipped) is None


def test_zero_leading_zero_and_out_of_range_values_are_rejected():
    sheet = Image.open(FIXTURES/"invalid-brush-size-labels.png")
    for row in range(4):
        assert read_size(sheet.crop((0, row*20, 38, (row+1)*20))) is None


def test_numeric_field_is_only_cleared_when_blank_or_default_zero():
    sheet = Image.open(FIXTURES/"rgb-field-states.png")
    for row, expected in enumerate([True, True, False, False, False, False, False]):
        reading = number_field_state(sheet.crop((0, row*24, 53, (row+1)*24)), dark_text=False)
        assert reading["cleared"] is expected, (row, reading)
    reading = number_field_state(sheet.crop((0, 6*24, 53, 7*24)), dark_text=False)
    assert reading["selected"]  # Highlighted old text is not an empty field.


def test_black_numeric_field_does_not_hide_old_number_or_visible_caret():
    from PIL import ImageDraw
    sheet = Image.open(FIXTURES/"numeric-size-labels.png")
    assert number_field_state(Image.new("RGB", (105, 32), "white"), True)["cleared"]
    for row, expected in enumerate([True, False, False, False, False, False, False]):
        image = sheet.crop((0, row*32, 105, (row+1)*32))
        assert number_field_state(image, True)["cleared"] is expected
    caret = Image.new("RGB", (105, 32), "white")
    ImageDraw.Draw(caret).line((80, 5, 80, 26), fill="black")
    assert not number_field_state(caret, True)["cleared"]
