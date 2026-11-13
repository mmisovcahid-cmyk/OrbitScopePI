"""
OrbitScope - offline snapshots of real answers
==============================================
A Raspberry Pi demo must keep working without internet. Every successful answer from a live
service (JPL SBDB, the Planet X orbit sample, CDS Sesame / NED) is also written to disk here.
When the service is unreachable later, the last real answer is served instead, marked with
``offline_snapshot: {"saved_at": ...}`` so the UI can say "cached on <date>".

Nothing is ever invented: if there is no snapshot, the caller's original error (HTTP 502) stands.
Time-dependent answers (Horizons ephemerides, SB Ident) are deliberately not snapshotted, because
an old answer would describe a different date than the one asked for.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


def snapshot_dir() -> Path:
    if settings.OFFLINE_CACHE_DIR:
        return Path(settings.OFFLINE_CACHE_DIR)
    return Path(settings.SPHEREX_CACHE_DIR).parent / "offline"


def _path(namespace: str, key: str) -> Path:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return snapshot_dir() / namespace / f"{digest}.json"


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save(namespace: str, key: str, data: Any) -> None:
    """Store one real answer. Failures are logged, never raised (the live answer still goes out)."""
    path = _path(namespace, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"key": key, "saved_at": time.time(), "data": data}), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not write offline snapshot {namespace}/{key}: {exc}")


def load(namespace: str, key: str) -> Optional[tuple[Any, float]]:
    """(data, saved_at) of the last real answer, or None."""
    path = _path(namespace, key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("key") != key:
        return None
    return payload.get("data"), float(payload.get("saved_at", 0.0))


def mark(data: Any, saved_at: float) -> Any:
    """Label a snapshot so the API response and the UI show where it came from."""
    if isinstance(data, dict):
        return {**data, "offline_snapshot": {"saved_at": iso(saved_at)}}
    return data


def stats() -> dict[str, Any]:
    root = snapshot_dir()
    out: dict[str, int] = {}
    if root.exists():
        for sub in root.iterdir():
            if sub.is_dir():
                out[sub.name] = sum(1 for _ in sub.glob("*.json"))
    return {"dir": str(root), "snapshots": out}
