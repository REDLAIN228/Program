"""Explicit profile for the user's screenshots, not automatic UI detection."""
from app.automation import WindowState
from app.models import Brush, BrushSlider, Calibration, ColorWheel, Rect


PAID_AREAS = [Rect(654, 87, 111, 27), Rect(1165, 690, 201, 78)]
PROFILE_NAME = "Roblox · персонаж слева · 1366×768"


def restrict_game_profile(profile: Calibration) -> bool:
    """Migrate the old screenshot preset before it can touch the paid size tab."""
    old_geometry = (profile.canvas == Rect(785, 114, 555, 555) and profile.color_wheel is not None
                    and profile.color_wheel.center == (644, 209))
    if profile.name != PROFILE_NAME and profile.adapter != "roblox-free-slider-v1" and not old_geometry:
        return False
    if profile.client_size != (1366, 768) or "roblox" not in profile.target_process.casefold():
        return False
    changed = profile.brush_slider is None or profile.size_tab is not None or profile.forbidden != PAID_AREAS
    if profile.brush_slider is None:
        profile.brush_slider = BrushSlider((590, 404), (720, 404), 1, 100)
    profile.size_tab = None
    profile.forbidden = list(PAID_AREAS)
    profile.adapter = "roblox-free-slider-v1"
    if changed:
        profile.brushes = [Brush(b.pixels, profile.brush_slider.start) for b in profile.brushes]
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
        [Brush(n, (590, 404)) for n in (2, 6, 16, 32, 64)],
        brush_tool=(868, 720), character=Rect(145, 250, 340, 500),
        color_wheel=ColorWheel((644, 209), (643, 135), Rect(606, 171, 75, 76),
                               value_reset=(746, 132), mode_button=(573, 317)),
        color_tab=(593, 100), brush_slider=BrushSlider((590, 404), (720, 404), 1, 100),
        forbidden=list(PAID_AREAS), adapter="roblox-free-slider-v1")
    profile.validate()
    return profile


def selection_clicks(profile: Calibration) -> tuple[int, int]:
    wheel = profile.color_wheel
    color = ((2 + bool(wheel.value_reset) + bool(wheel.mode_button)) if wheel else 1)
    return int(color + bool(profile.color_tab)), (2 if profile.brush_slider else 1 + bool(profile.size_tab))
