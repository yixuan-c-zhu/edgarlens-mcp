"""A tiny on-disk JSON cache with per-entry TTLs.

EDGAR data changes slowly (the ticker list daily, filings a few times a quarter),
so caching keeps us well under the SEC's rate limit and makes repeat questions instant.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


def default_cache_dir() -> Path:
    if env := os.environ.get("EDGARLENS_CACHE_DIR"):
        return Path(env)
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "edgarlens"


class DiskCache:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or default_cache_dir()

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()[:32]
        return self.directory / f"{digest}.json"

    def get(self, key: str, ttl_seconds: float) -> Any | None:
        path = self._path(key)
        try:
            entry = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        if time.time() - entry.get("fetched_at", 0) > ttl_seconds:
            return None
        return entry.get("data")

    def set(self, key: str, data: Any) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"key": key, "fetched_at": time.time(), "data": data}))
        tmp.replace(path)  # atomic, so a crash never leaves a half-written entry


class NullCache:
    """Cache that stores nothing (used in tests and with --no-cache)."""

    def get(self, key: str, ttl_seconds: float) -> Any | None:
        return None

    def set(self, key: str, data: Any) -> None:
        pass
