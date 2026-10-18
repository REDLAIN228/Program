"""CPU detail saliency, optional bundled OpenCV face models, and explicit user ROIs.

Body/hair/clothes bands are composition heuristics, never semantic detections.
No downloaded weights, network requests, or mandatory GPU are used.
"""
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image


@dataclass
class PriorityResult:
    scores: np.ndarray
    regions: list[dict]
    method: str


def project_regions(regions, source_size, target_size, crop=False):
    sw, sh = source_size
    tw, th = target_size
    scale = (max if crop else min)(tw/sw, th/sh)
    dx, dy = (tw-sw*scale)/2, (th-sh*scale)/2
    result = []
    for x, y, w, h, score in regions:
        left, top = max(0., (x*sw*scale+dx)/tw), max(0., (y*sh*scale+dy)/th)
        right, bottom = min(1., ((x+w)*sw*scale+dx)/tw), min(1., ((y+h)*sh*scale+dy)/th)
        if right > left and bottom > top:
            result.append((left, top, right-left, bottom-top, score))
    return tuple(result)


def _unit(a):
    a = a.astype(np.float32)
    maximum = float(np.percentile(a, 98))
    return np.clip(a/max(maximum, 1e-5), 0, 1)


@lru_cache(maxsize=6)
def _analyze(rgb_bytes, size, mode, detect_faces, regions):
    a = np.frombuffer(rgb_bytes, np.uint8).reshape(size[1], size[0], 3)
    gray = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    contrast = _unit(np.abs(gray.astype(float)-cv2.GaussianBlur(gray, (0, 0), 5)))
    edges = _unit(cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1)))
    lab = cv2.cvtColor(a, cv2.COLOR_RGB2LAB).astype(float)
    border = np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    foreground = _unit(np.linalg.norm(lab-np.median(border, axis=0), axis=2))
    # Spectral residual saliency remains useful for objects, logos and landscapes.
    spectrum = np.fft.fft2(gray.astype(float)+1)
    log = np.log(np.abs(spectrum)+1e-6)
    residual = log-cv2.blur(log, (3, 3))
    spectral = _unit(cv2.GaussianBlur(np.abs(np.fft.ifft2(np.exp(residual+1j*np.angle(spectrum))))**2,
                                    (0, 0), 3))
    scores = 12+25*foreground+22*contrast+22*edges+19*spectral
    found = []
    height, width = gray.shape

    def add(label, box, value, source):
        x, y, w, h = box
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(width, int(x+w)), min(height, int(y+h))
        if x1 <= x0 or y1 <= y0:
            return
        scores[y0:y1, x0:x1] = np.maximum(scores[y0:y1, x0:x1], value)
        found.append(dict(label=label, box=[x0/width, y0/height, (x1-x0)/width, (y1-y0)/height],
                          score=value, source=source))

    silhouette = cv2.morphologyEx((foreground > .25).astype(np.uint8), cv2.MORPH_GRADIENT,
                                 np.ones((3, 3), np.uint8)) > 0
    scores[silhouette] = np.maximum(scores[silhouette], 88)
    # Composition priors guide the fallback, without claiming hands/eyes were detected.
    if mode in ("Portrait", "Full Character"):
        yy, xx = np.mgrid[:height, :width]
        center_y = .38 if mode == "Portrait" else .22
        head = ((xx/width-.5)/.28)**2+((yy/height-center_y)/.23)**2 < 1
        scores[head & (foreground > .1)] = np.maximum(scores[head & (foreground > .1)], 82)
        found.append(dict(label="Композиционный приоритет головы", box=[.22, max(0, center_y-.23), .56, .46],
                          score=82, source="heuristic"))
    if mode == "Landscape":
        scores = 15+30*foreground+25*contrast+20*edges+10*spectral

    # Composition hints are explicitly labelled; they are not body-part detections.
    if mode in ("Portrait", "Full Character"):
        cy = .38 if mode == "Portrait" else .22
        add("Предполагаемая зона глаз", (width*.28, height*(cy-.03), width*.44, height*.09),
            94, "composition heuristic")
        add("Предполагаемые волосы", (width*.22, max(0, height*(cy-.23)), width*.56, height*.12),
            90, "composition heuristic")
        if mode == "Full Character":
            add("Предполагаемая одежда и тело", (width*.25, height*.43, width*.5, height*.48),
                75, "composition heuristic")
    faces_found = bodies_found = 0
    model_available = False
    if detect_faces:
        from pathlib import Path
        folder = getattr(cv2.data, "haarcascades", "")
        path = Path(folder)/"haarcascade_frontalface_default.xml"
        if path.is_file():
            model_available = True
            faces = cv2.CascadeClassifier(str(path)).detectMultiScale(gray, 1.12, 5, minSize=(24, 24))
            eye_path = Path(folder)/"haarcascade_eye.xml"
            eye_model = cv2.CascadeClassifier(str(eye_path)) if eye_path.is_file() else None
            for x, y, w, h in faces:
                faces_found += 1
                add("Лицо", (x, y, w, h), 94, "OpenCV Haar")
                add("Нижняя часть лица", (x+w*.22, y+h*.55, w*.56, h*.35), 96, "face-relative heuristic")
                if eye_model is not None:
                    for ex, ey, ew, eh in eye_model.detectMultiScale(gray[y:y+h//2, x:x+w], 1.1, 4, minSize=(8, 8)):
                        add("Глаз", (x+ex, y+ey, ew, eh), 100, "OpenCV Haar")
        if mode == "Full Character" and height >= 128 and width >= 64:
            hog = cv2.HOGDescriptor()
            hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            bodies, confidence = hog.detectMultiScale(gray, winStride=(8, 8), padding=(8, 8), scale=1.1)
            for x, y, w, h in bodies:
                bodies_found += 1
                add("Фигура человека", (x, y, w, h), 85, "OpenCV HOG/SVM pedestrian model")
                add("Предполагаемая одежда", (x+w*.15, y+h*.3, w*.7, h*.55), 75, "body-relative heuristic")
                add("Предполагаемая левая рука", (x, y+h*.3, w*.22, h*.45), 85, "body-relative heuristic")
                add("Предполагаемая правая рука", (x+w*.78, y+h*.3, w*.22, h*.45), 85, "body-relative heuristic")
    # Text-like runs: local contrast regions with repeated narrow components.
    dark = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 8)
    lines = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((2, 9), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(lines, 8)
    for x, y, w, h, area in stats[1:count]:
        if 2.5 < w/max(1, h) < 18 and 6 <= h < height*.12 and area/(w*h) > .3:
            add("Возможная надпись", (x, y, w, h), 89, "contrast heuristic; no OCR")
    for x, y, w, h, value in regions:
        if not all(np.isfinite(v) for v in (x, y, w, h, value)) or not 0 <= value <= 100:
            raise ValueError("Некорректная пользовательская область приоритета")
        x0, y0 = max(0, round(x*width)), max(0, round(y*height))
        x1, y1 = min(width, round((x+w)*width)), min(height, round((y+h)*height))
        scores[y0:y1, x0:x1] = value  # Manual lowering must override automatic scores too.
        found.append(dict(label="Ручная область", box=[x, y, w, h], score=value, source="user"))
    scores = np.clip(scores, 0, 100).astype(np.float32)
    scores.setflags(write=False)
    method = ((f"OpenCV Haar: {faces_found} лиц; " if model_available else "Модель OpenCV недоступна; ")
              if detect_faces else "Детектор лиц выключен; ")
    method += "значимость, контраст, силуэт и текстовые кандидаты — эвристика"
    if detect_faces and mode == "Full Character":
        method += f"; HOG/SVM: {bodies_found} фигур (не anime/pose-модель)"
    return PriorityResult(scores, found, method)


def analyze(image, mode="Auto", detect_faces=True, regions=()):
    if mode not in ("Auto", "Portrait", "Full Character", "Landscape", "Custom"):
        raise ValueError("Неизвестный режим приоритетов")
    reduced = image.convert("RGB").copy()
    reduced.thumbnail((512, 512), Image.Resampling.LANCZOS)
    return _analyze(reduced.tobytes(), reduced.size, mode, detect_faces, tuple(tuple(r) for r in regions))


def heatmap(image, scores):
    base = image.convert("RGB").copy()
    base.thumbnail((1536, 1536), Image.Resampling.LANCZOS)
    values = cv2.resize(scores, base.size, interpolation=cv2.INTER_LINEAR)
    colors = np.full((*values.shape, 3), (100, 105, 115), np.uint8)
    colors[values >= 40] = (248, 213, 85)
    colors[values >= 65] = (250, 140, 52)
    colors[values >= 85] = (235, 55, 80)
    return Image.blend(base, Image.fromarray(colors), .43)


def simplify_background(image, scores, strength):
    if strength <= 0:
        return image.copy()
    a = np.asarray(image.convert("RGB"))
    small = cv2.resize(a, (scores.shape[1], scores.shape[0]), interpolation=cv2.INTER_AREA)
    blurred = cv2.bilateralFilter(small, 9, 55, 55)
    blurred = cv2.resize(blurred, image.size, interpolation=cv2.INTER_LINEAR)
    weight = cv2.resize((1-scores/100)**2, image.size)[:, :, None]*strength/100
    mixed = Image.fromarray(np.rint(a*(1-weight)+blurred*weight).astype(np.uint8))
    # Blending must not invent dozens of near-identical colors around a flat
    # cartoon edge. Snap the simplified background to an actual source palette.
    palette = image.convert("RGB").quantize(colors=64, dither=Image.Dither.NONE)
    simplified = np.asarray(mixed.quantize(palette=palette, dither=Image.Dither.NONE).convert("RGB"))
    protected = cv2.resize(scores, image.size) >= 85
    output = simplified.copy()
    output[protected] = a[protected]
    return Image.fromarray(output)
