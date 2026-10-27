"""Real 4.0 window screenshots at several sizes plus stress of mode switches.

Run: python tools/v4_visual_smoke.py [output-dir]
Uses a temporary data directory; never the user's %LOCALAPPDATA%\\AnimeDrawer.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pump(app, seconds):
    until = time.monotonic()+seconds
    while time.monotonic() < until:
        app.processEvents()
        time.sleep(.005)


def main():
    from PIL import Image, ImageDraw
    from PySide6.QtWidgets import QApplication
    from app.storage import Store
    from app.ui.panel import MainWindow
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]/"docs"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    data = Path(tempfile.mkdtemp(prefix="redlain-smoke-"))
    window = MainWindow(Store(data))
    window.hotkeys_ready = True
    report = {}
    try:
        window.resize(1366, 768)
        window.show()
        window.shell.play_intro()
        pump(app, .9)
        source = Image.new("RGB", (240, 240), "white")
        d = ImageDraw.Draw(source)
        d.ellipse((30, 20, 210, 230), fill=(20, 20, 28))
        d.ellipse((50, 50, 190, 210), fill=(244, 190, 168))
        d.ellipse((80, 100, 105, 130), fill=(20, 20, 28))
        d.ellipse((135, 100, 160, 130), fill=(20, 20, 28))
        path = data/"portrait.png"
        source.save(path)
        window.load_image(str(path))
        window.make_plan()
        until = time.monotonic()+30
        while window.job is not None and time.monotonic() < until:
            app.processEvents()
            time.sleep(.01)
        pump(app, .5)
        window.grab().save(str(out/"v4-workspace-1366.png"))
        for name in ("projects", "settings", "draw"):
            window.shell.navigate(name)
            pump(app, .3)
            if name != "draw":
                window.grab().save(str(out/f"v4-{name}.png"))
        # 1366×768 screen at 125% / 150% DPI = 1093×614 / 910×512 logical px (≈480 above the taskbar).
        for width, height in ((1024, 640), (1093, 614), (910, 480), (860, 600)):
            window.resize(width, height)
            pump(app, .3)
            window.grab().save(str(out/f"v4-workspace-{width}.png"))
            report[f"{width}x{height}"] = dict(actual=[window.width(), window.height()],
                                                run_visible=window.run_button.isVisible(),
                                                run_inside=window.rect().contains(
                                                    window.run_button.mapTo(window, window.run_button.rect().bottomRight())))
        window.resize(1366, 768)
        pump(app, .2)
        window.shell.toggle_compact()
        pump(app, .4)
        window.grab().save(str(out/"v4-compact.png"))
        window.shell.toggle_compact()
        pump(app, .4)
        # Rapid repeated toggles must end in a consistent, fully opaque window.
        for _ in range(12):
            window.shell.toggle_compact()
            window.shell.navigate("settings")
            window.shell.navigate("draw")
            window.shell.hide_to_launcher()
            window.shell.reveal()
            app.processEvents()
        pump(app, .6)
        report["after_stress"] = dict(visible=window.isVisible(), opacity=window.windowOpacity(),
                                      compact=window.shell._compact)
        report["paint_ms"] = dict(background=window.shell.root.paint_cost_ms(),
                                  assistant=window.shell.assistant.view.paint_cost_ms())
        for state in ("PROCESSING", "DRAWING", "PAUSED", "ERROR", "FINISHED"):
            window.set_state(state)
            pump(app, .25)
            window.shell.assistant.grab().save(str(out/f"v4-assistant-{state.lower()}.png"))
        window.set_state("IDLE")
    finally:
        window.close_resources()
        window.icon.close()
        window.hide()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
