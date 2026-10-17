from __future__ import annotations

from dataclasses import asdict, dataclass, field
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

    def validate(self) -> None:
        w, h = self.client_size
        if w < 32 or h < 32 or self.dpi <= 0:
            raise ValueError("Некорректный размер окна или DPI")
        if self.canvas.width < 16 or self.canvas.height < 16:
            raise ValueError("Выделите холст размером хотя бы 16×16")
        if not self.swatches or not self.brushes:
            raise ValueError("Нужен хотя бы один цвет и один размер кисти")
        for rect in [self.canvas, self.character]:
            if rect and (rect.width < 1 or rect.height < 1 or rect.x < 0 or rect.y < 0
                         or rect.x + rect.width > w or rect.y + rect.height > h):
                raise ValueError("Область выходит за границы игрового окна")
        controls = [s.point for s in self.swatches + self.anchors] + [b.point for b in self.brushes]
        controls += [p for p in [self.brush_tool, self.color_indicator] if p is not None]
        if any(not Rect(0, 0, w, h).contains(*p) for p in controls):
            raise ValueError("Элемент управления вне окна")
        if any(self.canvas.contains(*p) for p in controls):
            raise ValueError("Кнопки палитры и кисти не должны находиться на холсте")
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
        estimate = estimate_plan(strokes, size, timing)
        return cls(size, strokes, timing, estimate, d["source_hash"],
                   [tuple(c) for c in d["palette"]], d.get("notes", []))


def estimate_plan(strokes: list[Stroke], size: tuple[int, int], timing: Timing) -> float:
    total = 0.0
    prev_color = prev_width = None
    for s in strokes:
        total += s.seconds(size, timing)
        if s.color != prev_color:
            total += timing.settle + 3 * timing.event
        if s.width != prev_width:
            total += timing.settle + 3 * timing.event
        prev_color, prev_width = s.color, s.width
    return total * 1.15  # Scheduling and color-verification reserve; still only an estimate.
