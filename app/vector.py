"""Bounded-error vector refinement and layer-safe mouse-up path optimization."""
from dataclasses import replace
from collections import deque
import math
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw

from app.models import Rect


ACCURACY = {"Speed": 1.25, "Balanced": .65, "Precision": .30, "Ultra": .12}


def quadratic(a, control, b, tolerance, depth=0):
    """Adaptive de Casteljau sampling: straight portions need only an endpoint."""
    if depth >= 10 or np.linalg.norm(control-(a+b)/2) <= tolerance:
        return [b]
    left, right = (a+control)/2, (control+b)/2
    middle = (left+right)/2
    return quadratic(a, left, middle, tolerance, depth+1)+quadratic(middle, right, b, tolerance, depth+1)


def refine(points, epsilon, closed=False):
    original = np.asarray(points, np.float32)
    if len(original) < 3:
        return original
    line = cv2.approxPolyDP(original.reshape(-1, 1, 2), epsilon*.5, closed).reshape(-1, 2)
    if len(line) < 3:
        return original if closed else line
    if closed:
        line = np.vstack((line, line[0]))
    result = [line[0]]
    for index in range(1, len(line)-1):
        previous, corner, following = line[index-1], line[index], line[index+1]
        incoming, outgoing = corner-previous, following-corner
        l1, l2 = np.linalg.norm(incoming), np.linalg.norm(outgoing)
        if min(l1, l2) < 1e-5:
            continue
        # Preserve sharp intentional corners; round gentle contour turns only.
        cosine = float(np.dot(incoming, outgoing)/(l1*l2))
        if cosine < .15:
            result.append(corner)
            continue
        radius = min(l1*.2, l2*.2, epsilon)
        a, b = corner-incoming/l1*radius, corner+outgoing/l2*radius
        result.append(a)
        result.extend(quadratic(a, corner, b, max(.025, epsilon*.2)))
    result.append(line[-1])
    return np.asarray(result)


def _points(stroke, size):
    frame = Rect(0, 0, *size)
    return np.asarray([frame.map(point, stroke.width/2+1) for point in stroke.points], np.float32)


def _box(stroke, size):
    points = _points(stroke, size)
    padding = stroke.width/2+2
    return (*np.min(points, axis=0)-padding, *np.max(points, axis=0)+padding)


def _overlap(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def path_metrics(strokes, size):
    length = sum(s.length(size) for s in strokes)
    travel = sum(float(np.linalg.norm(_points(a, size)[-1]-_points(b, size)[0]))
                 for a, b in zip(strokes, strokes[1:]))
    return dict(strokes=len(strokes), points=sum(len(s.points) for s in strokes),
                draw_length=length, travel_length=travel)


def optimize(strokes, size, scores, accuracy, intelligence, cancel, timing=None, color_clicks=1, brush_clicks=1):
    started = time.monotonic()
    epsilon = ACCURACY[accuracy]
    height, width = scores.shape
    refined = []
    last_group, seen = None, set()
    max_error = 0.
    for index, stroke in enumerate(strokes):
        if index % 64 == 0 and cancel.is_set():
            raise InterruptedError("Векторизация отменена")
        points = _points(stroke, size)
        xx = np.clip(np.rint(points[:, 0]*width/size[0]).astype(int), 0, width-1)
        yy = np.clip(np.rint(points[:, 1]*height/size[1]).astype(int), 0, height-1)
        importance = float(np.percentile(scores[yy, xx], 80))
        # Important contours retain small errors even in the Speed preset.
        tolerance = epsilon*(1-.75*importance/100*intelligence/100)
        group = (stroke.priority, stroke.color, stroke.width)
        if group != last_group:
            seen.clear()
            last_group = group
        key = tuple(map(tuple, points))
        reverse = key[::-1]
        if key in seen or reverse in seen:
            continue
        seen.add(key)
        # Repair paths are already raster-verified; do not alter their footprint.
        if stroke.priority != 3 and len(points) >= 3:
            adjusted = refine(points, tolerance, stroke.points[0] == stroke.points[-1])
            margin = stroke.width/2+1
            normalized = tuple((float(np.clip((p[0]-margin)/(size[0]-1-2*margin), 0, 1)),
                                float(np.clip((p[1]-margin)/(size[1]-1-2*margin), 0, 1))) for p in adjusted)
            # Bézier subdivision can yield several samples at the same physical
            # Windows pixel. They add input waits without adding any geometry.
            frame = Rect(0, 0, *size)
            distinct, last_pixel = [], None
            for point in normalized:
                pixel = frame.map(point, margin)
                if pixel != last_pixel:
                    distinct.append(point)
                    last_pixel = pixel
            normalized = tuple(distinct) or stroke.points[:1]
            stroke = replace(stroke, points=normalized)
            max_error = max(max_error, tolerance*1.5+math.sqrt(.5))
        refined.append(replace(stroke, importance=importance))

    # A bounded look-ahead avoids quadratic searches over huge drawings. A
    # candidate may pass a different color only when their footprints are disjoint.
    pending = deque(range(len(refined)))
    boxes = [_box(s, size) for s in refined]
    starts = [_points(s, size)[0] for s in refined]
    ends = [_points(s, size)[-1] for s in refined]
    output, cursor = [], np.zeros(2)
    window = []
    while pending or window:
        while pending and len(window) < 24:
            window.append(pending.popleft())
        if len(output) % 128 == 0 and cancel.is_set():
            raise InterruptedError("Оптимизация маршрута отменена")
        candidates = []
        first = window[0]
        for position, idx in enumerate(window):
            if refined[idx].priority != refined[first].priority:
                break
            if any(refined[earlier].color != refined[idx].color and _overlap(boxes[earlier], boxes[idx])
                   for earlier in window[:position]):
                continue
            distance = min(np.linalg.norm(starts[idx]-cursor), np.linalg.norm(ends[idx]-cursor))
            if output and timing is not None:
                switch = (color_clicks if output[-1].color != refined[idx].color else 0)
                switch += brush_clicks if output[-1].width != refined[idx].width else 0
                distance += switch*(2*timing.control_hold+timing.control_settle)*timing.control_speed
            # Critical details win near ties, without moving between paint layers.
            candidates.append((float(distance)+max(0, 85-refined[idx].importance)*.03, position, idx))
        _, position, idx = min(candidates)
        window.pop(position)
        stroke = refined[idx]
        if np.linalg.norm(ends[idx]-cursor) < np.linalg.norm(starts[idx]-cursor):
            stroke = replace(stroke, points=stroke.points[::-1])
            cursor = starts[idx]
        else:
            cursor = ends[idx]
        output.append(stroke)
    return output, dict(process_seconds=time.monotonic()-started, contour_error_bound=max_error,
                        before=path_metrics(strokes, size), after=path_metrics(output, size))


def vector_preview(plan, order=False):
    from app.raster import pixel_points
    factor = min(1, 1400/max(plan.canvas_size))
    size = tuple(max(1, round(n*factor)) for n in plan.canvas_size)
    image = Image.new("RGB", size, "#10151f")
    draw = ImageDraw.Draw(image)
    for index, stroke in enumerate(plan.strokes):
        points = pixel_points(stroke, plan.canvas_size, size)
        t = index/max(1, len(plan.strokes)-1)
        color = (round(70+170*t), round(210-120*t), round(220-50*t)) if order else (235, 77, 111)
        if len(points) > 1:
            draw.line(points, fill=color, width=1)
        if points:
            x, y = points[0]
            draw.ellipse((x-1, y-1, x+1, y+1), fill="white")
    return image


def merge_compatible(strokes, labels, palette, size, cancel):
    """Join nearby marks only when the whole brush stays in their target color.

    Never cross a white hole or another color, never cross a paint stage, and
    never group past an intervening stroke. Existing calibrated widths survive.
    """
    if not strokes:
        return []
    ids = {tuple(color): i for i, color in enumerate(palette)}
    sx, sy = labels.shape[1]/size[0], labels.shape[0]/size[1]
    output = [strokes[0]]
    cached_key, core = None, None
    for index, stroke in enumerate(strokes[1:]):
        if index % 128 == 0 and cancel.is_set():
            raise InterruptedError("Объединение штрихов отменено")
        previous = output[-1]
        same = ((stroke.color, stroke.width, stroke.priority, stroke.component_id) ==
                (previous.color, previous.width, previous.priority, previous.component_id))
        if not same or stroke.priority not in (1, 3) or len(previous.points)+len(stroke.points) > 512:
            output.append(stroke)
            continue
        frame = Rect(0, 0, *size)
        margin = stroke.width/2+1
        a = np.asarray(frame.map(previous.points[-1], margin), np.float32)
        b = np.asarray(frame.map(stroke.points[0], margin), np.float32)
        distance = float(np.linalg.norm(a-b))
        if distance > max(6, stroke.width*4):
            output.append(stroke)
            continue
        key = stroke.color, stroke.width
        if key != cached_key:
            rx, ry = max(1, math.ceil((stroke.width/2+1)*sx)), max(1, math.ceil((stroke.width/2+1)*sy))
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*rx+1, 2*ry+1))
            core = cv2.erode((labels == ids[stroke.color]).astype(np.uint8), kernel,
                             borderType=cv2.BORDER_CONSTANT, borderValue=0)
            cached_key = key
        samples = np.rint(np.linspace(a, b, max(2, math.ceil(distance)+1))*[sx, sy]).astype(int)
        samples[:, 0] = np.clip(samples[:, 0], 0, labels.shape[1]-1)
        samples[:, 1] = np.clip(samples[:, 1], 0, labels.shape[0]-1)
        if np.all(core[samples[:, 1], samples[:, 0]]):
            output[-1] = replace(previous, points=previous.points+stroke.points,
                                  importance=max(previous.importance, stroke.importance))
        else:
            output.append(stroke)
    return output
