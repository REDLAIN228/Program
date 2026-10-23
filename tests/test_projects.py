from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from PIL import Image
import pytest

from app.automation import DrawingExecutor, WindowState
from app.models import Plan, Rect, Stroke, Timing
from app.planner import render_plan
from app.projects import ProjectStore, ProjectWriter, compare_canvas, image_digest, validate_checkpoint


class Input:
    def __init__(self): self.pressed = False
    def snapshot(self): return WindowState(7, "test", "TestClass", "test.exe", Rect(0, 0, 400, 400), 96)
    def is_foreground(self): return True
    def point_belongs_to_target(self, x, y): return self.snapshot().client.contains(x, y)
    def move(self, x, y): pass
    def down(self): self.pressed = True
    def up(self): self.pressed = False
    def sample(self, x, y): return (20, 20, 28)


def create(store, profile):
    source = Image.new("RGB", (60, 60), (20, 20, 28))
    strokes = [Stroke(((.2, y), (.8, y)), (20, 20, 28), 3, stage=i) for i, y in enumerate((.2, .4, .6, .8))]
    plan = Plan((300, 280), strokes, Timing(.0001, .0001, 1e6, 20), .1, image_digest(source), [(20, 20, 28)])
    project_id = store.new_id()
    store.create(project_id, "Persistent portrait", source, source.resize(plan.canvas_size), render_plan(plan), plan, profile,
                 dict(mode="MASTERPIECE", canvas_fill=dict(mode="REDLAIN BRANDING", text="REDLAIN")))
    return project_id, plan


def test_pause_save_process_restart_and_resume_execute_only_remaining_strokes(tmp_path, profile):
    store = ProjectStore(tmp_path)
    project_id, plan = create(store, profile)
    backend = Input()
    executor = DrawingExecutor(backend, profile)
    saved = threading.Event()
    result, errors = [], []
    def checkpoint(state, canvas):
        store.save_checkpoint(project_id, state, canvas)
        if state["cursor"] == 2 and state["status"] == "paused": saved.set()
    def event(value):
        if value["type"] == "stroke_complete" and value["index"] == 1:
            executor.pause()
    def run():
        try: result.append(executor.run(plan, event=event, checkpoint=checkpoint))
        except Exception as exc: errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert saved.wait(3)
        assert not backend.pressed
        executor.stop()
        thread.join(3)
        assert not errors and result == ["stopped"]
    finally:
        executor.stop()
        thread.join(2)
    # A separate Python interpreter proves that the checkpoint has no dependency
    # on GUI objects or in-memory runner state.
    command = [sys.executable, "-c", "from app.projects import ProjectStore; import sys,json; p=ProjectStore(sys.argv[1]).load(sys.argv[2]); print(json.dumps(p['state']))", str(tmp_path), project_id]
    state = json.loads(subprocess.check_output(command, text=True))
    assert state["cursor"] == 2 and state["executed"] == [0, 1]
    assert state["completed_stages"] == [0, 1]
    loaded = ProjectStore(tmp_path).load(project_id)
    assert loaded["manifest"]["options"]["canvas_fill"]["mode"] == "REDLAIN BRANDING"
    assert loaded["state"]["metrics"]["telemetry"]["mouse_presses"] > 0
    starts = []
    resumed = DrawingExecutor(Input(), loaded["profile"])
    outcome = resumed.run(loaded["plan"], resume=loaded["state"], event=lambda e: starts.append(e["index"]) if e["type"] == "stroke_start" else None)
    assert outcome == "finished" and starts == [2, 3]
    assert resumed.executed_indices == [0, 1, 2, 3]


def test_atomic_failure_preserves_old_checkpoint_and_save_as_is_independent(tmp_path, profile, monkeypatch):
    store = ProjectStore(tmp_path)
    project_id, _ = create(store, profile)
    initial = dict(cursor=1, executed=[0], skipped=[], metrics={}, status="paused", controls={})
    store.save_checkpoint(project_id, initial)
    original = os.replace
    def fail_manifest(source, target):
        if Path(target).name == "project.json": raise OSError("Simulated disk failure")
        return original(source, target)
    monkeypatch.setattr(os, "replace", fail_manifest)
    with pytest.raises(OSError):
        store.save_checkpoint(project_id, dict(initial, cursor=2, executed=[0, 1]))
    assert ProjectStore(tmp_path).load(project_id)["state"]["cursor"] == 1
    monkeypatch.setattr(os, "replace", original)
    copied = store.save_as(project_id, "Independent copy")
    store.delete_checkpoint(project_id)
    assert store.load(project_id)["state"]["cursor"] == 0
    assert store.load(copied["id"])["state"]["cursor"] == 1
    assert copied["assets"] == store.manifest(project_id)["assets"]


def test_corrupt_resource_and_future_format_are_rejected(tmp_path, profile):
    store = ProjectStore(tmp_path)
    project_id, _ = create(store, profile)
    data = store.manifest(project_id)
    asset = store.assets/data["assets"]["source"]
    asset.write_bytes(asset.read_bytes()+b"corrupt")
    with pytest.raises(ValueError, match="сумма"):
        store.load(project_id)
    data["format_version"] = 999
    store._path(project_id).write_text(json.dumps(data), "utf-8")
    with pytest.raises(ValueError, match="версия"):
        store.load(project_id)
    with pytest.raises(ValueError): store.manifest("../escape")


@pytest.mark.parametrize("state", [dict(cursor=2, executed=[0, 0], skipped=[]),
                                    dict(cursor=2, executed=[0], skipped=[]),
                                    dict(cursor=1, executed=[1], skipped=[]),
                                    dict(cursor=0, executed=[], skipped=[], metrics=dict(elapsed=float('nan')))])
def test_invalid_ledger_never_enters_drawing(state):
    with pytest.raises(ValueError): validate_checkpoint(state, 4)


def test_canvas_evidence_requires_matching_ledger_and_preserved_pixels():
    saved = Image.new("RGB", (60, 60), "white")
    assert compare_canvas(saved, saved.copy(), 2, 2)["status"] == "unknown"
    from PIL import ImageDraw
    ImageDraw.Draw(saved).line((25, 25, 34, 25), fill="black")
    assert compare_canvas(saved, saved.copy(), 2, 2)["status"] == "match"
    # Losing the only 10 pixels used to pass the 1.2% whole-canvas threshold.
    assert compare_canvas(saved, Image.new("RGB", saved.size, "white"), 2, 2)["status"] == "mismatch"
    assert compare_canvas(saved, saved.copy(), 1, 2)["status"] == "unknown"
    assert compare_canvas(None, saved, None, 2)["status"] == "unknown"
    assert compare_canvas(saved, Image.new("RGB", (60, 60), "black"), 2, 2)["status"] == "mismatch"


def test_previous_atomic_checkpoint_recovers_a_damaged_manifest(tmp_path, profile):
    store = ProjectStore(tmp_path)
    project_id, _ = create(store, profile)
    for cursor in (1, 2):
        store.save_checkpoint(project_id, dict(cursor=cursor, executed=list(range(cursor)), skipped=[], metrics={}))
    store._path(project_id).write_bytes(b'{"interrupted":')
    recovered = ProjectStore(tmp_path).load(project_id)
    assert recovered["manifest"]["recovered_from_backup"] is True
    assert recovered["state"]["cursor"] == 1
    store._path(project_id).unlink()
    assert ProjectStore(tmp_path).recent()[0]["id"] == project_id


def test_checkpoint_writer_serializes_real_progress_and_reports_io_failures(tmp_path, profile):
    store = ProjectStore(tmp_path)
    project_id, _ = create(store, profile)
    successes, failures = [], []
    writer = ProjectWriter(store, lambda op, data: successes.append(data), failures.append)
    try:
        for cursor in range(1, 5):
            writer.submit("save_checkpoint", project_id, dict(cursor=cursor, executed=list(range(cursor)), skipped=[], metrics={}))
        assert writer.flush(3)
        assert store.load(project_id)["state"]["cursor"] == 4
        assert [row["checkpoint"]["cursor"] for row in successes] == [1, 2, 3, 4] and not failures
        writer.submit("save_checkpoint", "invalid-id", {})
        assert writer.flush(3) and failures
    finally:
        assert writer.close(3)
