"""Shape-following brushwork: sketch, nested curved fills, final small contours."""
import math

import cv2
import numpy as np

from app.models import Stroke


def shape_strokes(mask, color, widths, size, scale, cancel):
    sx, sy = scale
    ratio = min(sx, sy)
    w, h = size
    output = []
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    regions = sorted(range(1, count), key=lambda i: -int(stats[i, cv2.CC_STAT_AREA]))

    def stroke(contour, brush, priority, closed=True):
        # A closed contour follows the object's shape, including the boundaries of holes.
        line = cv2.approxPolyDP(contour, .35, closed).reshape(-1, 2)
        if not len(line) or (len(line) < 2 and priority != 1):
            return
        if closed or len(line) == 1:
            line = np.vstack([line, line[0]])
        margin = brush/2+1
        points = tuple((float(np.clip(((x+left)/sx-margin)/(w-1-2*margin), 0, 1)),
                        float(np.clip(((y+top)/sy-margin)/(h-1-2*margin), 0, 1))) for x, y in line)
        output.append(Stroke(points, color, brush, priority=priority))

    for region in regions:
        if cancel.is_set():
            raise InterruptedError("Обработка отменена")
        left, top, region_w, region_h = stats[region, :4]
        component = (labels[top:top+region_h, left:left+region_w] == region).astype(np.uint8)*255
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
            step = max(1, math.floor(brush*ratio*.65))
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
