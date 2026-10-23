"""Versioned, checksummed projects with atomic checkpoints and immutable assets."""
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import queue
import re
import threading
import uuid

import numpy as np
from PIL import Image, ImageDraw

from app.models import Calibration, Plan
from app.storage import write_json

FORMAT = 3
MAX_JSON = 64_000_000
MAX_IMAGE = 160_000_000


def image_digest(image):
    rgb = image.convert("RGB")
    return hashlib.sha256(rgb.tobytes()+str(rgb.size).encode()).hexdigest()


def validate_checkpoint(state, total):
    if not isinstance(state, dict):
        raise ValueError("Некорректная контрольная точка")
    cursor = state.get("cursor", 0)
    done, skipped = state.get("executed", []), state.get("skipped", [])
    if (type(cursor) is not int or not 0 <= cursor <= total or not isinstance(done, list)
            or not isinstance(skipped, list) or any(type(i) is not int or not 0 <= i < cursor for i in done+skipped)
            or len(set(done+skipped)) != len(done)+len(skipped) or set(done+skipped) != set(range(cursor))):
        raise ValueError("Контрольная точка содержит некорректные выполненные штрихи")
    metrics = state.get("metrics", {})
    if not isinstance(metrics, dict):
        raise ValueError("Некорректная статистика проекта")
    for key in ("elapsed", "active", "paused", "draw_seconds"):
        value = metrics.get(key, 0)
        if not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1e9:
            raise ValueError("Некорректное время в контрольной точке")
    return deepcopy(state)


class ProjectStore:
    def __init__(self, root):
        self.root = Path(root)/"projects"
        self.assets = self.root/".assets"
        self.assets.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def new_id(self):
        return uuid.uuid4().hex

    def cache_plan(self, plan):
        from app.storage import Store
        Store(self.root.parent).save_plan(plan)

    def _path(self, project_id):
        if not isinstance(project_id, str) or not re.fullmatch(r"[a-f0-9]{32}", project_id):
            raise ValueError("Некорректный ID проекта")
        return self.root/project_id/"project.json"

    def _put(self, raw, extension):
        import os
        import tempfile
        digest = hashlib.sha256(raw).hexdigest()
        name = digest+extension
        target = self.assets/name
        if not target.exists():
            fd, temp = tempfile.mkstemp(dir=self.assets, prefix=".asset-")
            try:
                with os.fdopen(fd, "wb") as file:
                    file.write(raw)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temp, target)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        return name

    def _get(self, name):
        if not re.fullmatch(r"[a-f0-9]{64}\.(png|json\.gz)", name):
            raise ValueError("Некорректная ссылка на ресурс проекта")
        path = self.assets/name
        if path.stat().st_size > (MAX_IMAGE if name.endswith(".png") else MAX_JSON):
            raise ValueError("Ресурс проекта слишком велик")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != name.split(".")[0]:
            raise ValueError("Контрольная сумма ресурса проекта не совпала")
        return raw

    def put_image(self, image):
        output = io.BytesIO()
        image.save(output, "PNG")
        return self._put(output.getvalue(), ".png")

    def get_image(self, name):
        with Image.open(io.BytesIO(self._get(name))) as image:
            if image.width*image.height > 40_000_000:
                raise ValueError("Изображение проекта слишком велико")
            return image.copy()

    def manifest(self, project_id):
        path = self._path(project_id)
        try:
            if path.stat().st_size > 8_000_000:
                raise ValueError("Манифест проекта слишком велик")
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            backup = path.with_name("previous.json")
            if not backup.exists(): raise
            data = json.loads(backup.read_text("utf-8"))
            data["recovered_from_backup"] = True
        if data.get("format_version") != FORMAT or data.get("id") != project_id:
            raise ValueError("Неподдерживаемая версия проекта")
        return data

    def create(self, project_id, title, source, processed, preview, plan, profile, options=None):
        from app.human import STAGES
        from app.raster import draw_stroke
        if image_digest(source) != plan.source_hash:
            raise ValueError("Исходное изображение не соответствует контрольной сумме плана")
        profile.validate()
        plan.drawing_area(profile.canvas)
        raw = json.dumps(plan.to_dict(), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > MAX_JSON:
            raise ValueError("План проекта превышает 64 МБ")
        masks = getattr(plan, "_layer_masks", None)
        if masks is None:
            masks = {name: Image.new("L", plan.canvas_size) for name in STAGES}
            painters = {name: ImageDraw.Draw(mask) for name, mask in masks.items()}
            for stroke in plan.strokes:
                draw_stroke(painters[STAGES[stroke.stage]], stroke, plan.canvas_size, plan.canvas_size, 255)
        assets = dict(source=self.put_image(source.convert("RGB")), processed=self.put_image(processed),
                      preview=self.put_image(preview), plan=self._put(gzip.compress(raw, mtime=0), ".json.gz"),
                      masks={name: self.put_image(mask) for name, mask in masks.items()})
        if hasattr(plan, "_label_map"):
            assets["segmentation"] = self.put_image(plan._label_map)
        if hasattr(plan, "_padding_mask"):
            assets["padding_mask"] = self.put_image(plan._padding_mask)
        now = datetime.now(timezone.utc).isoformat()
        data = dict(format_version=FORMAT, id=project_id, title=str(title)[:160], created=now, updated=now,
                    source_checksum=plan.source_hash, assets=assets, profile=profile.to_dict(),
                    options=options or {}, total=len(plan.strokes), revision=1,
                    checkpoint=dict(cursor=0, executed=[], skipped=[], status="ready", metrics={}, controls={}),
                    stages=list(STAGES), stage_counts=[sum(s.stage == stage for s in plan.strokes) for stage in range(7)],
                    engine=plan.engine)
        with self._lock:
            if self._path(project_id).exists():
                raise ValueError("Проект с этим ID уже существует")
            write_json(self._path(project_id), data)
        return data

    def save_checkpoint(self, project_id, state, canvas=None):
        with self._lock:
            data = self.manifest(project_id)
            previous = deepcopy(data)
            data["checkpoint"] = validate_checkpoint(state, data["total"])
            if canvas is not None:
                data["assets"]["canvas"] = self.put_image(canvas)
                data["canvas_cursor"] = state["cursor"]
            data["updated"] = datetime.now(timezone.utc).isoformat()
            data["revision"] += 1
            write_json(self._path(project_id).with_name("previous.json"), previous)
            write_json(self._path(project_id), data)
            return data

    def load(self, project_id):
        data = self.manifest(project_id)
        with gzip.GzipFile(fileobj=io.BytesIO(self._get(data["assets"]["plan"]))) as compressed:
            raw = compressed.read(MAX_JSON+1)
        if len(raw) > MAX_JSON:
            raise ValueError("План проекта слишком велик")
        plan = Plan.from_dict(json.loads(raw))
        if len(plan.strokes) != data["total"] or plan.source_hash != data["source_checksum"]:
            raise ValueError("План не соответствует манифесту проекта")
        state = validate_checkpoint(data["checkpoint"], len(plan.strokes))
        source = self.get_image(data["assets"]["source"])
        if image_digest(source) != data["source_checksum"]:
            raise ValueError("Контрольная сумма исходного изображения не совпала")
        profile = Calibration.from_dict(data["profile"])
        plan.drawing_area(profile.canvas)
        return dict(manifest=data, plan=plan, profile=profile, source=source, state=state,
                    processed=self.get_image(data["assets"]["processed"]),
                    preview=self.get_image(data["assets"]["preview"]),
                    canvas=self.get_image(data["assets"]["canvas"]) if data["assets"].get("canvas") else None)

    def recent(self, limit=100):
        rows = []
        # A power loss can remove the newest manifest. Still expose the last
        # complete checkpoint so it can be recovered from Projects.
        candidates = {path.parent for name in ("project.json", "previous.json") for path in self.root.glob("*/"+name)}
        for folder in candidates:
            try:
                rows.append(self.manifest(folder.name))
            except (ValueError, OSError, KeyError):
                continue
        return sorted(rows, key=lambda row: row["updated"], reverse=True)[:limit]

    def save_as(self, project_id, title):
        with self._lock:
            data = deepcopy(self.manifest(project_id))
            data["id"], data["title"], data["revision"] = self.new_id(), str(title)[:160], 1
            data["created"] = data["updated"] = datetime.now(timezone.utc).isoformat()
            write_json(self._path(data["id"]), data)
            return data

    def delete_checkpoint(self, project_id):
        with self._lock:
            data = self.manifest(project_id)
            data["checkpoint"] = dict(cursor=0, executed=[], skipped=[], status="ready", metrics={}, controls={})
            data["assets"].pop("canvas", None)
            data.pop("canvas_cursor", None)
            data["revision"] += 1
            data["updated"] = datetime.now(timezone.utc).isoformat()
            write_json(self._path(project_id).with_name("previous.json"), data)
            write_json(self._path(project_id), data)

    def update_profile(self, project_id, profile):
        with self._lock:
            payload = self.load(project_id)
            payload["plan"].drawing_area(profile.canvas)
            profile.validate()
            data = payload["manifest"]
            data["profile"] = profile.to_dict()
            data["revision"] += 1
            data["updated"] = datetime.now(timezone.utc).isoformat()
            write_json(self._path(project_id), data)
            return data


class ProjectWriter:
    """One disk writer; requests are serialized and never touch Qt widgets."""
    def __init__(self, store, completed=lambda *_: None, failed=lambda *_: None):
        self.store, self.completed, self.failed = store, completed, failed
        self.queue = queue.Queue(maxsize=16)
        self.thread = threading.Thread(target=self._run, name="ProjectCheckpointWriter", daemon=True)
        self.thread.start()

    def submit(self, operation, *args, **kwargs):
        try:
            self.queue.put_nowait((operation, args, kwargs))
        except queue.Full as exc:
            raise RuntimeError("Очередь сохранения заполнена. Приостановите рисунок и проверьте диск.") from exc

    def _run(self):
        while True:
            item = self.queue.get()
            try:
                if item is None:
                    return
                operation, args, kwargs = item
                result = getattr(self.store, operation)(*args, **kwargs)
                self.completed(operation, result)
            except Exception as exc:
                self.failed(str(exc))
            finally:
                self.queue.task_done()

    def flush(self, timeout=5):
        import time
        until = time.monotonic()+timeout
        while self.queue.unfinished_tasks and time.monotonic() < until:
            time.sleep(.01)
        return not self.queue.unfinished_tasks

    def close(self, timeout=5):
        if not self.thread.is_alive():
            return True
        if not self.flush(timeout):
            return False
        self.queue.put_nowait(None)
        self.thread.join(timeout)
        return not self.thread.is_alive()


def compare_canvas(saved, current, capture_cursor=None, state_cursor=None):
    if saved is None or capture_cursor != state_cursor:
        return dict(status="unknown", reason="Нет снимка, соответствующего этой контрольной точке")
    if saved.size != current.size:
        return dict(status="mismatch", reason="Размер холста отличается от сохранённого")
    a, b = np.asarray(saved.convert("RGB"), np.int16), np.asarray(current.convert("RGB"), np.int16)
    difference = np.max(np.abs(a-b), axis=2)
    changed = float(np.mean(difference[2:-2, 2:-2] > 25)) if min(saved.size) > 8 else 1.
    # A nearly blank canvas must not hide the loss of its only small stroke in
    # a whole-image percentage. Compare the actual marked area as well.
    ink = np.max(255-a, axis=2) > 25
    current_ink = np.max(255-b, axis=2) > 25
    ink[:2] = ink[-2:] = current_ink[:2] = current_ink[-2:] = False
    ink[:, :2] = ink[:, -2:] = current_ink[:, :2] = current_ink[:, -2:] = False
    ink_pixels = int(np.count_nonzero(ink))
    if ink_pixels < 8:
        return dict(status="unknown", changed_fraction=changed,
                    reason="На сохранённом холсте недостаточно различимого следа для уверенной проверки")
    ink_change = float(np.count_nonzero((ink | current_ink) & (difference > 25))/ink_pixels)
    return dict(status="match" if changed < .012 and ink_change < .06 else "mismatch", changed_fraction=changed,
                ink_changed_fraction=ink_change,
                reason="Сравнение пикселей, не проверка идентичности сервера")
