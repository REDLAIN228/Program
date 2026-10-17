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
