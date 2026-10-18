"""Explicit profile for the user's screenshots, not automatic UI detection."""
from dataclasses import replace

from app.automation import WindowState
from app.models import Brush, BrushSlider, Calibration, ColorWheel, Rect


PAID_AREAS = [Rect(654, 87, 111, 27), Rect(1165, 690, 201, 78)]
PROFILE_NAME = "Roblox · персонаж слева · 1366×768"
FREE_SLIDER_ADAPTER = "roblox-free-slider-v5"
LEGACY_ADAPTERS = {"roblox-free-slider-v1", "roblox-free-slider-v2", "roblox-free-slider-v3", "roblox-free-slider-v4"}


def opacity_slider():
    # Confirmed by user: left = 100%, right = 1%.
    return BrushSlider((720, 454), (590, 454), 1, 100, Rect(690, 419, 46, 21),
                       decrease=(747, 454), increase=(561, 454))


def screenshot_wheel():
    # Saturated hue is LEFT, white is RIGHT. Stay inside the rounded corners.
    return ColorWheel((644, 209), (643, 135), Rect(605, 170, 78, 79),
                      value_reset=(746, 132), mode_button=(573, 317), saturation_reversed=True, inset=3,
                      value_end=(746, 286))


def feedback_slider(slider):
    dx, dy = slider.start[0]-590, slider.start[1]-404
    return replace(slider, readout=Rect(698+dx, 370+dy, 38, 20),
                   decrease=(561+dx, 404+dy), increase=(747+dx, 404+dy))


def restrict_game_profile(profile: Calibration) -> bool:
    """Migrate the old screenshot preset before it can touch the paid size tab."""
    old_geometry = (profile.canvas == Rect(785, 114, 555, 555) and profile.color_wheel is not None
                    and profile.color_wheel.center == (644, 209))
    if profile.name != PROFILE_NAME and profile.adapter not in LEGACY_ADAPTERS | {FREE_SLIDER_ADAPTER} and not old_geometry:
        return False
    if profile.client_size != (1366, 768) or "roblox" not in profile.target_process.casefold():
        return False
    needs_fine_brush = (profile.brush_slider is None or profile.brush_slider.minimum == 1) and not any(
        b.pixels == 1 for b in profile.brushes)
    wrong_old_range = (profile.adapter == "roblox-free-slider-v1" and profile.brush_slider is not None
                       and (profile.brush_slider.minimum, profile.brush_slider.maximum) == (1, 100))
    needs_feedback = profile.brush_slider is None or profile.brush_slider.readout is None
    needs_color_check = (old_geometry and profile.color_indicator is None)
    update_geometry = (profile.adapter != FREE_SLIDER_ADAPTER and old_geometry)
    changed = (profile.brush_slider is None or profile.size_tab is not None or needs_feedback
               or profile.forbidden != PAID_AREAS or needs_fine_brush or wrong_old_range or needs_color_check
               or update_geometry)
    if update_geometry:
        profile.color_wheel = screenshot_wheel()
        profile.opacity_slider = opacity_slider()
        profile.color_tolerance = 25
        if profile.character == Rect(145, 250, 340, 500):
            profile.character = Rect(70, 215, 355, 465)
    if needs_color_check:
        profile.color_indicator = (565, 283)
    if profile.brush_slider is None:
        profile.brush_slider = BrushSlider((590, 404), (720, 404), 1, 256)
    elif wrong_old_range:
        profile.brush_slider = replace(profile.brush_slider, minimum=1, maximum=256)
    if needs_feedback:
        profile.brush_slider = feedback_slider(profile.brush_slider)
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
        brush_tool=(868, 720), character=Rect(70, 215, 355, 465),
        color_indicator=(565, 283), color_tolerance=25,
        color_wheel=screenshot_wheel(), opacity_slider=opacity_slider(),
        color_tab=(593, 100), brush_slider=feedback_slider(BrushSlider((590, 404), (720, 404), 1, 256)),
        forbidden=list(PAID_AREAS), adapter=FREE_SLIDER_ADAPTER)
    profile.validate()
    return profile


def selection_clicks(profile: Calibration) -> tuple[int, int]:
    wheel = profile.color_wheel
    color = 2 if wheel else 1  # Hue + square; tab/mode/brightness are session setup.
    return color, ((12 if profile.brush_slider.readout else 2)
                                               if profile.brush_slider else 1 + bool(profile.size_tab))
