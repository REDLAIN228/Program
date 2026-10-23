"""Real input accounting and explicitly labeled model estimates."""
from dataclasses import asdict
import math
import threading
import time


def estimated_breakdown(plan):
    strokes = plan.strokes
    colors = sum(i == 0 or s.color != strokes[i-1].color for i, s in enumerate(strokes))
    brushes = sum(i == 0 or s.width != strokes[i-1].width for i, s in enumerate(strokes))
    path = sum(s.length(plan.canvas_size) for s in strokes)
    travel = sum(math.dist((a.points[-1][0]*plan.canvas_size[0], a.points[-1][1]*plan.canvas_size[1]),
                          (b.points[0][0]*plan.canvas_size[0], b.points[0][1]*plan.canvas_size[1])) for a, b in zip(strokes, strokes[1:]))
    return dict(scope="estimate, not measured game time", strokes=len(strokes),
                color_changes=colors, brush_changes=brushes, mouse_presses=len(strokes)+colors*plan.color_clicks+brushes*plan.brush_clicks,
                draw_pixels=path, travel_pixels=travel, minimum_motion_seconds=path/plan.timing.pixels_per_second,
                estimated_total_seconds=plan.estimated_seconds)


class InputTelemetry:
    def __init__(self):
        self._lock = threading.Lock()
        self.values = dict(mouse_moves=0, mouse_presses=0, key_presses=0, wait_seconds=0., wait_calls=0,
                           travel_pixels=0., drawing_pixels=0., color_changes=0, brush_changes=0)
        self.last = None

    def add(self, **values):
        with self._lock:
            for key, value in values.items():
                self.values[key] = self.values.get(key, 0)+value

    def movement(self, point, drawing):
        with self._lock:
            if self.last is not None:
                key = "drawing_pixels" if drawing else "travel_pixels"
                self.values[key] += math.dist(self.last, point)
            self.last = point
            self.values["mouse_moves"] += 1

    def snapshot(self):
        with self._lock:
            return dict(self.values)
