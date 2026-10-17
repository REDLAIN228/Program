from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 40_000_000


def open_image(path: str) -> Image.Image:
    with Image.open(path) as im:
        if im.format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("Поддерживаются PNG, JPEG и WEBP")
        if im.width * im.height > 40_000_000:
            raise ValueError("Изображение слишком велико (максимум 40 Мп)")
        return flatten(ImageOps.exif_transpose(im))


def flatten(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    base = Image.new("RGBA", rgba.size, "white")
    return Image.alpha_composite(base, rgba).convert("RGB")


def prepare(image: Image.Image, size: tuple[int, int], crop: bool = False,
            style: str = "Anime", remove_background: bool = False) -> Image.Image:
    image = flatten(image)
    image = (ImageOps.fit(image, size, method=Image.Resampling.LANCZOS) if crop else
             ImageOps.pad(image, size, method=Image.Resampling.LANCZOS, color="white"))
    if remove_background:
        a = np.asarray(image).copy()
        # GrabCut is a local segmentation heuristic, never AI generation.
        if min(size) < 16:
            raise ValueError("Слишком маленькое изображение для удаления фона")
        mask = np.zeros(a.shape[:2], np.uint8)
        bg, fg = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.grabCut(a, mask, (2, 2, size[0] - 4, size[1] - 4), bg, fg, 3, cv2.GC_INIT_WITH_RECT)
        a[(mask == 0) | (mask == 2)] = 255
        image = Image.fromarray(a)
    a = np.asarray(image)
    if style in {"Black & White", "Manga"}:
        gray = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
        a = cv2.cvtColor(cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                              cv2.THRESH_BINARY, 15, 5), cv2.COLOR_GRAY2RGB)
    elif style == "Sketch":
        gray = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
        blur = cv2.GaussianBlur(255 - gray, (0, 0), 5)
        sketch = cv2.divide(gray, 255 - blur, scale=256)
        a = cv2.cvtColor(sketch, cv2.COLOR_GRAY2RGB)
    elif style == "Pixel Art":
        small = image.resize((48, 48), Image.Resampling.BOX)
        a = np.asarray(small.resize(size, Image.Resampling.NEAREST))
    elif style == "Comic":
        a = cv2.bilateralFilter(a, 7, 45, 45)
    # Anime / Detailed Anime / Custom leave imported artwork intact.
    return Image.fromarray(a)
