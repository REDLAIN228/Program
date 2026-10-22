"""Win32 backend. No process memory access, injection, drivers or protection bypass."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import PureWindowsPath
import threading
import time

from app.automation import FieldNotCleared, SafetyError, WindowState
from app.models import Rect


def _require_windows():
    if os.name != "nt":
        raise OSError("Управление внешними окнами доступно только на Windows")


# Explicit Windows field widths let packet layout be tested on non-Windows hosts too.
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_uint32), ("wParamL", ctypes.c_uint16), ("wParamH", ctypes.c_uint16)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", ctypes.c_uint32), ("data", INPUTUNION)]


def normalize_absolute(x: int, y: int, desktop: Rect) -> tuple[int, int]:
    if not desktop.contains(x, y) or desktop.width < 2 or desktop.height < 2:
        raise SafetyError("Точка за границей виртуального рабочего стола")
    return (round((x-desktop.x)*65535/(desktop.width-1)),
            round((y-desktop.y)*65535/(desktop.height-1)))


if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                  wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = wintypes.UINT

    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL


def enable_dpi_awareness() -> None:
    if os.name == "nt":
        user32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2


def window_state(hwnd: int) -> WindowState:
    _require_windows()
    if not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        raise SafetyError("Целевое окно закрыто или свёрнуто")
    rect = wintypes.RECT()
    origin = wintypes.POINT(0, 0)
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)) or not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise SafetyError("Не удалось получить координаты окна")
    title, cls = ctypes.create_unicode_buffer(512), ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, len(title))
    user32.GetClassNameW(hwnd, cls, len(cls))
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # Query limited information only.
    name = ctypes.create_unicode_buffer(32768)
    length = wintypes.DWORD(len(name))
    try:
        if not handle or not kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)):
            raise SafetyError("Не удалось проверить имя процесса целевого окна")
        process = PureWindowsPath(name.value).name
    finally:
        if handle:
            kernel32.CloseHandle(handle)
    return WindowState(hwnd, title.value, cls.value, process,
                       Rect(origin.x, origin.y, rect.right, rect.bottom), user32.GetDpiForWindow(hwnd))


def list_windows() -> list[WindowState]:
    _require_windows()
    result = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            try:
                state = window_state(hwnd)
                if state.title and state.client.width >= 200 and state.client.height >= 150:
                    result.append(state)
            except SafetyError:
                pass
        return True

    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    if not user32.EnumWindows(callback, 0):
        raise OSError("EnumWindows failed")
    return sorted(result, key=lambda s: ("roblox" not in s.process.lower(), s.title))


def focus_window(hwnd: int) -> None:
    _require_windows()
    user32.ShowWindow(hwnd, 9)
    if not user32.SetForegroundWindow(hwnd):
        raise SafetyError("Windows не разрешила активировать окно. Выберите его вручную и повторите.")


def capture_client(state: WindowState):
    import mss
    from PIL import Image
    with mss.mss() as capture:
        shot = capture.grab({"left": state.client.x, "top": state.client.y,
                             "width": state.client.width, "height": state.client.height})
        return Image.frombytes("RGB", shot.size, shot.rgb)


class Win32Backend:
    def __init__(self, hwnd: int):
        _require_windows()
        self.hwnd = hwnd
        self._lock = threading.Lock()

    def snapshot(self):
        return window_state(self.hwnd)

    def is_foreground(self):
        return user32.GetForegroundWindow() == self.hwnd

    def point_belongs_to_target(self, x, y):
        hwnd = user32.WindowFromPoint(wintypes.POINT(x, y))
        return user32.GetAncestor(hwnd, 2) == self.hwnd  # GA_ROOT

    def _send(self, flags: int, x: int = 0, y: int = 0):
        event = INPUT(type=0, mi=MOUSEINPUT(x, y, 0, flags, 0, 0))
        with self._lock:
            if user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
                raise SafetyError("Windows отклонила SendInput (например, разные уровни прав). "
                                  "Запустите окна с одинаковыми правами; обход защиты не поддерживается.")

    def move(self, x, y):
        self._move_packet(x, y)

    def _move_packet(self, x, y, button=0):
        sx, sy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        sw, sh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        ax, ay = normalize_absolute(x, y, Rect(sx, sy, sw, sh))
        # Preserve ordered movement messages at pen boundaries. GetCursorPos
        # alone does not say which coalesced move the application has consumed.
        self._send(0x8000 | 0x4000 | 0x2000 | 0x0001 | button, ax, ay)

    def down_at(self, x, y):
        # The button event carries its own position, rather than depending on
        # the application's last processed standalone mouse-move message.
        self._move_packet(x, y, 0x0002)

    def cursor_position(self):
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            raise SafetyError("Windows не вернула положение курсора")
        return point.x, point.y

    def down(self):
        self._send(0x0002)

    def up(self):
        self._send(0x0004)

    def _key(self, vk, up=False):
        # The game's text entry can accept printable VK events while ignoring
        # edit keys lacking a hardware scan code. Use ordinary SendInput scan
        # packets for editing/commit; printable digits keep the existing VK path.
        editing = {0x08: (0x0E, False), 0x0D: (0x1C, False),
                   0x23: (0x4F, True), 0x2E: (0x53, True)}
        scan, extended = editing.get(vk, (0, False))
        flags = (0x0008 if scan else 0) | int(extended) | (0x0002 if up else 0)
        event = INPUT(type=1, ki=KEYBDINPUT(0 if scan else vk, scan, flags, 0, 0))
        with self._lock:
            if user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
                raise SafetyError("Windows отклонила ввод числа через SendInput")

    def replace_number(self, number, guard, wait, *, confirm_cleared=None, selected=False):
        if type(number) is not int or not 0 <= number <= 999:
            raise ValueError("Допускаются только целые числа 0–999")
        held = []

        def down(vk):
            guard()
            held.append(vk)
            self._key(vk)
            wait(.035)

        def up(vk):
            self._key(vk, True)
            held.remove(vk)
            wait(.035)  # Give the game a frame with the key released before repeating it.

        try:
            # Roblox TextBoxes may ignore Ctrl+A. The field is clicked on its
            # right side; End plus explicit deletion also repairs concatenated
            # values such as "0255" from previous attempts.
            if not selected:
                down(0x23)
                up(0x23)
            for vk in (0x08,)*8+(0x2E,)*8:
                down(vk)
                up(vk)
            if confirm_cleared is not None:
                guard()
                if not confirm_cleared():
                    raise FieldNotCleared("Старое число не удалено. Новое число не вводилось.")
            # Some numeric boxes restore "0" when emptied. Keep that default
            # before the new digits, rather than appending it to their end.
            down(0x23)
            up(0x23)
            for digit in str(number):
                down(ord(digit))
                up(ord(digit))
            down(0x0D)  # Commit the TextBox and release keyboard focus.
            up(0x0D)
        finally:
            for vk in reversed(held):
                self._key(vk, True)

    def sample(self, x, y):
        import mss
        with mss.mss() as capture:
            shot = capture.grab({"left": x, "top": y, "width": 1, "height": 1})
            return tuple(shot.rgb[:3])

    def slider_thumb(self, start, end):
        import mss
        from PIL import Image
        from app.slider import blue_thumb
        if start[1] != end[1]:
            return None
        left, top = min(start[0], end[0])-10, start[1]
        with mss.mss() as capture:
            shot = capture.grab({"left": left, "top": top,
                                 "width": abs(end[0]-start[0])+21, "height": 1})
        return blue_thumb(Image.frombytes("RGB", shot.size, shot.rgb), (left, top))

    def color_control_marker(self, wheel, kind):
        import math
        import mss
        from PIL import Image
        from app.slider import white_marker
        state = self.snapshot()
        if kind == "square":
            r = wheel.square
            area = Rect(r.x-6, r.y-6, r.width+12, r.height+12)
            allowed = lambda point: r.contains(*point)
        elif kind == "hue":
            cx, cy = wheel.center
            radius = math.dist(wheel.center, wheel.red)
            side = math.ceil(radius)+8
            area = Rect(cx-side, cy-side, 2*side+1, 2*side+1)
            allowed = lambda point: abs(math.dist(point, wheel.center)-radius) <= 6
        elif kind == "value" and wheel.value_end and wheel.value_reset:
            x, y = wheel.value_reset
            bottom = wheel.value_end[1]
            area = Rect(x-8, min(y, bottom)-7, 17, abs(bottom-y)+15)
            allowed = lambda point: abs(point[0]-x) <= 3
        else:
            return None
        if (area.x < 0 or area.y < 0 or area.x+area.width > state.client.width
                or area.y+area.height > state.client.height):
            return None
        with mss.mss() as capture:
            shot = capture.grab({"left": state.client.x+area.x, "top": state.client.y+area.y,
                                 "width": area.width, "height": area.height})
        return white_marker(Image.frombytes("RGB", shot.size, shot.rgb), (area.x, area.y), allowed)

    def read_brush_size(self, region):
        import mss
        from PIL import Image
        from app.size_ocr import read_size
        with mss.mss() as capture:
            shot = capture.grab({"left": region.x, "top": region.y,
                                 "width": region.width, "height": region.height})
        self._size_image = Image.frombytes("RGB", shot.size, shot.rgb)
        self._size_region = region
        value = read_size(self._size_image)
        self._size_values = (getattr(self, "_size_values", [])+[value])[-12:]
        return value

    def read_opacity(self, region):
        import mss
        from PIL import Image
        from app.size_ocr import read_percent
        with mss.mss() as capture:
            shot = capture.grab({"left": region.x, "top": region.y,
                                 "width": region.width, "height": region.height})
        self._opacity_image = Image.frombytes("RGB", shot.size, shot.rgb)
        return read_percent(self._opacity_image)

    def read_numeric_size(self, region):
        import mss
        from PIL import Image
        from app.size_ocr import read_numeric_size
        with mss.mss() as capture:
            shot = capture.grab({"left": region.x, "top": region.y,
                                 "width": region.width, "height": region.height})
        self._size_image = Image.frombytes("RGB", shot.size, shot.rgb)
        self._size_region = region
        value = read_numeric_size(self._size_image)
        self._size_values = (getattr(self, "_size_values", [])+[value])[-12:]
        return value

    def read_number_field(self, region, dark_text):
        import mss
        from PIL import Image
        from app.size_ocr import number_field_state
        with mss.mss() as capture:
            shot = capture.grab({"left": region.x, "top": region.y,
                                 "width": region.width, "height": region.height})
        self._field_image = Image.frombytes("RGB", shot.size, shot.rgb)
        return number_field_state(self._field_image, dark_text)

    def save_control_diagnostic(self, profile, details):
        from app.storage import data_directory, write_json
        directory = data_directory()/"logs"
        directory.mkdir(parents=True, exist_ok=True)
        state = self.snapshot()
        if profile.client_size == (1366, 768) and profile.color_wheel:
            image = capture_client(state).crop((545, 85, 765, 580))
            image.save(directory/"controls.png")
        elif profile.popup_controls:
            image = capture_client(state).crop((398, 40, 970, 730))
            image.save(directory/"controls.png")
        if getattr(self, "_field_image", None) is not None:
            self._field_image.save(directory/"number-field.png")
        write_json(directory/"controls.json", {**details, "profile": profile.to_dict()})
        return str(directory/"controls.json")

    def save_size_diagnostic(self, expected, observed):
        from app.storage import data_directory, write_json
        directory = data_directory()/"logs"
        directory.mkdir(parents=True, exist_ok=True)
        if getattr(self, "_size_image", None) is not None:
            self._size_image.save(directory/"brush-size.png")
        from dataclasses import asdict
        state = self.snapshot()
        region = getattr(self, "_size_region", None)
        write_json(directory/"brush-size.json", {
            "expected": expected, "observed": observed,
            "recent_readings": getattr(self, "_size_values", []),
            "screen_region": asdict(region) if region else None,
            "client": asdict(state.client), "dpi": state.dpi,
        })
        return str(directory/"brush-size.png")


class GlobalHotkeys:
    """F8 pause/resume, F9 emergency stop. Registration must succeed before RUN."""

    def __init__(self, pause, stop):
        self.pause, self.stop = pause, stop
        self.closed = threading.Event()
        self.ready = threading.Event()
        self.error = None
        self.thread = None

    def start(self):
        _require_windows()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="hotkeys")
        self.thread.start()
        if not self.ready.wait(3):
            raise SafetyError("Не удалось запустить глобальные горячие клавиши")
        if self.error:
            raise SafetyError(self.error)

    def _loop(self):
        registered = []
        try:
            for ident, vk in [(1, 0x77), (2, 0x78)]:
                if not user32.RegisterHotKey(None, ident, 0x4000, vk):
                    self.error = "F8/F9 заняты другой программой. Освободите клавиши и перезапустите приложение."
                    return
                registered.append(ident)
            self.ready.set()
            msg = wintypes.MSG()
            while not self.closed.wait(.01):
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == 0x0312:
                        (self.pause if msg.wParam == 1 else self.stop)()
        finally:
            self.ready.set()
            for ident in registered:
                user32.UnregisterHotKey(None, ident)

    def close(self):
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=2)
