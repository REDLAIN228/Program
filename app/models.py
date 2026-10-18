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
    saturation_reversed: bool = False
    inset: int = 0
    value_end: tuple[int, int] | None = None

    def points(self, rgb: RGB) -> list[tuple[int, int]]:
        if len(rgb) != 3 or any(not 0 <= c <= 255 for c in rgb):
            raise ValueError("Некорректный RGB")
        hue, saturation, value = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
        angle = hue * 2 * math.pi
        dx, dy = self.red[0] - self.center[0], self.red[1] - self.center[1]
        ring = (round(self.center[0] + dx * math.cos(angle) - dy * math.sin(angle)),
                round(self.center[1] + dx * math.sin(angle) + dy * math.cos(angle)))
        saturation = 1-saturation if self.saturation_reversed else saturation
        square = (round(self.square.x + saturation * (self.square.width - 1)),
                  round(self.square.y + (1 - value) * (self.square.height - 1)))
        square = tuple(max(start+self.inset, min(start+length-1-self.inset, coord))
                       for start, length, coord in zip((self.square.x, self.square.y),
                                                      (self.square.width, self.square.height), square))
        return [ring] + ([self.value_reset] if self.value_reset else []) + [square]


@dataclass(frozen=True)
class BrushSlider:
    start: tuple[int, int]
    end: tuple[int, int]
    minimum: int | None = None
    maximum: int | None = None
    readout: Rect | None = None
    decrease: tuple[int, int] | None = None
    increase: tuple[int, int] | None = None

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
    opacity_slider: BrushSlider | None = None  # Percent opacity, not transparency.

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
        for slider in [self.brush_slider, self.opacity_slider]:
            if slider is None:
                continue
            controls += [slider.start, slider.end]
            controls += [p for p in [slider.decrease, slider.increase] if p is not None]
            if slider.readout:
                r = slider.readout
                if r.width < 5 or r.height < 5:
                    raise ValueError("Слишком маленькая область числа размера кисти")
                controls += [(r.x, r.y), (r.x+r.width-1, r.y+r.height-1)]
                if slider.decrease is None or slider.increase is None:
                    raise ValueError("Для проверки размера нужны бесплатные стрелки ползунка")
            if math.dist(slider.start, slider.end) < 16:
                raise ValueError("Слишком короткий ползунок кисти")
            if (slider.minimum is None) != (slider.maximum is None):
                raise ValueError("Укажите обе границы диапазона ползунка")
            if slider.minimum is not None:
                if not 0 <= slider.minimum < slider.maximum <= 4096:
                    raise ValueError("Некорректный диапазон ползунка")
                if slider is self.brush_slider:
                    controls += [slider.point(b.pixels) for b in self.brushes]
        if self.color_wheel:
            wheel = self.color_wheel
            radius = math.dist(wheel.center, wheel.red)
            if radius < 8 or wheel.square.width < 8 or wheel.square.height < 8:
                raise ValueError("Некорректная геометрия цветового круга")
            if type(wheel.inset) is not int or not 0 <= wheel.inset < min(wheel.square.width, wheel.square.height)/2:
                raise ValueError("Некорректный отступ цветового квадрата")
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
            controls += [p for p in [wheel.value_reset, wheel.mode_button, wheel.value_end] if p is not None]
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
                                    tuple(d["color_wheel"]["mode_button"]) if d["color_wheel"].get("mode_button") else None,
                                    bool(d["color_wheel"].get("saturation_reversed", False)),
                                    d["color_wheel"].get("inset", 0),
                                    tuple(d["color_wheel"]["value_end"]) if d["color_wheel"].get("value_end") else None)
                         if d.get("color_wheel") else None),
            color_tab=tuple(d["color_tab"]) if d.get("color_tab") else None,
            size_tab=tuple(d["size_tab"]) if d.get("size_tab") else None,
            brush_slider=(BrushSlider(tuple(d["brush_slider"]["start"]), tuple(d["brush_slider"]["end"]),
                                      d["brush_slider"].get("minimum"), d["brush_slider"].get("maximum"),
                                      Rect(**d["brush_slider"]["readout"]) if d["brush_slider"].get("readout") else None,
                                      tuple(d["brush_slider"]["decrease"]) if d["brush_slider"].get("decrease") else None,
                                      tuple(d["brush_slider"]["increase"]) if d["brush_slider"].get("increase") else None)
                          if d.get("brush_slider") else None),
            forbidden=[Rect(**r) for r in d.get("forbidden", [])],
            adapter=d.get("adapter"),
            opacity_slider=(BrushSlider(tuple(d["opacity_slider"]["start"]), tuple(d["opacity_slider"]["end"]),
                                       d["opacity_slider"].get("minimum"), d["opacity_slider"].get("maximum"),
                                       Rect(**d["opacity_slider"]["readout"]) if d["opacity_slider"].get("readout") else None,
                                       tuple(d["opacity_slider"]["decrease"]) if d["opacity_slider"].get("decrease") else None,
                                       tuple(d["opacity_slider"]["increase"]) if d["opacity_slider"].get("increase") else None)
                            if d.get("opacity_slider") else None),
        )
        p.validate()
        return p


@dataclass(frozen=True)
class Timing:
    event: float = 0.012
    settle: float = 0.09
    pixels_per_second: float = 900
    sample_pixels: float = 5
    game_delay: float = .25

    @classmethod
    def preset(cls, name: str) -> Timing:
        return {"Slow": cls(.035, .35, 180, 2), "Safe": cls(.020, .15, 500, 4),
                "Normal": cls(), "Fast": cls(.008, .06, 1400, 6),
                "Turbo · 5": cls(.006, .05, 1800, 5),
                "Turbo · 6": cls(.005, .05, 2200, 5),
                "Turbo · 7": cls(.004, .05, 2600, 5)}[name]

    @property
    def control_speed(self) -> float:
        if self.pixels_per_second <= 1400:
            return min(600, self.pixels_per_second)
        return min(1400, 600+(self.pixels_per_second-1400)/1.5)

    @property
    def control_hold(self) -> float:
        return max(.105, self.event * 3, self.game_delay)

    @property
    def control_settle(self) -> float:
        return max(.35, self.settle, self.game_delay*2)

    def pen_event(self, width: int, feedback: bool = False) -> float:
        # A one-pixel corner must survive at least one 60 Hz game frame.
        return max(self.event, 1/(60 if width <= 2 else 120)) if feedback else self.event

    def pen_sample(self, width: int, feedback: bool = False) -> float:
        return min(self.sample_pixels, max(2, width)) if feedback else self.sample_pixels

    @property
    def pen_hold(self) -> float:
        return max(.035, self.event, self.game_delay)

    @property
    def pen_release(self) -> float:
        return max(.05, self.event, self.game_delay)


@dataclass(frozen=True)
class Stroke:
    points: tuple[Point, ...]
    color: RGB
    width: int
    opacity: float = 1.0
    priority: int = 0
    importance: float = 50.0
    component_id: int = -1

    def length(self, size: tuple[int, int]) -> float:
        w, h = size
        return sum(math.hypot((b[0] - a[0]) * w, (b[1] - a[1]) * h)
                   for a, b in zip(self.points, self.points[1:]))

    def seconds(self, size: tuple[int, int], timing: Timing, feedback: bool = False) -> float:
        length = self.length(size)
        samples = sum(max(1, math.ceil(math.hypot((b[0]-a[0])*size[0], (b[1]-a[1])*size[1])
                                      / timing.pen_sample(self.width, feedback)))
                      for a, b in zip(self.points, self.points[1:]))
        samples = max(1, samples)
        overhead = (timing.control_hold+2*timing.pen_hold+timing.pen_release if feedback else 4*timing.event)
        return samples * timing.pen_event(self.width, feedback) + length / timing.pixels_per_second + overhead


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
    drawing_rect: Rect | None = None  # Coordinates relative to the full canvas.
    target_canvas_size: tuple[int, int] | None = None
    engine: str = "Legacy"
    smart_finish: bool = False
    safety_buffer: float = 0.0
    time_factor: float = 1.0
    metrics: dict = field(default_factory=dict)
    analysis: dict = field(default_factory=dict)

    def drawing_area(self, canvas: Rect) -> Rect:
        if self.drawing_rect is None and self.target_canvas_size is None:
            if self.canvas_size != (canvas.width, canvas.height):
                raise ValueError("План создан для другого размера холста. Выполните PREVIEW заново.")
            return canvas
        r = self.drawing_rect
        if r is None or self.target_canvas_size != (canvas.width, canvas.height):
            raise ValueError("Формат рисунка относится к другому холсту. Выполните PREVIEW заново.")
        if (any(type(n) is not int for n in (r.x, r.y, r.width, r.height))
                or (r.width, r.height) != self.canvas_size or min(r.width, r.height) < 32
                or r.x < 0 or r.y < 0 or r.x+r.width > canvas.width or r.y+r.height > canvas.height):
            raise ValueError("Размер или положение рисунка выходит за границы холста")
        return Rect(canvas.x+r.x, canvas.y+r.y, r.width, r.height)

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
            opacity = s.get("opacity", 1.)
            if (not 1 <= s["width"] < min(size) or not math.isfinite(opacity)
                    or not .01 <= opacity <= 1):
                raise ValueError("Неподдерживаемая кисть или прозрачность")
            importance = s.get("importance", 50.)
            if not math.isfinite(importance) or not 0 <= importance <= 100:
                raise ValueError("Некорректный приоритет детали")
            component = s.get("component_id", -1)
            if type(component) is not int or not -1 <= component <= 2**31-1:
                raise ValueError("Некорректная связная область штриха")
            strokes.append(Stroke(points, rgb, s["width"], opacity, s.get("priority", 0), importance, component))
        timing = Timing(**d["timing"])
        if any(not math.isfinite(v) or v <= 0 for v in asdict(timing).values()):
            raise ValueError("Некорректные интервалы")
        color_clicks, brush_clicks = d.get("color_clicks", 1), d.get("brush_clicks", 1)
        if any(type(n) is not int or not 1 <= n <= 12 for n in [color_clicks, brush_clicks]):
            raise ValueError("Некорректное число нажатий элементов управления")
        estimate = estimate_plan(strokes, size, timing, color_clicks, brush_clicks)
        plan = cls(size, strokes, timing, estimate, d["source_hash"],
                   [tuple(c) for c in d["palette"]], d.get("notes", []),
                   color_clicks=color_clicks, brush_clicks=brush_clicks,
                   drawing_rect=Rect(**d["drawing_rect"]) if d.get("drawing_rect") is not None else None,
                   target_canvas_size=tuple(d["target_canvas_size"]) if d.get("target_canvas_size") is not None else None,
                   engine=d.get("engine", "Legacy"), smart_finish=bool(d.get("smart_finish", False)),
                   safety_buffer=d.get("safety_buffer", 0.), time_factor=d.get("time_factor", 1.),
                   metrics=d.get("metrics", {}), analysis=d.get("analysis", {}))
        if (not math.isfinite(plan.time_factor) or not .1 <= plan.time_factor <= 20
                or not math.isfinite(plan.safety_buffer) or not 0 <= plan.safety_buffer <= 60):
            raise ValueError("Некорректная настройка таймера")
        if plan.engine not in ("Legacy", "Vector 2.0") or not isinstance(plan.metrics, dict) or not isinstance(plan.analysis, dict):
            raise ValueError("Некорректные данные движка или анализа")
        plan.estimated_seconds *= plan.time_factor
        if plan.target_canvas_size is not None or plan.drawing_rect is not None:
            target = plan.target_canvas_size
            if (target is None or len(target) != 2 or any(type(n) is not int or not 32 <= n <= 8192 for n in target)):
                raise ValueError("Некорректный размер целевого холста")
            plan.drawing_area(Rect(0, 0, *target))
        return plan


def estimate_plan(strokes: list[Stroke], size: tuple[int, int], timing: Timing,
                  color_clicks: int = 1, brush_clicks: int = 1) -> float:
    total = 0.0
    prev_color = prev_width = prev_end = prev_opacity = None
    for s in strokes:
        feedback_controls = brush_clicks == 12
        total += s.seconds(size, timing, feedback_controls)
        # The feedback adapter paces mouse-up travel and verifies size again
        # after each color change. UI travel uses a nominal 200 px per click;
        # this remains an estimate, not recognition of the game's round timer.
        click_seconds = (2*timing.control_hold + timing.control_settle + 200/timing.control_speed
                         if feedback_controls else timing.settle + 3*timing.event)
        if feedback_controls and prev_color is None:
            total += 3*click_seconds  # Open tab, wheel mode, brightness once.
        if s.color != prev_color:
            total += color_clicks * click_seconds
            if feedback_controls:
                # HSV gestures send held movement as well as press/release.
                total += 30*max(.025, timing.game_delay/4)
        if feedback_controls:
            if prev_width is None or abs(s.width-prev_width) > 8:
                total += brush_clicks*click_seconds
            elif s.width != prev_width:
                total += abs(s.width-prev_width)*click_seconds
            if s.width != prev_width or s.color != prev_color:
                total += timing.control_settle/2  # Confirm the number; no extra tab clicks.
        elif s.width != prev_width:
            total += brush_clicks*click_seconds
        if feedback_controls and s.opacity != prev_opacity:
            total += 2*click_seconds
        elif feedback_controls and s.opacity != 1 and s.color != prev_color:
            total += 4*click_seconds  # Verify new hue at 100%, restore opacity.
        if feedback_controls:
            if prev_end is None or s.color != prev_color or s.width != prev_width:
                total += size[0]/timing.control_speed  # Return from controls to canvas.
            else:
                total += math.hypot((s.points[0][0]-prev_end[0])*size[0],
                                    (s.points[0][1]-prev_end[1])*size[1])/timing.control_speed
        prev_color, prev_width = s.color, s.width
        prev_opacity = s.opacity
        prev_end = s.points[-1]
    return total * 1.15  # Scheduling and color-verification reserve; still only an estimate.
