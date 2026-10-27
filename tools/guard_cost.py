"""Measure per-sample Win32 safety-check cost against a real local window.

Every mouse sample of a stroke runs the full foreground/class/process/size/DPI
guard. This reports how much wall time those checks add per sample. It only
inspects this program's own test window; no input is sent.
Run on Windows: python tools/guard_cost.py
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def timed(function, count=2000):
    started = time.perf_counter()
    for _ in range(count):
        function()
    return round((time.perf_counter()-started)/count*1e6, 2)


def main():
    if os.name != "nt":
        raise SystemExit("Windows only")
    from PySide6.QtWidgets import QApplication
    from app.windows import Win32Backend, enable_dpi_awareness, window_state
    from app.ui.test_canvas import TestCanvas
    enable_dpi_awareness()
    app = QApplication.instance() or QApplication(sys.argv)
    canvas = TestCanvas()
    canvas.show()
    app.processEvents()
    hwnd = int(canvas.winId())
    backend = Win32Backend(hwnd)
    state = window_state(hwnd)
    x, y = state.client.x+state.client.width//2, state.client.y+state.client.height//2
    report = dict(
        window_state_us=timed(lambda: window_state(hwnd)),
        is_foreground_us=timed(backend.is_foreground),
        point_belongs_us=timed(lambda: backend.point_belongs_to_target(x, y)),
        unavailable_reason_us=timed(backend.unavailable_reason),
    )
    report["guard_per_sample_us"] = round(report["window_state_us"]+report["is_foreground_us"]
                                          + report["point_belongs_us"]+report["unavailable_reason_us"], 2)
    canvas.close()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
