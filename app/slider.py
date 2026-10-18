"""Locate the blue free-slider thumb without assuming its current value."""


def blue_thumb(strip, offset):
    pixels = list(strip.convert("RGB").getdata())
    hits = [i for i, (r, g, b) in enumerate(pixels) if r < 120 and b-r > 100 and b-g > 40]
    groups = []
    for x in hits:
        if not groups or x != groups[-1][-1]+1:
            groups.append([])
        groups[-1].append(x)
    candidates = [g for g in groups if 4 <= len(g) <= 24]
    if len(candidates) != 1:
        return None
    return offset[0]+round((candidates[0][0]+candidates[0][-1])/2), offset[1]


def white_marker(image, offset, allowed=lambda point: True):
    """Find the white core with a dark rim used by the game's HSV selectors."""
    import cv2
    import numpy as np
    a = np.asarray(image.convert("RGB"), np.int16)
    light = ((np.min(a, axis=2) >= 220) & (np.ptp(a, axis=2) < 40)).astype(np.uint8)
    count, labels, stats, centers = cv2.connectedComponentsWithStats(light, 8)
    candidates = []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if not (3 <= area <= 40 and 2 <= w <= 8 and 2 <= h <= 8 and .5 <= w/h <= 2):
            continue
        cx, cy = centers[index]
        point = round(cx)+offset[0], round(cy)+offset[1]
        if not allowed(point):
            continue
        patch = a[max(0, y-3):y+h+3, max(0, x-3):x+w+3]
        if np.count_nonzero(np.max(patch, axis=2) < 80) < 6:
            continue
        candidates.append(point)
    return candidates[0] if len(candidates) == 1 else None
