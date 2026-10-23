from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import hashlib
from datetime import datetime, timezone

from app.models import Calibration, Plan


def data_directory() -> Path:
    override = os.environ.get("ANIME_DRAWER_DATA_DIR")
    if override:
        root = Path(override)
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AnimeDrawer"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "anime-drawer"
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".saving-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Store:
    def __init__(self, root: Path | None = None):
        self.root = root or data_directory()
        self.root.mkdir(parents=True, exist_ok=True)

    def settings(self) -> dict:
        path = self.root / "settings.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise ValueError(f"Не удалось прочитать {path}; файл сохранён без изменений") from exc

    def save_settings(self, settings: dict) -> None:
        if any("key" in k.lower() or "token" in k.lower() for k in settings):
            raise ValueError("Ключи API должны храниться в системном хранилище, не в JSON")
        write_json(self.root / "settings.json", settings)

    def profiles(self) -> dict[str, Calibration]:
        path = self.root / "profiles.json"
        if not path.exists():
            return {}
        from app.game_profile import restrict_game_profile
        profiles = {k: Calibration.from_dict(v) for k, v in json.loads(path.read_text("utf-8")).items()}
        for profile in profiles.values():
            restrict_game_profile(profile)
            profile.validate()
        return profiles

    def save_profile(self, profile: Calibration) -> None:
        profile.validate()
        current = self.profiles()
        current[profile.name] = profile
        write_json(self.root / "profiles.json", {k: v.to_dict() for k, v in current.items()})

    def save_plan(self, plan: Plan) -> Path:
        fingerprint = hashlib.sha256(json.dumps(plan.to_dict(), sort_keys=True).encode()).hexdigest()[:16]
        path = self.root / "plans" / (plan.source_hash[:12] + "-" + fingerprint + ".json")
        write_json(path, plan.to_dict())
        return path

    def load_plan(self, path: str | Path) -> Plan:
        path = Path(path)
        if path.stat().st_size > 32_000_000:
            raise ValueError("Файл плана слишком велик")
        return Plan.from_dict(json.loads(path.read_text("utf-8")))

    def archive_image(self, image) -> Path:
        image = image.convert("RGB")
        digest = hashlib.sha256(image.tobytes() + str(image.size).encode()).hexdigest()
        directory = self.root / "images"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (digest + ".png")
        if not path.exists():
            fd, tmp = tempfile.mkstemp(dir=directory, suffix=".png")
            os.close(fd)
            try:
                image.save(tmp, "PNG")
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        return path

    def record(self, kind: str, info: dict) -> None:
        path = self.root / "history.json"
        history = json.loads(path.read_text("utf-8")) if path.exists() else []
        history.append({"at": datetime.now(timezone.utc).isoformat(), "kind": kind, **info})
        write_json(path, history[-200:])

    def performance(self):
        path = self.root/"performance.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text("utf-8"))
        except (ValueError, OSError):
            return []
        return data if isinstance(data, list) else []

    def record_performance(self, key, metrics):
        if metrics.get("strokes", 0) < 3 or metrics.get("predicted", 0) <= .05:
            return
        records = self.performance()
        records.append({"key": key, **metrics})
        write_json(self.root/"performance.json", records[-200:])
