from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
import threading
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw

from app.imaging import prepare
from app.models import Plan, Progress, RGB, Rect, Stroke, Timing, estimate_plan
from app.painter import complete_coverage, shape_strokes
from app.raster import draw_stroke, composite_stroke


@dataclass
class PlanOptions:
    canvas_size: tuple[int, int] = (512, 512)
    quality: str = "Balanced"
    style: str = "Anime"
    speed: str = "Normal"
    time_limit: float | None = 165
    palette: list[RGB] | None = None
    brush_widths: tuple[int, ...] = (3, 9, 18)
    crop: bool = False
    remove_background: bool = False
    color_clicks: int = 1
    brush_clicks: int = 1
    stroke_style: str = "Shape"
    engine: str = "Legacy"
    detail_intelligence: int = 75
    priority_mode: str = "Auto"
    detect_faces: bool = True
    priority_regions: tuple = ()
    vector_accuracy: str = "Balanced"
    safety_buffer: float = 8.
    smart_finish: bool = True
    time_factor: float = 1.
    measured_runs: int = 0
    opacity: int = 100
    game_delay: float = .25
    human_mode: str = "BALANCED"
    canvas_fill: dict | None = None
    input_calibration: dict | None = None


def rdp(points: np.ndarray, epsilon: float) -> np.ndarray:
    return cv2.approxPolyDP(np.asarray(points, np.float32).reshape(-1, 1, 2), epsilon, False).reshape(-1, 2)


def _quantize(image: Image.Image, palette: list[RGB] | None, colors: int) -> tuple[np.ndarray, list[RGB]]:
    if palette:
        palette = list(dict.fromkeys(tuple(c) for c in palette))
        values = np.array(palette, dtype=np.float32)
        a = np.asarray(image, dtype=np.float32).reshape(-1, 3)
        # Bounded memory even for 1920x1080 and 64 calibrated colors.
        labels = np.empty(len(a), dtype=np.uint8)
        norms = (values*values).sum(axis=1)
        for start in range(0, len(a), 16384):
            chunk = a[start:start+16384]
            distance = (chunk*chunk).sum(axis=1)[:, None]+norms[None, :]-2*(chunk@values.T)
            labels[start:start+len(chunk)] = np.argmin(distance, axis=1)
        labels = labels.reshape(image.height, image.width)
        if len(palette) > colors:
            counts = np.bincount(labels.ravel(), minlength=len(palette))
            ranked = np.argsort(-counts).tolist()
            dark = min(range(len(palette)), key=lambda i: sum(palette[i]))
            white = next((i for i, rgb in enumerate(palette) if min(rgb) >= 248), None)
            keep = [i for i in [dark, white] if i is not None and counts[i] > 0]
            keep = list(dict.fromkeys(keep + ranked))[:colors]
            # Prefer a smaller subset of actual calibrated swatches; no invented colors.
            return _quantize(image, [palette[i] for i in keep], colors)
        return labels, palette
    # Preserve distinct dark/light/chromatic extremes instead of averaging a black
    # outline and colored clothing into the same gray when the budget is reduced.
    method = Image.Quantize.MEDIANCUT if colors >= 12 else Image.Quantize.MAXCOVERAGE
    q = image.quantize(colors=colors, method=method, dither=Image.Dither.NONE)
    pal = q.getpalette()
    palette = [tuple(pal[3 * i:3 * i + 3]) for i in range(len(pal) // 3)]
    return np.asarray(q), palette


def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.pad((row > 0).astype(np.int8), (1, 1)))
    return list(zip(np.where(d == 1)[0].tolist(), (np.where(d == -1)[0] - 1).tolist()))


def _merge_hatches(strokes: list[Stroke], mask: np.ndarray, size: tuple[int, int],
                   scale: tuple[float, float]) -> list[Stroke]:
    """Join nearby hatch rows only when the connector stays in the same color core."""
    if not strokes:
        return []
    w, h = size
    sx, sy = scale
    brush = strokes[0].width
    radius = max(1, round(brush * min(sx, sy)))
    core = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius, radius)),
                     borderType=cv2.BORDER_CONSTANT, borderValue=0)
    margin = brush / 2 + 1
    def raster(point):
        return np.array(((margin + point[0]*(w-1-2*margin))*sx,
                         (margin + point[1]*(h-1-2*margin))*sy))
    output = []
    points = list(strokes[0].points)
    for stroke in strokes[1:]:
        a, b = raster(points[-1]), raster(stroke.points[0])
        distance = float(np.linalg.norm(b-a))
        join = distance <= max(3., radius * 3)
        if join:
            check = np.rint(np.linspace(a, b, max(2, math.ceil(distance) + 1))).astype(int)
            check[:, 0] = np.clip(check[:, 0], 0, mask.shape[1]-1)
            check[:, 1] = np.clip(check[:, 1], 0, mask.shape[0]-1)
            join = bool(np.all(core[check[:, 1], check[:, 0]]))
        if join:
            points.extend(stroke.points)
        else:
            output.append(Stroke(tuple(points), stroke.color, brush))
            points = list(stroke.points)
    output.append(Stroke(tuple(points), strokes[0].color, brush))
    return output


def render_plan(plan: Plan, size: tuple[int, int] | None = None) -> Image.Image:
    size = size or plan.canvas_size
    image = Image.new("RGB", size, "white")
    for stroke in plan.strokes:
        composite_stroke(image, stroke, plan.canvas_size, size)
    return image


def render_placement(plan: Plan) -> Image.Image:
    """Show the selected drawing at its actual size on the entire canvas."""
    if plan.drawing_rect is None:
        return render_plan(plan)
    area = plan.drawing_area(Rect(0, 0, *plan.target_canvas_size))
    image = Image.new("RGB", plan.target_canvas_size, "white")
    image.paste(render_plan(plan), (area.x, area.y))
    return image


def _build_legacy(image: Image.Image, options: PlanOptions, progress: Progress = lambda *_: None,
               cancel: threading.Event | None = None) -> tuple[Plan, Image.Image]:
    cancel = cancel or threading.Event()
    cw, ch = options.canvas_size
    if min(cw, ch) < 32 or max(cw, ch) > 8192:
        raise ValueError("Размер холста должен быть от 32 до 8192 пикселей")
    if not options.brush_widths or min(options.brush_widths) < 1:
        raise ValueError("Задайте калиброванные размеры кисти")
    if max(options.brush_widths) >= min(cw, ch) - 4:
        raise ValueError("Размер кисти превышает размеры холста")
    if options.palette is not None and not 1 <= len(options.palette) <= 64:
        raise ValueError("Палитра должна содержать от 1 до 64 цветов")
    if options.time_limit is not None and options.time_limit <= 0:
        raise ValueError("Лимит времени должен быть положительным")
    if options.stroke_style not in {"Shape", "Scanline"}:
        raise ValueError("Неизвестный способ рисования")
    timing = replace(Timing.preset(options.speed), game_delay=options.game_delay)
    grid, colors = {"Fast": (160, 8), "Balanced": (256, 12),
                    "Detailed": (320, 20), "Ultra Detailed": (768, 64), "Full HD": (1920, 128)}[options.quality]
    full_hd = options.quality == "Full HD"
    minimum_colors = min(8, len(options.palette)) if options.palette else 8
    source_hash = hashlib.sha256(image.convert("RGB").tobytes() + str(image.size).encode()).hexdigest()
    best = None
    baseline = None
    for attempt in range(1 if full_hd else 4):
        if cancel.is_set():
            raise InterruptedError("Обработка отменена")
        ratio = min(1, grid / max(cw, ch))
        w, h = max(16, round(cw * ratio)), max(16, round(ch * ratio))
        progress(attempt / 4, f"Сегментация: {w}×{h}")
        prepared = prepare(image, (w, h), options.crop, options.style, options.remove_background)
        if options.engine == "Legacy" and not full_hd and (attempt or options.stroke_style == "Shape"):
            prepared = Image.fromarray(cv2.medianBlur(np.asarray(prepared), 3))
        labels, palette = _quantize(prepared, options.palette, colors)
        # Simplify color segmentation at a coarse resolution, but never space fill
        # rows farther apart than the smallest physical brush. Reducing both grids
        # together would create white stripes/dots in the budget-reduced result.
        fill_ratio = min(1., max(ratio, 1. / min(options.brush_widths)))
        fill_w, fill_h = max(16, round(cw * fill_ratio)), max(16, round(ch * fill_ratio))
        grid_limit = 1920 if full_hd else 1024
        if max(fill_w, fill_h) > grid_limit:
            raise ValueError("Для такого большого холста добавьте более широкую минимальную кисть "
                             f"или уменьшите окно: рабочая сетка ограничена {grid_limit} px для CPU.")
        labels = cv2.resize(labels, (fill_w, fill_h), interpolation=cv2.INTER_NEAREST)
        w, h = fill_w, fill_h
        ratio_x, ratio_y = w / cw, h / ch
        ratio = min(ratio_x, ratio_y)
        detail_map = (cv2.resize(options._priority_scores, (w, h))
                      if hasattr(options, "_priority_scores") else None)
        strokes: list[Stroke] = []
        # Large color areas first, preserving contours for a separate last pass.
        color_ids = sorted(np.unique(labels).tolist(), key=lambda c: -int(np.count_nonzero(labels == c)))
        widths = sorted(set(options.brush_widths), reverse=True)
        for idx, color_id in enumerate(color_ids):
            if cancel.is_set():
                raise InterruptedError("Обработка отменена")
            color = palette[color_id]
            if min(color) >= 248:  # White is the explicitly required blank background.
                continue
            mask = (labels == color_id).astype(np.uint8) * 255
            if options.stroke_style == "Shape":
                strokes.extend(shape_strokes(mask, color, widths, options.canvas_size, (ratio_x, ratio_y), cancel,
                                             detail_map, options.vector_accuracy, options.detail_intelligence))
                progress((attempt + .9*(idx + 1) / len(color_ids)) / 4, "Штрихи по форме областей")
                continue
            covered = np.zeros((h, w), np.uint8)
            for brush in widths:
                hatch_strokes = []
                thickness = max(1, round(brush * ratio))
                remaining = cv2.bitwise_and(mask, cv2.bitwise_not(covered))
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (thickness, thickness))
                core = cv2.erode(remaining, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0)
                spacing = max(1, math.floor(thickness * .75))
                reverse = False
                for y in range(0, h, spacing):
                    runs = _runs(core[y])
                    if reverse:
                        runs.reverse()
                    for x0, x1 in runs:
                        if thickness > 1 and x1 - x0 < thickness:
                            continue
                        start, end = ((x1, y), (x0, y)) if reverse else ((x0, y), (x1, y))
                        # Invert the executor's inset mapping, preserving intended pixel positions.
                        margin = brush / 2 + 1
                        def normalized(p):
                            return (min(1., max(0., (p[0] / ratio_x - margin) / (cw - 1 - 2 * margin))),
                                    min(1., max(0., (p[1] / ratio_y - margin) / (ch - 1 - 2 * margin))))
                        hatch_strokes.append(Stroke((normalized(start), normalized(end)), color, brush, priority=0))
                        # cv2.line(thickness=N) can cover N+2 raster pixels. That would
                        # overestimate real brush coverage and leave white horizontal gaps.
                        # Mark only cells fully covered by this physical-width stroke.
                        radius = max(0, math.floor(brush * min(ratio_x, ratio_y) / 2 - .5))
                        covered[max(0, y-radius):min(h, y+radius+1), x0:x1+1] = 255
                    reverse = not reverse
                strokes.extend(_merge_hatches(hatch_strokes, mask, options.canvas_size, (ratio_x, ratio_y)))
            # Vector contours preserve small islands and boundaries with the finest brush.
            contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for contour in sorted(contours, key=cv2.contourArea, reverse=True):
                if len(contour) < 2:
                    continue
                line = rdp(np.vstack([contour[:, 0], contour[0, 0]]), .65 + attempt * .35)
                if len(line) < 2:
                    continue
                brush = min(widths)
                margin = brush / 2 + 1
                points = tuple((float(min(1., max(0., (x / ratio_x - margin) / (cw - 1 - 2 * margin)))),
                                float(min(1., max(0., (y / ratio_y - margin) / (ch - 1 - 2 * margin)))))
                               for x, y in line)
                strokes.append(Stroke(points, color, brush, priority=1))
            progress((attempt + .9*(idx + 1) / len(color_ids)) / 4, "Планирование штрихов")
        # Fill layers first; short vector contours last. Group by color/width within layers.
        if options.stroke_style == "Shape":
            # Preserve component order inside each stage instead of scanning the whole image by rows.
            strokes.sort(key=lambda s: s.priority)
        else:
            strokes.sort(key=lambda s: (s.priority, s.color, -s.width))
        progress((attempt+.95)/4 if not full_hd else .95, "Проверка реального покрытия и заполнение пробелов")
        if len(strokes) > 100_000:
            raise ValueError("План превышает 100 000 штрихов. Уменьшите кадр или качество.")
        repairs, uncovered = complete_coverage(strokes, labels, palette, widths, options.canvas_size, cancel)
        strokes.extend(repairs)
        if options.engine == "Legacy" and options.opacity != 100:
            strokes = [replace(stroke, opacity=options.opacity/100) for stroke in strokes]
        estimate = estimate_plan(strokes, options.canvas_size, timing, options.color_clicks, options.brush_clicks)
        plan = Plan(options.canvas_size, strokes, timing, estimate, source_hash,
                    list(dict.fromkeys(s.color for s in strokes)),
                    color_clicks=options.color_clicks, brush_clicks=options.brush_clicks)
        plan.notes.append(f"Покрытие: добавлено {len(repairs)} корректирующих штрихов; "
                          f"незаполненных пикселей в проверяемой области: {uncovered}.")
        if best is None or estimate < best[0].estimated_seconds:
            best = plan, Image.fromarray(np.array(palette, np.uint8)[labels]), attempt
        if baseline is None:
            baseline = best
        if options.time_limit is None or estimate <= options.time_limit:
            break
        grid = max(64, int(grid * .70))
        colors = max(minimum_colors, colors // 2)
        # Do not discard calibrated colors or fabricate larger uncalibrated brushes.
        # Grid reduction merges details; a still-over-budget plan is refused at RUN.
    assert best is not None
    if options.time_limit and best[0].estimated_seconds > options.time_limit:
        # If every candidate is too slow, keep the original quality and refuse RUN.
        # Do not present a ruined, still-over-budget result as a successful optimization.
        best = baseline
    plan, prepared, selected_attempt = best
    plan.notes.append("Локальная обработка; это не AI-генерация. Начинайте с пустого белого холста.")
    if full_hd:
        plan.notes.append(f"Full HD: расчёт {w}×{h}, до 128 цветов, без автоматического снижения качества. "
                          f"Физический холст {cw}×{ch}; исходные детали не дорисовываются.")
    plan.notes.append("Штрихи по форме: набросок → отдельные цветовые области → тонкие детали."
                      if options.stroke_style == "Shape" else "Построчное заполнение областей.")
    plan.notes.append(f"Цвета из изображения через HSV; проверьте TEST DRAW. Непрозрачность {options.opacity}%."
                      if options.palette is None and options.color_clicks > 1 else
                      f"Ручная палитра: только подтверждённые RGB и размеры кисти; непрозрачность {options.opacity}%.")
    if options.time_limit and plan.estimated_seconds > options.time_limit:
        plan.notes.append(f"План требует около {plan.estimated_seconds:.0f} с и превышает лимит "
                          f"{options.time_limit:.0f} с. Увеличьте лимит или упростите изображение.")
    if selected_attempt:
        plan.notes.append(f"Детализация и палитра снижены на {selected_attempt} ступени для бюджета времени.")
    progress(1., "План готов")
    return plan, prepared


def _build_selected(image: Image.Image, options: PlanOptions, progress: Progress = lambda *_: None,
               cancel: threading.Event | None = None) -> tuple[Plan, Image.Image]:
    """Preserve the public planning API and the explicit legacy comparison path."""
    if type(options.opacity) is not int or not 1 <= options.opacity <= 100:
        raise ValueError("Непрозрачность должна быть целым числом 1–100%")
    if not math.isfinite(options.game_delay) or not .06 <= options.game_delay <= 1:
        raise ValueError("Задержка игры должна быть 60–1000 мс")
    if options.engine == "Human 3.0":
        from app.human import build_human_plan
        return build_human_plan(image, options, progress, cancel)
    if options.engine == "Legacy":
        return _build_legacy(image, options, progress, cancel)
    if options.engine != "Vector 2.0":
        raise ValueError("Неизвестный движок")
    from app.priority import analyze, project_regions, simplify_background
    from app.vector import optimize, merge_compatible
    from app.smart_timer import fit_budget
    pipeline_started = time.monotonic()
    cancel = cancel or threading.Event()
    if cancel.is_set():
        raise InterruptedError("Обработка отменена")
    if not 0 <= options.detail_intelligence <= 100:
        raise ValueError("Detail Intelligence должен быть 0–100")
    if not 0 <= options.safety_buffer <= 60 or not .1 <= options.time_factor <= 20:
        raise ValueError("Некорректная настройка Smart Timer")
    progress(.01, "Анализ значимости изображения")
    analysis_image = prepare(image, options.canvas_size, options.crop, "Custom", options.remove_background)
    regions = project_regions(options.priority_regions, image.size, options.canvas_size, options.crop)
    analysis = analyze(analysis_image, options.priority_mode, options.detect_faces, regions)
    scores = analysis.scores if options.detail_intelligence else np.full_like(analysis.scores, 50)
    input_image = simplify_background(analysis_image, scores, options.detail_intelligence)
    base_options = replace(options, crop=False, remove_background=False, time_limit=None)
    base_options._priority_scores = scores
    plan, processed = _build_legacy(input_image, base_options,
                                     lambda value, label: progress(.08+value*.53, label), cancel)
    progress(.63, "Адаптивные кривые Безье и безопасный порядок слоёв")
    old_strokes = plan.strokes
    strokes, metrics = optimize(old_strokes, plan.canvas_size, scores, options.vector_accuracy,
                                options.detail_intelligence, cancel, plan.timing, plan.color_clicks, plan.brush_clicks)
    # Check the actual raster after curve fitting too; a reduced point count is
    # never accepted as proof that fill coverage survived the geometry change.
    palette = list(dict.fromkeys(plan.palette+[(255, 255, 255)]))
    labels, palette = _quantize(processed, palette, len(palette))
    before_merge = len(strokes)
    strokes = merge_compatible(strokes, labels, palette, plan.canvas_size, cancel)
    repairs, uncovered = complete_coverage(strokes, labels, palette, options.brush_widths, plan.canvas_size, cancel)
    if repairs:
        repairs, _ = optimize(repairs, plan.canvas_size, scores, "Ultra", options.detail_intelligence, cancel,
                              plan.timing, plan.color_clicks, plan.brush_clicks)
        repairs = merge_compatible(repairs, labels, palette, plan.canvas_size, cancel)
    plan.strokes = [replace(stroke, opacity=options.opacity/100) for stroke in strokes+repairs]
    plan.source_hash = hashlib.sha256(image.convert("RGB").tobytes()+str(image.size).encode()).hexdigest()
    plan.engine, plan.smart_finish = "Vector 2.0", options.smart_finish
    plan.safety_buffer, plan.time_factor = options.safety_buffer, options.time_factor
    plan.analysis = dict(method=analysis.method, regions=analysis.regions, mode=options.priority_mode)
    metrics["unrefined_estimate"] = estimate_plan(old_strokes, plan.canvas_size, plan.timing,
                                           plan.color_clicks, plan.brush_clicks)*options.time_factor
    metrics["coverage_repairs"] = len(repairs)
    metrics["merged_strokes"] = before_merge-len(strokes)
    metrics["uncovered_pixels"] = uncovered
    plan.metrics = metrics
    plan.estimated_seconds = estimate_plan(plan.strokes, plan.canvas_size, plan.timing,
                                           plan.color_clicks, plan.brush_clicks)*options.time_factor
    plan.notes.append("Detail Priority: "+analysis.method)
    if options.opacity != 100:
        plan.notes.append(f"Непрозрачность штрихов {options.opacity}%. Перекрытия накапливают цвет; "
                          "для точной копии исходных цветов используйте 100%.")
    plan.notes.append(f"Vector 2.0: допуск относительно базовых штрихов ≤{metrics['contour_error_bound']:.2f} px; "
                      f"добавлено {len(repairs)} штрихов контроля покрытия.")
    plan.notes.append(f"Оценка по {options.measured_runs} измеренным запускам (приблизительно)."
                      if options.measured_runs else "Пока нет измерений этого профиля и скорости; оценка консервативная и приблизительная.")
    progress(.9, "Распределение времени с сохранением приоритетов")
    plan = fit_budget(plan, options.time_limit)
    if options.quality == "Full HD" and options.time_limit is not None:
        plan.notes = [note.replace("без автоматического снижения качества",
                                   "без снижения разрешения сетки; бюджет может сокращать второстепенные штрихи")
                      for note in plan.notes]
    plan.metrics["new_estimate"] = plan.estimated_seconds
    plan.metrics["pipeline_seconds"] = time.monotonic()-pipeline_started
    # Comparison is generated on demand; store the unmodified stroke data in a
    # separate UI result/cache rather than duplicating it in every JSON plan.
    plan._reference_strokes = old_strokes
    plan._priority_scores = scores
    progress(1., "Vector Engine 2.0: план готов")
    return plan, processed


def build_plan(image: Image.Image, options: PlanOptions, progress: Progress = lambda *_: None,
               cancel: threading.Event | None = None) -> tuple[Plan, Image.Image]:
    if options.engine == "Human 3.0" or not options.canvas_fill:
        plan, processed = _build_selected(image, options, progress, cancel)
        if options.input_calibration:
            plan.analysis["input_calibration"] = options.input_calibration
        return plan, processed
    from app.canvas_fill import apply_canvas_fill
    from app.priority import project_regions
    original_hash = hashlib.sha256(image.convert("RGB").tobytes()+str(image.size).encode()).hexdigest()
    filled, mask, info = apply_canvas_fill(image, options.canvas_size, options.canvas_fill, options.crop)
    mapped = project_regions(options.priority_regions, image.size, options.canvas_size, options.crop)
    plan, processed = _build_selected(filled, replace(options, crop=False, priority_regions=mapped), progress, cancel)
    plan.source_hash = original_hash
    plan.analysis["fill"] = info
    plan._padding_mask = mask
    if options.input_calibration:
        plan.analysis["input_calibration"] = options.input_calibration
    return plan, processed
