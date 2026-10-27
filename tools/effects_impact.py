"""Do the background/assistant/animations slow the engine? Measure it.

The same plan runs on a worker thread (in-memory SimGame window, real
"Turbo · 7" timing) while the 4.0 window is open:
  off     — "Без анимаций", background and assistant disabled;
  forced  — full effects kept running during execution (worst case, not the
            normal flow: normally decorations stop for external input);
  normal  — full effects, but DRAWING state stops decorative frames, as in RUN.
Reports execution seconds, process CPU seconds, decorative frame cost and UI
timer lateness. Run: python tools/effects_impact.py  (QT_QPA_PLATFORM=windows
for the real Windows compositor; offscreen by default.)
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from app.automation import DrawingExecutor
    from app.models import Rect, Timing
    from app.planner import PlanOptions, build_plan
    from app.storage import Store
    from app.ui.panel import MainWindow
    from app.ui.test_canvas import COLORS, TestCanvas
    from benchmark_v2 import fixtures
    from benchmark_v4 import SimGame
    app = QApplication.instance() or QApplication([])
    profile = TestCanvas().profile(False)
    profile.canvas = Rect(profile.canvas.x, profile.canvas.y, 128, 128)
    profile.verified = True
    plan, _ = build_plan(fixtures()["portrait"], PlanOptions((128, 128), style="Custom", engine="Human 3.0",
                         human_mode="BALANCED", time_limit=None, palette=COLORS, brush_widths=(3, 9, 18),
                         detect_faces=False))
    plan = replace(plan, timing=Timing.preset("Turbo · 7"), smart_finish=False)
    window = MainWindow(Store(Path(tempfile.mkdtemp(prefix="redlain-fx-"))))
    window.hotkeys_ready = True
    window.resize(1366, 768)
    window.show()
    window.activateWindow()
    shell = window.shell
    report = dict(scope="Same plan, same timing; SimGame in memory; Qt platform "+os.environ["QT_QPA_PLATFORM"],
                  strokes=len(plan.strokes), runs={})
    try:
        for name in ("off", "forced", "normal", "off"):
            shell.motion.set("level", "off" if name == "off" else "full")
            shell.motion.set("background", name != "off")
            shell.motion.set("assistant", name != "off")
            window.set_state("DRAWING" if name == "normal" else "IDLE")
            if name == "forced":
                shell.motion.set_external_input(False)
            shell.sync_decorations()
            shell.root._paint_ms.clear()
            shell.assistant.view._paint_ms.clear()
            shell.root.frames = shell.assistant.view.frames = 0
            lateness = []
            expected = [time.perf_counter()+.05]
            probe = QTimer()
            probe.setInterval(50)
            def tick():
                now = time.perf_counter()
                lateness.append(max(0., now-expected[0])*1000)
                expected[0] = now+.05
            probe.timeout.connect(tick)
            probe.start()
            executor = DrawingExecutor(SimGame(profile), profile)
            result = {}
            worker = threading.Thread(target=lambda: result.setdefault("outcome", executor.run(plan)))
            cpu, started = time.process_time(), time.perf_counter()
            worker.start()
            while worker.is_alive():
                app.processEvents()
                time.sleep(.002)
            probe.stop()
            run = dict(outcome=result.get("outcome"), seconds=round(time.perf_counter()-started, 3),
                       process_cpu_seconds=round(time.process_time()-cpu, 3),
                       background_frames=shell.root.frames, background_ms=round(shell.root.paint_cost_ms(), 3),
                       assistant_frames=shell.assistant.view.frames,
                       assistant_ms=round(shell.assistant.view.paint_cost_ms(), 3),
                       ui_timer_late_p95_ms=round(sorted(lateness)[int(len(lateness)*.95)] if lateness else 0, 2),
                       ui_timer_late_median_ms=round(statistics.median(lateness), 2) if lateness else 0)
            key = name if name not in report["runs"] else name+"-repeat"
            report["runs"][key] = run
            print(key, json.dumps(run, ensure_ascii=False), flush=True)
            window.set_state("IDLE")
    finally:
        window.close_resources()
        window.icon.close()
        window.hide()
    out = Path(__file__).resolve().parents[1]/"docs/v4-effects-impact.json"
    existing = json.loads(out.read_text("utf-8")) if out.exists() else {}
    existing[os.environ["QT_QPA_PLATFORM"]] = report
    out.write_text(json.dumps(existing, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
