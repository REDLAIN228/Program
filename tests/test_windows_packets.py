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


def test_numeric_keyboard_packets_clear_replace_and_commit_without_clipboard(monkeypatch):
    import app.windows as native
    packets, guards, waits = [], [], []
    def send(count, pointer, size):
        event = ctypes.cast(pointer, ctypes.POINTER(INPUT)).contents
        assert event.type == 1
        packets.append((event.ki.wVk, event.ki.wScan, event.ki.dwFlags))
        return 1
    monkeypatch.setattr(native, "user32", SimpleNamespace(SendInput=send), raising=False)
    backend = native.Win32Backend.__new__(native.Win32Backend)
    backend._lock = threading.Lock()
    backend.replace_number(32, lambda: guards.append(True), waits.append)
    assert packets == ([(0, 0x4F, 9), (0, 0x4F, 11)]+[(0, 0x0E, 8), (0, 0x0E, 10)]*8
                       +[(0, 0x53, 9), (0, 0x53, 11)]+[(0, 0x4F, 9), (0, 0x4F, 11),
                       (ord("3"), 0, 0), (ord("3"), 0, 2), (ord("2"), 0, 0), (ord("2"), 0, 2),
                       (0, 0x1C, 8), (0, 0x1C, 10)])
    assert len(guards) == 14 and waits == [.025]*28
    assert sum(waits) < .8  # Previously 1.47 s just for the key-edge waits.


@pytest.mark.parametrize("stop_at", [1, 3, 5, 19])
def test_numeric_keyboard_releases_editing_keys_when_stop_interrupts_input(monkeypatch, stop_at):
    import app.windows as native
    packets = []
    backend = native.Win32Backend.__new__(native.Win32Backend)
    backend._key = lambda vk, up=False: packets.append((vk, up))
    waits = []
    def stop(seconds):
        waits.append(seconds)
        if len(waits) == stop_at:
            raise InterruptedError("F9")
    with pytest.raises(InterruptedError, match="F9"):
        backend.replace_number(255, lambda: None, stop)
    held = set()
    for vk, up in packets:
        if up:
            held.discard(vk)
        else:
            held.add(vk)
    assert not held
    assert not any(vk == 0x0D for vk, _ in packets)  # Never commit after cancellation.
    with pytest.raises(ValueError):
        backend.replace_number("255\n", lambda: None, lambda _: None)


class TextBoxIgnoringSelectAll:
    def __init__(self, text, caret):
        self.text, self.caret = text, caret
        self.before_digits = []

    def key(self, vk, up=False):
        if up:
            return
        if vk == 0x23:
            self.caret = len(self.text)
        elif vk == 0x08 and self.caret:
            self.text = self.text[:self.caret-1]+self.text[self.caret:]
            self.caret -= 1
        elif vk == 0x2E:
            self.text = self.text[:self.caret]+self.text[self.caret+1:]
        elif ord("0") <= vk <= ord("9"):
            self.before_digits.append(self.text)
            self.text = self.text[:self.caret]+chr(vk)+self.text[self.caret:]
            self.caret += 1
        # Ctrl+A is deliberately ignored, as reported by the user.


def test_ignored_select_all_reproduces_uploaded_0255_value():
    box = TextBoxIgnoringSelectAll("255", 0)
    for vk in (0x11, 0x41, ord("0"), 0x0D):
        box.key(vk)
    assert box.text == "0255"


@pytest.mark.parametrize("old,caret,number", [("255", 0, 0), ("0255", 2, 128), ("0", 0, 255),
                                               ("2552550", 4, 32), ("99999999", 1, 1)])
def test_number_is_cleared_before_typing_even_when_select_all_is_ignored(old, caret, number):
    from app.windows import Win32Backend
    box = TextBoxIgnoringSelectAll(old, caret)
    backend = Win32Backend.__new__(Win32Backend)
    backend._key = box.key
    backend.replace_number(number, lambda: None, lambda _: None)
    assert box.before_digits[0] == ""
    assert box.text == str(number)


def test_number_box_restoring_zero_does_not_append_zero_to_new_value():
    from app.windows import Win32Backend
    class RestoresZero(TextBoxIgnoringSelectAll):
        def key(self, vk, up=False):
            super().key(vk, up)
            if self.text == "":
                self.text, self.caret = "0", 0
    box = RestoresZero("255", 0)
    backend = Win32Backend.__new__(Win32Backend)
    backend._key = box.key
    backend.replace_number(128, lambda: None, lambda _: None)
    assert int(box.text) == 128


def test_scan_code_edit_keys_clear_target_that_ignores_virtual_edit_keys(monkeypatch):
    import app.windows as native
    box = TextBoxIgnoringSelectAll("0255", 0)
    def send(count, pointer, size):
        event = ctypes.cast(pointer, ctypes.POINTER(INPUT)).contents.ki
        if event.dwFlags & 8:
            vk = {0x4F: 0x23, 0x0E: 0x08, 0x53: 0x2E, 0x1C: 0x0D}[event.wScan]
        elif event.wVk in (0x23, 0x08, 0x2E):
            return 1  # OS accepted the VK packet; this modeled game ignores it.
        else:
            vk = event.wVk
        box.key(vk, bool(event.dwFlags & 2))
        return 1
    monkeypatch.setattr(native, "user32", SimpleNamespace(SendInput=send), raising=False)
    backend = native.Win32Backend.__new__(native.Win32Backend)
    backend._lock = threading.Lock()
    backend.replace_number(128, lambda: None, lambda _: None)
    assert box.before_digits[0] == "" and box.text == "128"


def test_delete_type_enter_is_one_transaction_with_no_empty_field_gate():
    from app.windows import Win32Backend
    box = TextBoxIgnoringSelectAll("0255", 0)
    packets = []
    def key(vk, up=False):
        packets.append((vk, up))
        box.key(vk, up)
    backend = Win32Backend.__new__(Win32Backend)
    backend._key = key
    backend.replace_number(128, lambda: None, lambda _: None)
    assert box.text == "128" and box.before_digits[0] == ""
    assert packets[-2:] == [(0x0D, False), (0x0D, True)]


def test_mouse_selection_is_deleted_before_end_can_collapse_it():
    from app.windows import Win32Backend
    class SelectedBox(TextBoxIgnoringSelectAll):
        selection = True
        def key(self, vk, up=False):
            if not up and self.selection:
                if vk == 0x08:
                    self.text, self.caret, self.selection = "", 0, False
                    return
                if vk == 0x23:
                    self.selection = False
            super().key(vk, up)
    box = SelectedBox("255"*10, 0)
    backend = Win32Backend.__new__(Win32Backend)
    backend._key = box.key
    backend.replace_number(128, lambda: None, lambda _: None, selected=True)
    assert box.text == "128" and box.before_digits[0] == ""
