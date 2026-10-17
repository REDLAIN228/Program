"""Explicit profile for the user's screenshots, not automatic UI detection."""
from app.automation import WindowState
from app.models import Brush, Calibration, ColorWheel, Rect


def screenshot_profile(state: WindowState) -> Calibration:
    if (state.client.width, state.client.height) != (1366, 768):
        raise ValueError("Этот шаблон рассчитан на игровую область 1366×768 при увеличении холста 100%. "
                         "Текущий размер другой: нужна ручная калибровка, координаты не масштабируются наугад.")
    if "roblox" not in state.process.casefold():
        raise ValueError("Выберите окно Roblox, прежде чем применять игровой шаблон.")
    profile = Calibration(
        "Roblox · персонаж слева · 1366×768", state.window_class, state.process, (1366, 768), state.dpi,
        Rect(785, 114, 555, 555), [],
        [Brush(2, (628, 143)), Brush(6, (628, 200)), Brush(16, (576, 316)),
         Brush(32, (681, 373)), Brush(64, (733, 430))],
        brush_tool=(868, 720), character=Rect(145, 250, 340, 500),
        color_wheel=ColorWheel((644, 209), (643, 135), Rect(606, 171, 75, 76),
                               value_reset=(746, 132), mode_button=(573, 317)),
        color_tab=(593, 100), size_tab=(705, 100))
    profile.validate()
    return profile


def selection_clicks(profile: Calibration) -> tuple[int, int]:
    wheel = profile.color_wheel
    color = ((2 + bool(wheel.value_reset) + bool(wheel.mode_button)) if wheel else 1)
    return int(color + bool(profile.color_tab)), 1 + bool(profile.size_tab)
