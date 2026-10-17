r"""Run on an interactive Windows desktop. Draws ONLY on our local test window.

After run.bat succeeds, use PowerShell in the project folder:
    $python = (Get-Content -Raw -Encoding UTF8 .\logs\python-path.txt).Trim()
    & $python tools\native_smoke.py
Produces artifacts/native-smoke.json and actual screenshots. F9 always aborts.
This is a real SendInput acceptance check, not part of the headless test suite.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    if os.name != "nt":
        raise SystemExit("Native smoke requires an interactive Windows desktop")
    from app.windows import (GlobalHotkeys, Win32Backend, capture_client, enable_dpi_awareness,
                             focus_window, window_state)
    enable_dpi_awareness()
    import numpy as np
    from PySide6.QtWidgets import QApplication
    from app.automation import DrawingExecutor
    from app.models import Plan, Stroke, Timing, estimate_plan
    from app.ui.test_canvas import COLORS, TestCanvas

    app = QApplication([])
    canvas = TestCanvas()
    canvas.show()
    canvas.activateWindow()
    app.processEvents()
    focus_window(int(canvas.winId()))
    app.processEvents()
    profile = canvas.profile(native=True)
    profile.verified = True  # Scope is this known test widget only.
    width = profile.brushes[1].pixels
    strokes = [Stroke(((.15, .25), (.80, .25)), COLORS[1], width),
               Stroke(((.20, .60), (.70, .85)), COLORS[5], profile.brushes[0].pixels)]
    size = profile.canvas.width, profile.canvas.height
    plan = Plan(size, strokes, Timing.preset("Safe"), estimate_plan(strokes, size, Timing.preset("Safe")),
                "native-smoke", [COLORS[1], COLORS[5]])
    executor = DrawingExecutor(Win32Backend(int(canvas.winId())), profile)
    hotkeys = GlobalHotkeys(lambda: executor.pause(not executor.pause_event.is_set()), executor.stop)
    hotkeys.start()
    results, failures = [], []
    def run():
        time.sleep(.5)
        try:
            results.append(executor.run(plan))
        except Exception as exc:
            failures.append(str(exc))
    thread = threading.Thread(target=run)
    thread.start()
    while thread.is_alive():
        app.processEvents()
        time.sleep(.002)
    thread.join()
    app.processEvents()
    root = Path(__file__).resolve().parents[1] / "artifacts"
    root.mkdir(exist_ok=True)
    actual = capture_client(window_state(int(canvas.winId())))
    r = profile.canvas
    crop = actual.crop((r.x, r.y, r.x+r.width, r.y+r.height))
    a = np.asarray(crop, dtype=float)
    red = int(np.count_nonzero(np.max(np.abs(a - COLORS[1]), axis=2) < 15))
    blue = int(np.count_nonzero(np.max(np.abs(a - COLORS[5]), axis=2) < 15))
    passed = results == ["finished"] and not failures and red > 100 and blue > 100
    actual.save(root / "native-smoke.png")
    report = {"passed": passed, "outcomes": results, "errors": failures,
              "red_pixels": red, "blue_pixels": blue, "completed": executor.completed,
              "dpi": profile.dpi, "client_size": profile.client_size}
    (root / "native-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    hotkeys.close()
    canvas.close()
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
