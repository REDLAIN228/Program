"""Explicit profile for the user's screenshots, not automatic UI detection."""
from dataclasses import replace

from app.automation import WindowState
from app.models import Brush, BrushSlider, Calibration, ColorWheel, Rect


PAID_AREAS = [Rect(654, 87, 111, 27), Rect(1165, 690, 201, 78)]
PROFILE_NAME = "Roblox · персонаж слева · 1366×768"
FREE_SLIDER_ADAPTER = "roblox-free-slider-v2"


def restrict_game_profile(profile: Calibration) -> bool:
    """Migrate the old screenshot preset before it can touch the paid size tab."""
    old_geometry = (profile.canvas == Rect(785, 114, 555, 555) and profile.color_wheel is not None
                    and profile.color_wheel.center == (644, 209))
    if profile.name != PROFILE_NAME and profile.adapter not in {"roblox-free-slider-v1", FREE_SLIDER_ADAPTER} and not old_geometry:
        return False
    if profile.client_size != (1366, 768) or "roblox" not in profile.target_process.casefold():
        return False
    needs_fine_brush = (profile.brush_slider is None or profile.brush_slider.minimum == 1) and not any(
        b.pixels == 1 for b in profile.brushes)
    wrong_old_range = (profile.adapter != FREE_SLIDER_ADAPTER and profile.brush_slider is not None
                       and (profile.brush_slider.minimum, profile.brush_slider.maximum) == (1, 100))
    changed = (profile.brush_slider is None or profile.size_tab is not None
               or profile.forbidden != PAID_AREAS or needs_fine_brush or wrong_old_range)
    if profile.brush_slider is None:
        profile.brush_slider = BrushSlider((590, 404), (720, 404), 1, 256)
    elif wrong_old_range:
        profile.brush_slider = replace(profile.brush_slider, minimum=1, maximum=256)
    profile.size_tab = None
    profile.forbidden = list(PAID_AREAS)
    profile.adapter = FREE_SLIDER_ADAPTER
    if changed:
        profile.brushes = [Brush(b.pixels, profile.brush_slider.start) for b in profile.brushes]
        if needs_fine_brush:
            profile.brushes.insert(0, Brush(1, profile.brush_slider.start))
        profile.verified = False
    return changed


def screenshot_profile(state: WindowState) -> Calibration:
    if (state.client.width, state.client.height) != (1366, 768):
        raise ValueError("Этот шаблон рассчитан на игровую область 1366×768 при увеличении холста 100%. "
                         "Текущий размер другой: нужна ручная калибровка, координаты не масштабируются наугад.")
    if "roblox" not in state.process.casefold():
        raise ValueError("Выберите окно Roblox, прежде чем применять игровой шаблон.")
    profile = Calibration(
        PROFILE_NAME, state.window_class, state.process, (1366, 768), state.dpi,
        Rect(785, 114, 555, 555), [],
        [Brush(n, (590, 404)) for n in (1, 2, 6, 16, 32, 64)],
        brush_tool=(868, 720), character=Rect(145, 250, 340, 500),
        color_wheel=ColorWheel((644, 209), (643, 135), Rect(606, 171, 75, 76),
                               value_reset=(746, 132), mode_button=(573, 317)),
        color_tab=(593, 100), brush_slider=BrushSlider((590, 404), (720, 404), 1, 256),
        forbidden=list(PAID_AREAS), adapter=FREE_SLIDER_ADAPTER)
    profile.validate()
    return profile


def selection_clicks(profile: Calibration) -> tuple[int, int]:
    wheel = profile.color_wheel
    color = ((2 + bool(wheel.value_reset) + bool(wheel.mode_button)) if wheel else 1)
    return int(color + bool(profile.color_tab)), (2 if profile.brush_slider else 1 + bool(profile.size_tab))
