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


def test_numeric_keyboard_packets_select_replace_and_commit_without_clipboard(monkeypatch):
    import app.windows as native
    packets, guards, waits = [], [], []
    def send(count, pointer, size):
        event = ctypes.cast(pointer, ctypes.POINTER(INPUT)).contents
        assert event.type == 1
        packets.append((event.ki.wVk, event.ki.dwFlags))
        return 1
    monkeypatch.setattr(native, "user32", SimpleNamespace(SendInput=send), raising=False)
    backend = native.Win32Backend.__new__(native.Win32Backend)
    backend._lock = threading.Lock()
    backend.replace_number(32, lambda: guards.append(True), waits.append)
    assert packets == [(0x11, 0), (0x41, 0), (0x41, 2), (0x11, 2),
                       (ord("3"), 0), (ord("3"), 2), (ord("2"), 0), (ord("2"), 2),
                       (0x0D, 0), (0x0D, 2)]
    assert len(guards) == 5 and len(waits) == 5


def test_numeric_keyboard_releases_control_when_stop_interrupts_input(monkeypatch):
    import app.windows as native
    packets = []
    backend = native.Win32Backend.__new__(native.Win32Backend)
    backend._key = lambda vk, up=False: packets.append((vk, up))
    def stop(seconds):
        raise InterruptedError("F9")
    with pytest.raises(InterruptedError, match="F9"):
        backend.replace_number(255, lambda: None, stop)
    assert packets == [(0x11, False), (0x11, True)]
    with pytest.raises(ValueError):
        backend.replace_number("255\n", lambda: None, lambda _: None)
