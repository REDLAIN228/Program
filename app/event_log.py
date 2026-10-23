"""Bounded persistent lifecycle journal; no keys or provider response bodies."""
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import uuid


class EventJournal:
    def __init__(self, root):
        directory = Path(root)/"logs"
        directory.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("redlain."+uuid.uuid4().hex)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.handler = RotatingFileHandler(directory/"redlain-events.jsonl", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(self.handler)

    def write(self, kind, **fields):
        self.logger.info(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), event=kind, **fields),
                                    ensure_ascii=False, allow_nan=False))

    def close(self):
        if self.handler in self.logger.handlers:
            self.logger.removeHandler(self.handler)
            self.handler.close()
