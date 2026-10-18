"""Shape-following brushwork: sketch, nested curved fills, final small contours."""
import math

import cv2
import numpy as np
from PIL import Image, ImageDraw

from app.models import Rect, Stroke
from app.raster import draw_stroke


def shape_strokes(mask, color, widths, size, scale, cancel, detail_map=None, accuracy="Balanced", intelligence=75):
    sx, sy = scale
    ratio = min(sx, sy)
    w, h = size
    output = []
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    regions = sorted(range(1, count), key=lambda i: -int(stats[i, cv2.CC_STAT_AREA]))

    def stroke(contour, brush, priority, closed=True):
        # A closed contour follows the object's shape, including the boundaries of holes.
        epsilon = .35
        if detail_map is not None:
            raw = contour.reshape(-1, 2)
            xx = np.clip(raw[:, 0]+left, 0, detail_map.shape[1]-1)
            yy = np.clip(raw[:, 1]+top, 0, detail_map.shape[0]-1)
            importance = float(np.percentile(detail_map[yy, xx], 80))
            base = {"Speed": 1.25, "Balanced": .65, "Precision": .25, "Ultra": .08}[accuracy]
            epsilon = max(.02, base*(1-.8*importance/100*intelligence/100)*ratio)
        line = cv2.approxPolyDP(contour, epsilon, closed).reshape(-1, 2)
        if not len(line) or (len(line) < 2 and priority != 1):
            return
        if closed or len(line) == 1:
            line = np.vstack([line, line[0]])
        margin = brush/2+1
        points = tuple((float(np.clip(((x+left)/sx-margin)/(w-1-2*margin), 0, 1)),
                        float(np.clip(((y+top)/sy-margin)/(h-1-2*margin), 0, 1))) for x, y in line)
        output.append(Stroke(points, color, brush, priority=priority, component_id=int(region)))

    for region in regions:
        if cancel.is_set():
            raise InterruptedError("Обработка отменена")
        left, top, region_w, region_h = stats[region, :4]
        component = (labels[top:top+region_h, left:left+region_w] == region).astype(np.uint8)*255
        detail = (float(np.mean(detail_map[top:top+region_h, left:left+region_w][component > 0]))
                  if detail_map is not None else 100.)
        boundary, _ = cv2.findContours(component, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        if stats[region, cv2.CC_STAT_AREA] >= max(40, 20*ratio*ratio):
            for contour in sorted(boundary, key=cv2.contourArea, reverse=True):
                stroke(contour, min(widths), 0)
        covered = np.zeros_like(component)
        for brush in sorted(set(widths), reverse=True):
            radius = max(1, math.ceil(brush*ratio/2))
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius+1, 2*radius+1))
            # Keep previously painted pixels available as safe brush centers. Eroding only
            # the unpainted gaps would discard narrow gaps between two wide brush marks.
            core = cv2.erode(component, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0)
            density = .65
            if detail_map is not None:
                base = {"Speed": .95, "Balanced": .85, "Precision": .75, "Ultra": .65}[accuracy]
                density = base-(base-.65)*detail/100*intelligence/100
            step = max(1, math.floor(brush*ratio*density))
            shrink = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*step+1, 2*step+1))
            coverage_radius = max(0, math.floor(brush*ratio/2-.5))
            footprint = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                   (2*coverage_radius+1, 2*coverage_radius+1))
            while np.any(core):
                if cancel.is_set():
                    raise InterruptedError("Обработка отменена")
                contours, _ = cv2.findContours(core, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
                for contour in sorted(contours, key=cv2.contourArea, reverse=True):
                    remaining = component & ~covered
                    near = cv2.dilate(remaining, footprint) if coverage_radius else remaining
                    points = contour.reshape(-1, 2)
                    needed = near[points[:, 1], points[:, 0]] > 0
                    if not np.any(needed):
                        continue
                    if np.all(needed):
                        arcs = [(points, True)]
                    else:
                        # Cut only at unneeded portions of this curved path. Never close
                        # a partial arc with a chord that might cross a hole or another color.
                        start = int(np.flatnonzero(~needed)[0])
                        points, needed = np.roll(points, -start, axis=0), np.roll(needed, -start)
                        changes = np.diff(np.pad(needed.astype(np.int8), (1, 1)))
                        arcs = [(points[a:b], False) for a, b in
                                zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1))]
                    for arc, closed in arcs:
                        stroke(arc.reshape(-1, 1, 2), brush, 1, closed)
                        traces = np.zeros_like(component)
                        cv2.polylines(traces, [arc], closed, 255, 1)
                        if len(arc) == 1:
                            traces[arc[0, 1], arc[0, 0]] = 255
                        covered |= cv2.dilate(traces, footprint) if coverage_radius else traces
                core = cv2.erode(core, shrink, borderType=cv2.BORDER_CONSTANT, borderValue=0)
        for contour in sorted(boundary, key=cv2.contourArea, reverse=True):
            stroke(contour, min(widths), 2)
    return output


def complete_coverage(strokes, labels, palette, widths, size, cancel):
    """Repair actual emitted brush marks, including tiny islands and thin gaps.

    Follow residual shapes rather than scanning global rows. Never invent an
    uncalibrated brush size or draw outside the executor's inset canvas.
    """
    factor = min(1., 1920/max(size))
    vw, vh = max(1, round(size[0]*factor)), max(1, round(size[1]*factor))
    target = cv2.resize(labels, (vw, vh), interpolation=cv2.INTER_NEAREST)
    raster = Image.new("L", (vw, vh), 255)
    draw = ImageDraw.Draw(raster)
    ids = {}
    for i, color in enumerate(palette):
        ids.setdefault(tuple(color), i)
    for i, stroke in enumerate(strokes):
        if i % 128 == 0 and cancel.is_set():
            raise InterruptedError("Обработка отменена")
        draw_stroke(draw, stroke, size, (vw, vh), ids[stroke.color])
    brush = min(widths)
    margin = brush/2+1
    sx, sy = vw/size[0], vh/size[1]
    frame = Rect(0, 0, *size)
    lo = frame.map((0, 0), margin)
    hi = frame.map((1, 1), margin)
    x0, y0 = round(lo[0]*sx), round(lo[1]*sy)
    x1, y1 = round(hi[0]*sx), round(hi[1]*sy)
    repairs = []
    for color_id in np.unique(target):
        if cancel.is_set():
            raise InterruptedError("Обработка отменена")
        color = tuple(palette[color_id])
        if min(color) >= 248:
            continue
        region = (target == color_id).astype(np.uint8)*255
        missing = region & (np.asarray(raster) != color_id).astype(np.uint8)*255
        if not np.any(missing):
            continue
        if brush == 1 and factor == 1:
            centers = missing
        else:
            radius = max(1, math.ceil(brush*min(sx, sy)/2))
            footprint = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius+1, 2*radius+1))
            centers = cv2.erode(region, footprint, borderType=cv2.BORDER_CONSTANT, borderValue=0)
            centers &= cv2.dilate(missing, footprint)
        centers[:y0] = 0
        centers[y1+1:] = 0
        centers[:, :x0] = 0
        centers[:, x1+1:] = 0
        while np.any(centers):
            if cancel.is_set():
                raise InterruptedError("Обработка отменена")
            contours, _ = cv2.findContours(centers, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                points = contour.reshape(-1, 2)
                points = np.vstack([points, points[0]])
                normalized = tuple((float(np.clip((x/sx-margin)/(size[0]-1-2*margin), 0, 1)),
                                    float(np.clip((y/sy-margin)/(size[1]-1-2*margin), 0, 1)))
                                   for x, y in points)
                stroke = Stroke(normalized, color, brush, priority=3)
                repairs.append(stroke)
                draw_stroke(draw, stroke, size, (vw, vh), int(color_id))
                if len(strokes)+len(repairs) > 100_000:
                    raise ValueError("Слишком много мелких деталей для 100 000 штрихов. Уменьшите кадр или качество.")
            centers = cv2.erode(centers, np.ones((3, 3), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)
    foreground = np.min(np.asarray(palette, np.uint8)[target], axis=2) < 248
    uncovered = foreground & (np.asarray(raster) == 255)
    uncovered[:y0] = False
    uncovered[y1+1:] = False
    uncovered[:, :x0] = False
    uncovered[:, x1+1:] = False
    return repairs, int(uncovered.sum())
