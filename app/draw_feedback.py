"""Check visible ink rather than assuming accepted input reached the game."""
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from app.models import Rect


@dataclass
class InkProbe:
    region: Rect
    before: np.ndarray
    eligible: np.ndarray
    expected: np.ndarray

    @classmethod
    def capture(cls, capture, points, color, width, opacity, canvas):
        padding = max(2, (width+1)//2+1)
        left = max(canvas.x, min(x for x, _ in points)-padding)
        top = max(canvas.y, min(y for _, y in points)-padding)
        right = min(canvas.x+canvas.width, max(x for x, _ in points)+padding+1)
        bottom = min(canvas.y+canvas.height, max(y for _, y in points)+padding+1)
        region = Rect(left, top, right-left, bottom-top)
        before = np.asarray(capture(region).convert("RGB"), dtype=np.float32)
        mask = Image.new("L", (region.width, region.height))
        draw = ImageDraw.Draw(mask)
        path = [(x-left, y-top) for x, y in points]
        # Probe the inner part of the brush; game edge antialiasing can differ.
        draw.line(path, fill=255, width=max(1, width//2))
        # The in-game brush cursor is part of a screenshot too. Its old/new
        # outlines must not count as proof that the game actually painted.
        radius = width/2+4
        for x, y in (path[0], path[-1]):
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=0)
        expected = before*(1-opacity)+np.asarray(color)*opacity
        eligible = (np.asarray(mask) > 0) & (np.max(np.abs(before-expected), axis=2) >= 30)
        if np.count_nonzero(eligible) < 6:
            return None  # Already matching ink, tiny dots or faint strokes are inconclusive.
        return cls(region, before, eligible, expected)

    def visible(self, image):
        after = np.asarray(image.convert("RGB"), dtype=np.float32)
        old_distance = np.max(np.abs(self.before-self.expected), axis=2)
        new_distance = np.max(np.abs(after-self.expected), axis=2)
        towards_ink = (old_distance-new_distance >= 12) & (new_distance <= 60)
        return np.count_nonzero(towards_ink & self.eligible) >= max(3, .35*np.count_nonzero(self.eligible))
