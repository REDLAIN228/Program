"""Start the built EXE and prove it really opens its window.

- separate ANIME_DRAWER_DATA_DIR (never the user's data);
- PATH without any Python directory and no PYTHON* variables;
- waits for a visible top-level window titled "REDLAIN DRAW ENGINE 4…" (the main window, not the splash) of that
  process, saves a screenshot, checks bundled assets, then terminates it.
Run (Windows): python tools/exe_smoke.py dist/RedlainDrawEngine [screenshot.png]
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def windows_of(pid):
    user32 = ctypes.windll.user32
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append((hwnd, title.value, (rect.left, rect.top, rect.right, rect.bottom)))
        return True
    user32.EnumWindows(callback_type(callback), 0)
    return found


def main():
    folder = Path(sys.argv[1]).resolve()
    shot = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    exe = folder/"RedlainDrawEngine.exe"
    internal = folder/"_internal"
    required = ["assets/redlain.ico", "assets/redlain-icon.png", "assets/redlain-icon.svg", "assets/size-digits.npz",
                "assets/assistant/drawing.png", "assets/assistant/README.md", "MODEL_NOTICES.md"]
    report = dict(exe=str(exe), exists=exe.exists(),
                  size_mb=round(sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())/2**20, 1),
                  missing=[name for name in required if not (internal/name).exists()])
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON") and k.upper() != "QT_QPA_PLATFORM"}
    env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if "python" not in p.lower() and "rl-py" not in p.lower())
    env["ANIME_DRAWER_DATA_DIR"] = tempfile.mkdtemp(prefix="redlain-exe-")
    started = time.monotonic()
    process = subprocess.Popen([str(exe)], cwd=str(folder), env=env)
    window = None
    try:
        while time.monotonic()-started < 60 and process.poll() is None:
            window = next((w for w in windows_of(process.pid) if w[1].startswith("REDLAIN DRAW ENGINE 4")), None)
            if window:
                break
            time.sleep(.25)
        report.update(alive=process.poll() is None, window_title=window[1] if window else None,
                      seconds_to_window=round(time.monotonic()-started, 1) if window else None,
                      all_windows=[w[1] for w in windows_of(process.pid)])
        if window and shot:
            time.sleep(1.5)  # Let the launch reveal finish before the screenshot.
            import mss
            from PIL import Image
            left, top, right, bottom = window[2]
            with mss.mss() as capture:
                image = capture.grab(dict(left=left, top=top, width=right-left, height=bottom-top))
                Image.frombytes("RGB", image.size, image.rgb).save(shot)
            report["screenshot"] = str(shot)
    finally:
        process.terminate()
        process.wait(10)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["exists"] and not report["missing"] and report.get("window_title") else 1


if __name__ == "__main__":
    raise SystemExit(main())
