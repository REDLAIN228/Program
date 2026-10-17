from __future__ import annotations

from dataclasses import asdict, dataclass, field
import colorsys
import math
from typing import Callable

RGB = tuple[int, int, int]
Point = tuple[float, float]
Progress = Callable[[float, str], None]


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height

    def map(self, point: Point, margin: float = 0) -> tuple[int, int]:
        if self.width <= 2 * margin + 1 or self.height <= 2 * margin + 1:
            raise ValueError("Кисть слишком широка для холста")
        u, v = point
        if not (math.isfinite(u) and math.isfinite(v) and 0 <= u <= 1 and 0 <= v <= 1):
            raise ValueError("Точка штриха вне холста")
        return (round(self.x + margin + u * (self.width - 1 - 2 * margin)),
                round(self.y + margin + v * (self.height - 1 - 2 * margin)))


@dataclass(frozen=True)
class Swatch:
    rgb: RGB
    point: tuple[int, int]


@dataclass(frozen=True)
class Brush:
    pixels: int
    point: tuple[int, int]


@dataclass(frozen=True)
class ColorWheel:
    center: tuple[int, int]
    red: tuple[int, int]  # A point halfway across the hue ring at hue zero.
    square: Rect  # Saturation increases rightward; value decreases downward.
    value_reset: tuple[int, int] | None = None
    mode_button: tuple[int, int] | None = None

    def points(self, rgb: RGB) -> list[tuple[int, int]]:
        if len(rgb) != 3 or any(not 0 <= c <= 255 for c in rgb):
            raise ValueError("Некорректный RGB")
        hue, saturation, value = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
        angle = hue * 2 * math.pi
        dx, dy = self.red[0] - self.center[0], self.red[1] - self.center[1]
        ring = (round(self.center[0] + dx * math.cos(angle) - dy * math.sin(angle)),
                round(self.center[1] + dx * math.sin(angle) + dy * math.cos(angle)))
        square = (round(self.square.x + saturation * (self.square.width - 1)),
                  round(self.square.y + (1 - value) * (self.square.height - 1)))
        return [ring] + ([self.value_reset] if self.value_reset else []) + [square]


@dataclass(frozen=True)
class BrushSlider:
    start: tuple[int, int]
    end: tuple[int, int]
    minimum: int | None = None
    maximum: int | None = None

    def point(self, pixels: int) -> tuple[int, int]:
        if self.minimum is None or self.maximum is None:
            raise ValueError("Укажите минимум и максимум бесплатного ползунка в CALIBRATE → Диапазон ползунка.")
        if not self.minimum <= pixels <= self.maximum or self.maximum <= self.minimum:
            raise ValueError("Размер кисти вне диапазона бесплатного ползунка")
        t = (pixels-self.minimum) / (self.maximum-self.minimum)
        return tuple(round(a+t*(b-a)) for a, b in zip(self.start, self.end))


@dataclass
class Calibration:
    name: str
    target_class: str
    target_process: str
    client_size: tuple[int, int]
    dpi: int
    canvas: Rect
    swatches: list[Swatch]
    brushes: list[Brush]
    brush_tool: tuple[int, int] | None = None
    character: Rect | None = None
    verified: bool = False
    # Optional pixel inside a solid current-color indicator; never a palette swatch.
    color_indicator: tuple[int, int] | None = None
    color_tolerance: int = 45
    # Stable pixels on permanent swatches detect palette/layout changes at fixed window size.
    anchors: list[Swatch] = field(default_factory=list)
    color_wheel: ColorWheel | None = None
    color_tab: tuple[int, int] | None = None
    size_tab: tuple[int, int] | None = None
    brush_slider: BrushSlider | None = None
    forbidden: list[Rect] = field(default_factory=list)
    adapter: str | None = None

    def validate(self) -> None:
        w, h = self.client_size
        if w < 32 or h < 32 or self.dpi <= 0:
            raise ValueError("Некорректный размер окна или DPI")
        if self.canvas.width < 16 or self.canvas.height < 16:
            raise ValueError("Выделите холст размером хотя бы 16×16")
        if (not self.swatches and not self.color_wheel) or not self.brushes:
            raise ValueError("Нужен хотя бы один цвет и один размер кисти")
        for rect in [self.canvas, self.character]:
            if rect and (rect.width < 1 or rect.height < 1 or rect.x < 0 or rect.y < 0
                         or rect.x + rect.width > w or rect.y + rect.height > h):
                raise ValueError("Область выходит за границы игрового окна")
        controls = [s.point for s in self.swatches + self.anchors] + [b.point for b in self.brushes]
        controls += [p for p in [self.brush_tool, self.color_indicator, self.color_tab, self.size_tab] if p is not None]
        if self.brush_slider:
            slider = self.brush_slider
            controls += [slider.start, slider.end]
            if math.dist(slider.start, slider.end) < 16:
                raise ValueError("Слишком короткий ползунок кисти")
            if (slider.minimum is None) != (slider.maximum is None):
                raise ValueError("Укажите обе границы диапазона ползунка")
            if slider.minimum is not None:
                if not 1 <= slider.minimum < slider.maximum <= 4096:
                    raise ValueError("Некорректный диапазон ползунка")
                controls += [slider.point(b.pixels) for b in self.brushes]
        if self.color_wheel:
            wheel = self.color_wheel
            radius = math.dist(wheel.center, wheel.red)
            if radius < 8 or wheel.square.width < 8 or wheel.square.height < 8:
                raise ValueError("Некорректная геометрия цветового круга")
            cx, cy = wheel.center
            for left, top, right, bottom in [
                    (cx-radius, cy-radius, cx+radius, cy+radius),
                    (wheel.square.x, wheel.square.y, wheel.square.x+wheel.square.width-1,
                     wheel.square.y+wheel.square.height-1)]:
                if (left < self.canvas.x+self.canvas.width and right >= self.canvas.x
                        and top < self.canvas.y+self.canvas.height and bottom >= self.canvas.y):
                    raise ValueError("Цветовой круг и квадрат оттенков не должны пересекать холст")
            controls += [(cx-radius, cy-radius), (cx+radius, cy+radius), wheel.center, wheel.red,
                         (wheel.square.x, wheel.square.y),
                         (wheel.square.x + wheel.square.width-1, wheel.square.y + wheel.square.height-1)]
            controls += [p for p in [wheel.value_reset, wheel.mode_button] if p is not None]
        if any(not Rect(0, 0, w, h).contains(*p) for p in controls):
            raise ValueError("Элемент управления вне окна")
        if any(self.canvas.contains(*p) for p in controls):
            raise ValueError("Кнопки палитры и кисти не должны находиться на холсте")
        if any(r.contains(*p) for r in self.forbidden for p in controls):
            raise ValueError("Элемент управления попал в запрещённую донатную область")
        if any(b.pixels < 1 or b.pixels >= min(self.canvas.width, self.canvas.height)
               for b in self.brushes):
            raise ValueError("Некорректная ширина кисти")
        if any(len(s.rgb) != 3 or any(not 0 <= c <= 255 for c in s.rgb) for s in self.swatches):
            raise ValueError("Некорректный RGB")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Calibration:
        p = cls(
            name=d["name"], target_class=d["target_class"], target_process=d["target_process"],
            client_size=tuple(d["client_size"]), dpi=d["dpi"], canvas=Rect(**d["canvas"]),
            swatches=[Swatch(tuple(s["rgb"]), tuple(s["point"])) for s in d["swatches"]],
            brushes=[Brush(b["pixels"], tuple(b["point"])) for b in d["brushes"]],
            brush_tool=tuple(d["brush_tool"]) if d.get("brush_tool") else None,
            character=Rect(**d["character"]) if d.get("character") else None,
            verified=bool(d.get("verified", False)),
            color_indicator=tuple(d["color_indicator"]) if d.get("color_indicator") else None,
            color_tolerance=d.get("color_tolerance", 45),
            anchors=[Swatch(tuple(s["rgb"]), tuple(s["point"])) for s in d.get("anchors", [])],
            color_wheel=(ColorWheel(tuple(d["color_wheel"]["center"]), tuple(d["color_wheel"]["red"]),
                                    Rect(**d["color_wheel"]["square"]),
                                    tuple(d["color_wheel"]["value_reset"]) if d["color_wheel"].get("value_reset") else None,
                                    tuple(d["color_wheel"]["mode_button"]) if d["color_wheel"].get("mode_button") else None)
                         if d.get("color_wheel") else None),
            color_tab=tuple(d["color_tab"]) if d.get("color_tab") else None,
            size_tab=tuple(d["size_tab"]) if d.get("size_tab") else None,
            brush_slider=(BrushSlider(tuple(d["brush_slider"]["start"]), tuple(d["brush_slider"]["end"]),
                                      d["brush_slider"].get("minimum"), d["brush_slider"].get("maximum"))
                          if d.get("brush_slider") else None),
            forbidden=[Rect(**r) for r in d.get("forbidden", [])],
            adapter=d.get("adapter"),
        )
        p.validate()
        return p


@dataclass(frozen=True)
class Timing:
    event: float = 0.012
    settle: float = 0.09
    pixels_per_second: float = 900
    sample_pixels: float = 5

    @classmethod
    def preset(cls, name: str) -> Timing:
        return {"Safe": cls(.020, .15, 500, 4),
                "Normal": cls(), "Fast": cls(.008, .06, 1400, 6)}[name]


@dataclass(frozen=True)
class Stroke:
    points: tuple[Point, ...]
    color: RGB
    width: int
    opacity: float = 1.0
    priority: int = 0

    def length(self, size: tuple[int, int]) -> float:
        w, h = size
        return sum(math.hypot((b[0] - a[0]) * w, (b[1] - a[1]) * h)
                   for a, b in zip(self.points, self.points[1:]))

    def seconds(self, size: tuple[int, int], timing: Timing) -> float:
        length = self.length(size)
        samples = sum(max(1, math.ceil(math.hypot((b[0]-a[0])*size[0], (b[1]-a[1])*size[1])
                                      / timing.sample_pixels))
                      for a, b in zip(self.points, self.points[1:]))
        samples = max(1, samples)
        return samples * timing.event + length / timing.pixels_per_second + 4 * timing.event


@dataclass
class Plan:
    canvas_size: tuple[int, int]
    strokes: list[Stroke]
    timing: Timing
    estimated_seconds: float
    source_hash: str
    palette: list[RGB]
    notes: list[str] = field(default_factory=list)
    schema: int = 1
    color_clicks: int = 1
    brush_clicks: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Plan:
        if d.get("schema") != 1:
            raise ValueError("Неподдерживаемая версия плана")
        size = tuple(d["canvas_size"])
        if len(size) != 2 or min(size) < 16 or max(size) > 16384:
            raise ValueError("Некорректный размер холста")
        strokes = []
        if len(d["strokes"]) > 100_000:
            raise ValueError("План слишком велик")
        for s in d["strokes"]:
            points = tuple(tuple(p) for p in s["points"])
            if not points or len(points) > 100_000:
                raise ValueError("Некорректный штрих")
            for p in points:
                Rect(0, 0, *size).map(p)
            rgb = tuple(s["color"])
            if len(rgb) != 3 or any(not 0 <= c <= 255 for c in rgb):
                raise ValueError("Некорректный цвет")
            if not 1 <= s["width"] < min(size) or s.get("opacity", 1) != 1:
                raise ValueError("Неподдерживаемая кисть или прозрачность")
            strokes.append(Stroke(points, rgb, s["width"], 1.0, s.get("priority", 0)))
        timing = Timing(**d["timing"])
        if any(not math.isfinite(v) or v <= 0 for v in asdict(timing).values()):
            raise ValueError("Некорректные интервалы")
        color_clicks, brush_clicks = d.get("color_clicks", 1), d.get("brush_clicks", 1)
        if any(type(n) is not int or not 1 <= n <= 12 for n in [color_clicks, brush_clicks]):
            raise ValueError("Некорректное число нажатий элементов управления")
        estimate = estimate_plan(strokes, size, timing, color_clicks, brush_clicks)
        return cls(size, strokes, timing, estimate, d["source_hash"],
                   [tuple(c) for c in d["palette"]], d.get("notes", []),
                   color_clicks=color_clicks, brush_clicks=brush_clicks)


def estimate_plan(strokes: list[Stroke], size: tuple[int, int], timing: Timing,
                  color_clicks: int = 1, brush_clicks: int = 1) -> float:
    total = 0.0
    prev_color = prev_width = None
    for s in strokes:
        total += s.seconds(size, timing)
        if s.color != prev_color:
            total += color_clicks * (timing.settle + 3 * timing.event)
        if s.width != prev_width:
            total += brush_clicks * (timing.settle + 3 * timing.event)
        prev_color, prev_width = s.color, s.width
    return total * 1.15  # Scheduling and color-verification reserve; still only an estimate.
