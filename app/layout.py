"""Fit a drawing inside an existing canvas without changing its calibration."""
from app.models import Rect


FORMATS = {
    "Весь холст": None,
    "Квадрат 1:1": (1, 1),
    "Портрет 3:4": (3, 4),
    "Альбом 4:3": (4, 3),
    "Вертикальный 9:16": (9, 16),
    "Широкий 16:9": (16, 9),
    "Свой размер": None,
}


def drawing_rect(canvas_size, format_name, percent=100, custom=(300, 300)):
    cw, ch = canvas_size
    if format_name not in FORMATS or percent not in (25, 50, 75, 100):
        raise ValueError("Неизвестный формат или масштаб рисунка")
    if format_name == "Свой размер":
        width, height = custom
    else:
        aspect = FORMATS[format_name]
        if aspect:
            unit = min(cw/aspect[0], ch/aspect[1])*percent/100
            width, height = round(aspect[0]*unit), round(aspect[1]*unit)
        else:
            width, height = round(cw*percent/100), round(ch*percent/100)
    if min(width, height) < 32 or width > cw or height > ch:
        raise ValueError(f"Размер рисунка должен быть не меньше 32×32 и помещаться в холст {cw}×{ch}.")
    return Rect((cw-width)//2, (ch-height)//2, width, height)
