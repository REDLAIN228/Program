import json
from pathlib import Path

from PIL import Image

from app.size_ocr import read_size


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
