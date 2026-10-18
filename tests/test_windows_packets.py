import ctypes
import threading
from types import SimpleNamespace

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


def test_native_press_carries_position_and_moves_are_not_coalesced(monkeypatch):
    import app.windows as native
    packets = []

    def send(count, pointer, size):
        event = ctypes.cast(pointer, ctypes.POINTER(INPUT)).contents.mi
        packets.append((event.dx, event.dy, event.dwFlags))
        return 1

    monkeypatch.setattr(native, "user32", SimpleNamespace(
        GetSystemMetrics=lambda index: {76: -1920, 77: 0, 78: 3840, 79: 1080}[index],
        SendInput=send), raising=False)
    backend = native.Win32Backend.__new__(native.Win32Backend)
    backend._lock = threading.Lock()
    backend.move(100, 200)
    backend.down_at(100, 200)
    backend.up()
    expected = normalize_absolute(100, 200, Rect(-1920, 0, 3840, 1080))
    assert packets == [(*expected, 0xE001), (*expected, 0xE003), (0, 0, 0x0004)]


def test_positioned_press_reports_rejected_input(monkeypatch):
    import app.windows as native
    monkeypatch.setattr(native, "user32", SimpleNamespace(
        GetSystemMetrics=lambda index: {76: 0, 77: 0, 78: 1366, 79: 768}[index],
        SendInput=lambda *args: 0), raising=False)
    backend = native.Win32Backend.__new__(native.Win32Backend)
    backend._lock = threading.Lock()
    with pytest.raises(SafetyError, match="SendInput"):
        backend.down_at(100, 200)
