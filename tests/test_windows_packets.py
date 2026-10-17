import ctypes

import pytest

from app.automation import SafetyError
from app.models import Rect
from app.windows import INPUT, MOUSEINPUT, normalize_absolute


def test_windows_sendinput_packet_layout_and_construction():
    expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    assert ctypes.sizeof(INPUT) == expected
    assert ctypes.sizeof(MOUSEINPUT) == (32 if expected == 40 else 24)
    event = INPUT(type=0, mi=MOUSEINPUT(65535, 0, 0, 0xC001, 0, 0))
    assert event.mi.dx == 65535
    assert event.mi.dwFlags == 0xC001


def test_absolute_mouse_coordinates_span_multiple_monitors():
    desktop = Rect(-1920, -200, 3840, 1280)
    assert normalize_absolute(-1920, -200, desktop) == (0, 0)
    assert normalize_absolute(1919, 1079, desktop) == (65535, 65535)
    x, y = normalize_absolute(0, 0, desktop)
    assert 32760 < x < 32790
    assert 10000 < y < 11000
    with pytest.raises(SafetyError):
        normalize_absolute(1920, 0, desktop)
