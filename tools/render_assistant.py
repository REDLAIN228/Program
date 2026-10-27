"""Export REDLAIN Assistant poses from the same QPainter code the app uses.

The character is code-drawn (app/ui/assistant.py); these PNGs are reference
renders for docs, store pages and review. Run: python tools/render_assistant.py
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication
    from app.ui.assistant import AssistantModel, AssistantView
    from app.ui.motion import MotionSettings
    app = QApplication.instance() or QApplication([])
    out = Path(__file__).resolve().parents[1]/"assets/assistant"
    out.mkdir(parents=True, exist_ok=True)
    motion = MotionSettings({"ui_motion": "off"})
    poses = {"idle": "IDLE", "preparing": "LOADING", "planning": "PROCESSING", "drawing": "DRAWING",
             "paused": "PAUSED", "error": "ERROR", "finished": "FINISHED"}
    for name, state in poses.items():
        model = AssistantModel()
        model.app_state(state)
        if name == "drawing":
            model.engine_event({"type": "cursor", "position": [.62, .42]}, (200, 69, 80))
        model.save = "saved" if name == "finished" else None
        view = AssistantView(model, motion)
        view.resize(630, 510)
        image = QImage(view.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(view.width()/210, view.height()/170)
        painter.translate((view.width()-210*scale)/2, (view.height()-170*scale)/2)
        painter.scale(scale, scale)
        view._hand = view._hand_target()
        view._paint_scene(painter)
        painter.end()
        image.save(str(out/f"{name}.png"))
        print("saved", out/f"{name}.png")
    del app


if __name__ == "__main__":
    main()
