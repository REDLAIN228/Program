"""Decorate only padding introduced by aspect-ratio fitting, never source whites."""
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from app.imaging import flatten
from app.models import Rect

MODES = ("NONE", "AUTO EXTEND", "BLURRED EDGES", "SOLID COLOR", "MIRROR FILL",
         "REDLAIN BRANDING", "CUSTOM TEXT", "PATTERN FILL")


@dataclass(frozen=True)
class FillSettings:
    mode: str = "NONE"
    text: str = "REDLAIN"
    font_size: int = 28
    color: tuple = (190, 39, 53)
    alignment: str = "center"
    font: str = "Sans"
    x: float = .5
    y: float = .5

    @classmethod
    def from_dict(cls, value=None):
        settings = cls(**(value or {}))
        if settings.mode not in MODES or settings.alignment not in ("left", "center", "right"):
            raise ValueError("Неизвестный режим заполнения или выравнивания")
        if (type(settings.font_size) is not int or not 6 <= settings.font_size <= 256
                or not isinstance(settings.text, str) or len(settings.text) > 160
                or settings.font not in ("Sans", "Serif", "Mono")
                or len(settings.color) != 3 or any(type(c) is not int or not 0 <= c <= 255 for c in settings.color)
                or not all(np.isfinite(c) and 0 <= c <= 1 for c in (settings.x, settings.y))):
            raise ValueError("Некорректные настройки оформления полей")
        return settings

    def to_dict(self):
        return asdict(self)


def padding_layout(source_size, target_size, crop=False):
    sw, sh = source_size
    tw, th = target_size
    if min(sw, sh, tw, th) < 1:
        raise ValueError("Пустое изображение или холст")
    if crop:
        return Rect(0, 0, tw, th), Image.new("L", target_size)
    # Use Pillow's actual contain rounding; this is geometry, not a whiteness detector.
    fitted = ImageOps.contain(Image.new("L", source_size), target_size)
    w, h = fitted.size
    rect = Rect((tw-w)//2, (th-h)//2, w, h)
    mask = Image.new("L", target_size, 255)
    ImageDraw.Draw(mask).rectangle((rect.x, rect.y, rect.x+w-1, rect.y+h-1), fill=0)
    return rect, mask


def _font(settings):
    names = {"Sans": ("segoeui.ttf", "DejaVuSans.ttf"), "Serif": ("georgia.ttf", "DejaVuSerif.ttf"),
             "Mono": ("consola.ttf", "DejaVuSansMono.ttf")}[settings.font]
    for name in names:
        for path in (Path("C:/Windows/Fonts")/name, Path(name)):
            try:
                return ImageFont.truetype(str(path), settings.font_size), False
            except OSError:
                pass
    return ImageFont.load_default(size=settings.font_size), True


def apply_canvas_fill(image, size, settings=None, crop=False):
    settings = FillSettings.from_dict(settings.to_dict() if isinstance(settings, FillSettings) else settings)
    source = flatten(image)
    rect, mask = padding_layout(source.size, size, crop)
    base = (ImageOps.fit(source, size, method=Image.Resampling.LANCZOS) if crop else
            ImageOps.pad(source, size, method=Image.Resampling.LANCZOS, color="white"))
    info = dict(content=asdict(rect), padding_pixels=int(np.count_nonzero(np.asarray(mask))),
                mode=settings.mode, font_fallback=False)
    if not info["padding_pixels"] or settings.mode == "NONE":
        return base, mask, info
    fitted = np.asarray(source.resize((rect.width, rect.height), Image.Resampling.LANCZOS))
    pads = ((rect.y, size[1]-rect.y-rect.height), (rect.x, size[0]-rect.x-rect.width), (0, 0))
    edge = Image.fromarray(np.pad(fitted, pads, mode="edge"))
    border = np.concatenate((fitted[0], fitted[-1], fitted[:, 0], fitted[:, -1]))
    background = tuple(np.median(border, axis=0).astype(int).tolist())
    if settings.mode == "AUTO EXTEND":
        decoration = edge.filter(ImageFilter.GaussianBlur(max(2, min(size)/70)))
    elif settings.mode == "BLURRED EDGES":
        decoration = ImageOps.fit(source, size).filter(ImageFilter.GaussianBlur(max(6, min(size)/18)))
    elif settings.mode == "MIRROR FILL":
        decoration = Image.fromarray(np.pad(fitted, pads, mode="reflect" if min(fitted.shape[:2]) > 1 else "edge"))
    else:
        decoration = Image.new("RGB", size, background if settings.mode == "SOLID COLOR" else "white")
        draw = ImageDraw.Draw(decoration)
        if settings.mode == "PATTERN FILL":
            gap = max(12, min(size)//16)
            for offset in range(-size[1], size[0]+size[1], gap):
                draw.line((offset, 0, offset+size[1], size[1]), fill=settings.color, width=1)
        elif settings.mode in ("REDLAIN BRANDING", "CUSTOM TEXT"):
            text = "REDLAIN" if settings.mode == "REDLAIN BRANDING" else settings.text
            font, info["font_fallback"] = _font(settings)
            bands = [Rect(0, 0, size[0], rect.y),
                     Rect(0, rect.y+rect.height, size[0], size[1]-rect.y-rect.height),
                     Rect(0, 0, rect.x, size[1]),
                     Rect(rect.x+rect.width, 0, size[0]-rect.x-rect.width, size[1])]
            bands = [band for band in bands if min(band.width, band.height) > 0]
            desired = (settings.x*(size[0]-1), settings.y*(size[1]-1))
            band = min(bands, key=lambda b: (0 if b.contains(*desired) else
                       ((b.x+b.width/2-desired[0])**2+(b.y+b.height/2-desired[1])**2)))
            box = draw.textbbox((0, 0), text, font=font)
            width, height = box[2]-box[0], box[3]-box[1]
            if width > band.width-4 or height > band.height-4:
                # A simplified drawable font is sized to this padding band.
                factor = min((band.width-4)/max(1, width), (band.height-4)/max(1, height), 1)
                font = ImageFont.load_default(size=max(6, round(settings.font_size*max(.1, factor))))
                info["font_fallback"] = True
                box = draw.textbbox((0, 0), text, font=font)
                width, height = box[2]-box[0], box[3]-box[1]
            anchor = {"left": band.x+3, "center": desired[0]-width/2, "right": band.x+band.width-width-3}[settings.alignment]
            x = max(band.x+2, min(anchor, band.x+band.width-width-2))
            y = max(band.y+2, min(desired[1]-height/2, band.y+band.height-height-2))
            draw.text((x-box[0], y-box[1]), text, fill=settings.color, font=font)
    base.paste(decoration, mask=mask)
    return base, mask, info


def highlight_padding(image, mask):
    output = image.convert("RGB").copy()
    tint = Image.blend(output, Image.new("RGB", output.size, (203, 70, 55)), .28)
    output.paste(tint, mask=mask)
    return output
