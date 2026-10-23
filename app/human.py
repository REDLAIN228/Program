"""CPU painter: region masses → virtual layers → connected brush trajectories.

Segmentation/lighting are image heuristics, not semantic object recognition.
Only calibrated brush sizes and palette colors can be emitted.
"""
from dataclasses import replace
import hashlib
import math
import threading
import time

import cv2
import numpy as np
from PIL import Image

from app.canvas_fill import apply_canvas_fill
from app.imaging import prepare
from app.models import Plan, Stroke, Timing, estimate_plan
from app.priority import analyze, project_regions
from app.raster import composite_stroke

STAGES = ("Background", "Silhouette", "Base Colors", "Shadows", "Highlights", "Outlines", "Fine Details")
MODES = {"FAST": dict(grid=384, colors=12, noise=12, epsilon=.9, detail=20),
         "BALANCED": dict(grid=768, colors=24, noise=5, epsilon=.4, detail=8),
         "MASTERPIECE": dict(grid=1920, colors=64, noise=2, epsilon=.15, detail=2)}


def _cancel(event):
    if event.is_set():
        raise InterruptedError("Планирование отменено")


def _normalized(points, brush, size, scale, origin=(0, 0)):
    margin = brush/2+1
    w, h = size
    return tuple((float(np.clip(((x+origin[0])/scale-margin)/(w-1-2*margin), 0, 1)),
                  float(np.clip(((y+origin[1])/scale-margin)/(h-1-2*margin), 0, 1))) for x, y in points)


def region_paths(mask, color, widths, size, scale, stage, settings, cancel, component=0, importance=50., origin=(0, 0)):
    """Nested shape contours, connected into safe spirals, with adaptive widths.

    Whole useful rings avoid splitting each color mass into hundreds of tiny
    repair arcs. Every connector is checked against the eroded region. Holes
    and differently colored islands cannot be crossed with the mouse down.
    """
    mask = np.pad((mask > 0).astype(np.uint8)*255, 1)
    origin = origin[0]-1, origin[1]-1
    covered = np.zeros_like(mask)
    output = []
    distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    for brush in sorted(set(widths), reverse=True):
        _cancel(cancel)
        physical = max(1, round(brush*scale))
        radius = (physical-1)/2
        safe = (distance > radius).astype(np.uint8)*255
        core = safe.copy()
        step = max(1, math.floor(physical*.82))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*step+1, 2*step+1))
        joined = []
        max_points = 1024

        def flush():
            nonlocal joined
            if not joined:
                return
            points = _normalized(joined, brush, size, scale, origin)
            kind = "underpaint" if stage == 1 else "contour" if stage == 5 else "detail" if stage == 6 else "fill"
            output.append(Stroke(points, tuple(color), brush, priority=2 if stage >= 5 else 1,
                                 importance=importance, component_id=component, stage=stage, kind=kind))
            joined = []

        while np.any(core):
            _cancel(cancel)
            contours, _ = cv2.findContours(core, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for contour in sorted(contours, key=cv2.contourArea, reverse=True):
                trace = cv2.approxPolyDP(contour, min(.45, settings["epsilon"]*scale), True).reshape(-1, 2)
                if not len(trace):
                    continue
                if len(trace) == 1:
                    trace = np.repeat(trace, 2, axis=0)
                stroke_mask = np.zeros_like(mask)
                cv2.polylines(stroke_mask, [trace], True, 255, physical)
                if not np.any(stroke_mask & mask & ~covered):
                    continue
                covered |= stroke_mask
                if joined:
                    distances = np.linalg.norm(trace-np.asarray(joined[-1]), axis=1)
                    closest = int(np.argmin(distances))
                    trace = np.roll(trace, -closest, axis=0)
                    length = float(distances[closest])
                    connector = np.rint(np.linspace(joined[-1], trace[0], max(2, math.ceil(length)+1))).astype(int)
                    safe_join = (length <= max(6, physical*3)
                                 and len(joined)+len(trace) < max_points
                                 and np.all(safe[connector[:, 1], connector[:, 0]]))
                    if not safe_join:
                        flush()
                joined.extend(map(tuple, np.vstack((trace, trace[0]))))
            core = cv2.erode(core, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0)
        flush()
    missing = int(np.count_nonzero(mask & ~covered))
    return output, missing


def refine_coverage(strokes, labels, palette, size, widths, scale, mode, cancel):
    """Bounded shape corrections against the real emitted Pillow brush model.

    OpenCV's even-width polylines can be a pixel wider than the game's preview
    footprint. Repair useful residual *paths*, never an unbounded dot-per-pixel pass.
    """
    from app.raster import draw_stroke
    from PIL import ImageDraw
    limit = {"FAST": 0, "BALANCED": 24, "MASTERPIECE": 256}[mode]
    if not limit or any(stroke.opacity != 1 for stroke in strokes): return [], None
    working_size = labels.shape[1], labels.shape[0]
    raster = Image.new("RGB", working_size, "white")
    for index, stroke in enumerate(strokes):
        if index % 128 == 0: _cancel(cancel)
        composite_stroke(raster, stroke, size, working_size)
    target = np.asarray(palette, np.uint8)[labels]
    brush = min(widths)
    physical = max(1, round(brush*scale))
    radius = max(0, (physical-1)//2)
    footprint = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius+1, 2*radius+1))
    repairs = []
    for iteration in range(2 if mode == "MASTERPIECE" else 1):
        before_count = 0
        for color_id in np.unique(labels):
            _cancel(cancel)
            color = tuple(int(c) for c in palette[color_id])
            if min(color) >= 248: continue
            region = (labels == color_id).astype(np.uint8)*255
            error = np.max(np.abs(np.asarray(raster, np.int16)-target.astype(np.int16)), axis=2) > 30
            missing = region & error.astype(np.uint8)*255
            inset = max(2, math.ceil((brush/2+1)*scale))
            missing[:inset] = missing[-inset:] = 0
            missing[:, :inset] = missing[:, -inset:] = 0
            before_count += int(np.count_nonzero(missing))
            if not np.any(missing): continue
            core = cv2.erode(region, footprint, borderType=cv2.BORDER_CONSTANT, borderValue=0)
            centers = core & cv2.dilate(missing, footprint)
            contours, _ = cv2.findContours(centers, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for contour in sorted(contours, key=cv2.contourArea, reverse=True):
                points = cv2.approxPolyDP(contour, .1, True).reshape(-1, 2)
                if len(points) < 2: continue
                points = np.vstack((points, points[0]))
                if sum(np.linalg.norm(b-a) for a, b in zip(points, points[1:])) < 3:
                    continue
                stroke = Stroke(_normalized(points, brush, size, scale), color, brush, priority=3,
                                importance=85, component_id=1_900_000_000+len(repairs), stage=6, kind="detail")
                draw_stroke(ImageDraw.Draw(raster), stroke, size, working_size, color)
                repairs.append(stroke)
                if len(repairs) >= limit: break
            if len(repairs) >= limit: break
        if len(repairs) >= limit or before_count == 0: break
    remaining = int(np.count_nonzero(np.max(np.abs(np.asarray(raster, np.int16)-target.astype(np.int16)), axis=2) > 30))
    return repairs, remaining


def build_human_plan(image, options, progress=lambda *_: None, cancel=None):
    from app.planner import _quantize
    from app.vector import optimize, path_metrics
    from app.telemetry import estimated_breakdown
    cancel = cancel or threading.Event()
    started = time.monotonic()
    if options.human_mode not in MODES:
        raise ValueError("Выберите FAST, BALANCED или MASTERPIECE")
    settings = MODES[options.human_mode]
    size = tuple(options.canvas_size)
    if min(size) < 32 or max(size) > 8192 or not options.brush_widths or min(options.brush_widths) < 1:
        raise ValueError("Некорректный холст или калиброванные кисти")
    if max(options.brush_widths) >= min(size)-4:
        raise ValueError("Кисть слишком велика для выбранного рисунка")
    _cancel(cancel)
    progress(.02, "Human Paint · анализ полей и композиции")
    prepared, padding, fill_info = apply_canvas_fill(image, size, options.canvas_fill, options.crop)
    prepared = prepare(prepared, size, False, options.style, options.remove_background)
    scale = min(1., settings["grid"]/max(size))
    working_size = tuple(max(16, round(n*scale)) for n in size)
    working = prepared.resize(working_size, Image.Resampling.LANCZOS)
    regions = project_regions(options.priority_regions, image.size, size, options.crop)
    analysis = analyze(prepared, options.priority_mode, options.detect_faces, regions)
    scores = cv2.resize(analysis.scores, working_size, interpolation=cv2.INTER_LINEAR)
    rgb = np.asarray(working)
    filtered = cv2.bilateralFilter(rgb, 5, 24 if options.human_mode == "MASTERPIECE" else 42, 5)
    progress(.09, "Human Paint · объединение цветовых масс")
    labels, palette = _quantize(Image.fromarray(filtered), options.palette, settings["colors"])
    labels = labels.copy()
    protected = np.zeros(labels.shape, np.uint8)
    for region in analysis.regions:
        if region["score"] >= 90:
            x, y, w, h = region["box"]
            protected[round(y*working_size[1]):round((y+h)*working_size[1]),
                      round(x*working_size[0]):round((x+w)*working_size[0])] = 1
    median = cv2.medianBlur(labels, 3)
    removed = 0
    for color_id in np.unique(labels):
        _cancel(cancel)
        count, components, stats, _ = cv2.connectedComponentsWithStats((labels == color_id).astype(np.uint8), 8)
        for component in range(1, count):
            if component % 128 == 0: _cancel(cancel)
            if stats[component, cv2.CC_STAT_AREA] >= settings["noise"]:
                continue
            x, y, w, h, _ = stats[component]
            points = components[y:y+h, x:x+w] == component
            if not np.any(protected[y:y+h, x:x+w][points]):
                labels[y:y+h, x:x+w][points] = median[y:y+h, x:x+w][points]
                removed += 1
    colors = np.asarray(palette, np.uint8)
    target = colors[labels]
    luma = cv2.cvtColor(target, cv2.COLOR_RGB2GRAY).astype(float)
    local_light = cv2.GaussianBlur(luma, (0, 0), max(3, min(working_size)/35))
    masks = [np.zeros_like(labels, np.uint8) for _ in STAGES]
    groups = [[] for _ in STAGES]
    foreground = np.zeros_like(labels, np.uint8)
    min_detail = max(settings["detail"], min(options.brush_widths)**2*scale**2*.4)
    for color_id in np.unique(labels):
        _cancel(cancel)
        color = tuple(int(c) for c in colors[color_id])
        if min(color) >= 248:
            continue
        count, components, stats, _ = cv2.connectedComponentsWithStats((labels == color_id).astype(np.uint8), 8)
        for component in range(1, count):
            if component % 128 == 0: _cancel(cancel)
            x, y, w, h, area = stats[component]
            mask = (components[y:y+h, x:x+w] == component).astype(np.uint8)*255
            inside = mask > 0
            importance = float(np.percentile(scores[y:y+h, x:x+w][inside], 80))
            border = x == 0 or y == 0 or x+w == labels.shape[1] or y+h == labels.shape[0]
            small = area < max(12, labels.size*.0008)
            if border and not small:
                stage = 0
            elif small and (area >= min_detail or np.any(protected[y:y+h, x:x+w][inside])):
                stage = 6
            elif float(luma[y:y+h, x:x+w][inside].mean()) < 65:
                stage = 5
            elif float((luma[y:y+h, x:x+w]-local_light[y:y+h, x:x+w])[inside].mean()) < -12:
                stage = 3
            elif float((luma[y:y+h, x:x+w]-local_light[y:y+h, x:x+w])[inside].mean()) > 14:
                stage = 4
            else:
                stage = 2
            if small and area < min_detail and not np.any(protected[y:y+h, x:x+w][inside]):
                continue
            masks[stage][y:y+h, x:x+w] |= mask
            if stage != 0:
                foreground[y:y+h, x:x+w] |= mask
            groups[stage].append((color, mask, int(color_id)*1000000+component, importance, (int(x), int(y))))
    # A real virtual silhouette underpainting is subsequently covered by target
    # base/shadow/highlight/outline masks; white holes stay unpainted throughout.
    if np.count_nonzero(foreground) > labels.size*.03:
        dominant = int(np.bincount(labels[foreground > 0], minlength=len(palette)).argmax())
        color = tuple(int(c) for c in colors[dominant])
        masks[1] = foreground
        groups[1].append((color, foreground, 2_000_000_000, 65., (0, 0)))
    strokes, missing = [], 0
    timings, max_error = {}, 0.
    for stage, name in enumerate(STAGES):
        _cancel(cancel)
        progress(.18+stage*.105, f"Layer {stage+1:02d} · {name}")
        tick = time.monotonic()
        layer = []
        # Group colors inside this stage. Different stages never interleave.
        for color, mask, component, importance, origin in sorted(groups[stage], key=lambda item: (item[0], -np.count_nonzero(item[1]))):
            widths = options.brush_widths
            if stage == 1:
                widths = widths[-2:] if len(widths) > 2 else widths
            if stage in (5, 6):
                widths = tuple(w for w in widths if w <= max(4, min(options.brush_widths)*2)) or (min(widths),)
            paths, left = region_paths(mask, color, widths, size, scale, stage, settings, cancel, component, importance, origin)
            layer.extend(paths)
            if stage != 1:
                missing += left
        if layer:
            layer, refinement = optimize(layer, size, scores, "Precision" if options.human_mode == "MASTERPIECE" else "Balanced",
                                options.detail_intelligence, cancel,
                                replace(Timing.preset(options.speed), game_delay=options.game_delay),
                                options.color_clicks, options.brush_clicks)
            max_error = max(max_error, refinement["contour_error_bound"])
        strokes.extend(replace(s, opacity=options.opacity/100) for s in layer)
        timings[name] = time.monotonic()-tick
        if len(strokes) > 100_000:
            raise ValueError("Слишком сложное изображение: выберите FAST или меньший холст")
        if sum(len(stroke.points) for stroke in strokes) > 1_000_000:
            raise ValueError("Слишком много точек траекторий. Выберите FAST или уменьшите холст.")
    timing = replace(Timing.preset(options.speed), game_delay=options.game_delay)
    progress(.94, "Проверка рисуемого покрытия · ограниченная коррекция по форме")
    repairs, raster_error = refine_coverage(strokes, labels, palette, size, options.brush_widths, scale, options.human_mode, cancel)
    strokes.extend(replace(stroke, opacity=options.opacity/100) for stroke in repairs)
    if repairs:
        from app.raster import draw_stroke
        from PIL import ImageDraw
        details_mask = Image.fromarray(masks[6])
        painter = ImageDraw.Draw(details_mask)
        for stroke in repairs:
            draw_stroke(painter, stroke, size, working_size, 255)
        masks[6] = np.asarray(details_mask).copy()
    estimate = estimate_plan(strokes, size, timing, options.color_clicks, options.brush_clicks)*options.time_factor
    source_hash = hashlib.sha256(image.convert("RGB").tobytes()+str(image.size).encode()).hexdigest()
    plan = Plan(size, strokes, timing, estimate, source_hash, list(dict.fromkeys(s.color for s in strokes)),
                color_clicks=options.color_clicks, brush_clicks=options.brush_clicks, engine="Human 3.0",
                smart_finish=False, safety_buffer=options.safety_buffer, time_factor=options.time_factor)
    plan.analysis = dict(mode=options.human_mode, method="Border-connected regions; local luminance; "+analysis.method,
                         segmentation_palette=palette,
                         regions=analysis.regions, fill=fill_info,
                         layers=[dict(index=i, name=name, strokes=sum(s.stage == i for s in strokes),
                                      pixels=int(np.count_nonzero(masks[i]))) for i, name in enumerate(STAGES)])
    plan.metrics = {**path_metrics(strokes, size), "pipeline_seconds": time.monotonic()-started,
                    "contour_error_bound": max_error,
                    "layer_planning_seconds": timings, "removed_noise_components": removed,
                    "unpaintable_mask_pixels": missing, "working_size": working_size,
                    "bounded_detail_repairs": len(repairs), "raster_error_pixels": raster_error,
                    "cost_breakdown": estimated_breakdown(plan)}
    plan._layer_masks = {name: Image.fromarray(mask) for name, mask in zip(STAGES, masks)}
    plan._label_map = Image.fromarray(labels)
    plan._padding_mask = padding
    plan._priority_scores = scores
    plan.notes = [f"Human Paint {options.human_mode}: 7 виртуальных этапов, {len(strokes)} непрерывных мазков.",
                  "Сегментация, силуэт и свет — локальные эвристики; это не семантическая нейросеть.",
                  f"Удалено шумовых островков: {removed}; пикселей масок вне возможностей кистей: {missing}.",
                  "Оценка времени требует проверки TEST DRAW / SPEED CALIBRATION в вашей игре."]
    if options.opacity != 100:
        plan.notes.append("Полупрозрачные виртуальные слои накапливают цвет; коррекция покрытия отключена. Проверьте итоговый PREVIEW.")
    if options.time_limit is not None and estimate > options.time_limit:
        plan.notes.append("План превышает таймер. Выберите FAST, уменьшите размер или используйте Unlimited; этапы не обрезаны молча.")
    progress(1., "Human Paint · план готов")
    return plan, Image.fromarray(target).resize(size, Image.Resampling.NEAREST)
