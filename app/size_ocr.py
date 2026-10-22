"""Conservative OCR for the small blue 1..256 brush-size label only."""
from functools import lru_cache
from pathlib import Path
from itertools import product

import cv2
import numpy as np


def normalize_digit(mask):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError("Empty glyph")
    glyph = mask[ys.min():ys.max()+1, xs.min():xs.max()+1].astype(np.float32)
    aspect = glyph.shape[1]/glyph.shape[0]
    glyph = cv2.resize(glyph, (16, 24), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(glyph, (3, 3), .6), aspect


@lru_cache(maxsize=1)
def templates():
    path = Path(__file__).resolve().parents[1]/"assets"/"size-digits.npz"
    with np.load(path, allow_pickle=False) as data:
        return data["glyphs"].astype(np.float32)/255, data["labels"], data["aspects"]


def read_size(image):
    a = np.asarray(image.convert("RGB"), dtype=np.int16)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mask = (b > 160) & (b-r > 65) & (b-g > 30)
    return _read_mask(mask, 1, 256)


def read_numeric_size(image):
    """Black digits on the white brush-size text box of the popup preset."""
    a = np.asarray(image.convert("RGB"), dtype=np.int16)
    return _read_mask(np.max(a, axis=2) < 90, 0, 999)


def read_percent(image):
    """Pink opacity label with a required trailing percent sign; never guess."""
    a = np.asarray(image.convert("RGB"), dtype=np.int16)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mask = (r > 170) & (r-g > 70) & (r-b > 15)
    ys, xs = np.nonzero(mask)
    if not len(xs) or min(xs) == 0 or max(xs) == image.width-1 or min(ys) == 0 or max(ys) == image.height-1:
        return None
    crop = mask[ys.min():ys.max()+1, xs.min():xs.max()+1]
    columns = np.any(crop, axis=0)
    changes = np.diff(np.pad(columns.astype(np.int8), (1, 1)))
    starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
    glyphs, labels, aspects = templates()
    if not np.any(labels == 10):
        return None
    # A '4' can touch the percent sign at small font sizes. Test bounded
    # suffix splits against actual percent templates, then require one number.
    height, width = crop.shape
    cuts = set(range(max(2, width-round(height*1.25)), max(3, width-round(height*.4))))
    if len(starts) >= 2:
        cuts.add(int(starts[-1]))
    candidates = set()
    for cut in sorted(cuts):
        if not np.any(crop[:, cut:]):
            continue
        glyph, aspect = normalize_digit(crop[:, cut:])
        distance = np.mean(np.abs(glyphs-glyph), axis=(1, 2))+.08*np.abs(aspects-aspect)
        sign = float(np.min(distance[labels == 10]))
        digit = float(np.min(distance[labels < 10]))
        if sign > .21 or digit-sign < .012:
            continue
        digits = np.pad(crop[:, :cut], ((2, 2), (2, 2)))
        value = _read_mask(digits, 1, 100)
        if value is not None:
            candidates.add(value)
    return candidates.pop() if len(candidates) == 1 else None


def _read_mask(mask, minimum, maximum):
    ys, xs = np.nonzero(mask)
    if len(xs) < 4 or ys.max()-ys.min()+1 < 6:
        return None
    if xs.min() == 0 or ys.min() == 0 or xs.max() == mask.shape[1]-1 or ys.max() == mask.shape[0]-1:
        return None  # A clipped digit must never become a plausible smaller number.
    crop = mask[ys.min():ys.max()+1, xs.min():xs.max()+1]
    columns = np.any(crop, axis=0)
    changes = np.diff(np.pad(columns.astype(np.int8), (1, 1)))
    runs = list(zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)))
    if not 1 <= len(runs) <= 3:
        return None
    glyphs, labels, aspects = templates()
    def classify(left, right):
        part = crop[:, left:right]
        ys, _ = np.nonzero(part)
        if len(ys) < 3 or ys.max()-ys.min()+1 < crop.shape[0]*.65:
            return None
        glyph, aspect = normalize_digit(part)
        distance = np.mean(np.abs(glyphs-glyph), axis=(1, 2))+.08*np.abs(aspects-aspect)
        scores = [float(np.min(distance[labels == digit])) for digit in range(10)]
        ranked = np.argsort(scores)
        best, second = scores[ranked[0]], scores[ranked[1]]
        if best > .23 or second-best < .018:
            return None
        return str(ranked[0]), best

    cache = {}
    def part(left, right):
        if (left, right) not in cache:
            cache[left, right] = classify(left, right)
        return cache[left, right]

    direct = [part(left, right) for left, right in runs]
    if all(direct):
        if direct[0][0] == "0" and (minimum != 0 or len(direct) != 1):
            return None
        value = int("".join(d[0] for d in direct))
        return value if minimum <= value <= maximum else None
    # Bold small text can have touching digits. Try near equal advances, but
    # reject ambiguous segmentations rather than guessing a brush size.
    height, width = crop.shape
    candidates = {}
    for length in (2, 3):
        if not .25 <= width/(length*height) <= 1.05:
            continue
        boundaries = [range(max(2, round(i*width/length)-3), min(width-1, round(i*width/length)+4))
                      for i in range(1, length)]
        for cuts in product(*boundaries):
            points = (0, *cuts, width)
            if any(b-a < 2 for a, b in zip(points, points[1:])):
                continue
            found = [part(a, b) for a, b in zip(points, points[1:])]
            if not all(found) or found[0][0] == "0":
                continue
            value = int("".join(d[0] for d in found))
            if not minimum <= value <= maximum:
                continue
            score = sum(d[1] for d in found)/length
            candidates[value] = min(candidates.get(value, 1.), score)
    ranked = sorted(candidates, key=candidates.get)
    if not ranked or candidates[ranked[0]] > .14:
        return None
    if len(ranked) > 1 and candidates[ranked[1]]-candidates[ranked[0]] < .018:
        return None
    return ranked[0]
