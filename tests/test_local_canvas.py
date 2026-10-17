from dataclasses import replace
import time
import threading

import numpy as np
from PIL import Image, ImageDraw

from app.automation import DrawingExecutor
from app.models import Timing
from app.planner import PlanOptions, build_plan, render_plan
from app.ui.test_canvas import COLORS, QtCanvasBackend, TestCanvas


def test_planned_image_is_actually_painted_using_qt_mouse_events(qapp, tmp_path):
    canvas = TestCanvas()
    canvas.show()
    canvas.activateWindow()
    qapp.processEvents()
    profile = canvas.profile()
    profile.verified = True
    source = Image.new("RGB", (240, 180), "white")
    draw = ImageDraw.Draw(source)
    draw.rectangle((35, 30, 105, 150), fill=COLORS[1])
    draw.ellipse((130, 40, 205, 140), fill=COLORS[5])
    plan, _ = build_plan(source, PlanOptions((profile.canvas.width, profile.canvas.height),
                            palette=COLORS, time_limit=None, brush_widths=(3, 9, 18), quality="Fast"))
    # Faster timing only for app-local events; never sent to an external application.
    plan.timing = Timing(.00001, .00001, 1000000, 50)
    backend = QtCanvasBackend(canvas)
    executor = DrawingExecutor(backend, profile)
    outcomes, errors = [], []
    def run():
        try:
            outcomes.append(executor.run(plan))
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 30
    while thread.is_alive() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.0005)
    if thread.is_alive():
        executor.stop_event.set()
        while thread.is_alive():
            qapp.processEvents()
            time.sleep(.001)
    thread.join()
    assert not errors
    assert outcomes == ["finished"]
    assert executor.completed == len(plan.strokes)
    assert canvas.received_segments > len(plan.strokes)
    assert not canvas.pressed
    r = profile.canvas
    actual = canvas.screenshot().crop((r.x, r.y, r.x+r.width, r.y+r.height))
    preview = render_plan(plan)
    distance = np.max(np.abs(np.asarray(actual, float)-np.asarray(preview, float)), axis=2)
    assert np.mean(distance < 35) > .95
    actual.save(tmp_path / "actual-canvas.png")
    preview.save(tmp_path / "planned-preview.png")
    # Both nonwhite colors must have been selected and painted; white-only passes fail.
    a = np.asarray(actual)
    assert np.count_nonzero(np.all(a == COLORS[1], axis=2)) > 1000
    assert np.count_nonzero(np.all(a == COLORS[5], axis=2)) > 1000
    canvas.close()
