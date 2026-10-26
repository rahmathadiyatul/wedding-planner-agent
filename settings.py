"""Runtime settings changeable from chat and persisted across restarts.

Small JSON file on the same volume as the plan. Env vars remain the defaults;
anything set here overrides them until changed again.
"""
from __future__ import annotations

import json
import os
import threading


class Settings:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def _read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, key: str, default=None):
        with self._lock:
            return self._read().get(key, default)

    def set(self, key: str, value) -> None:
        with self._lock:
            data = self._read()
            data[key] = value
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)

    def all(self) -> dict:
        with self._lock:
            return self._read()
