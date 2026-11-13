"""
OrbitScope - persistent store for detection runs and candidates (SQLite)
=======================================================================
Candidates survive restarts and carry a human review status so volunteers can mark
detections as real / artifact. One small SQLite file, no server needed.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings

REVIEW_STATUSES = ("unreviewed", "real", "artifact", "unsure")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    params TEXT NOT NULL,
    summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    class TEXT NOT NULL,
    score REAL NOT NULL,
    ra REAL NOT NULL,
    dec REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'unreviewed',
    note TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_run ON candidates(run_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CandidateStore:
    def __init__(self, path: Optional[str | Path] = None) -> None:
        self.path = Path(path or settings.ORBITSCOPE_DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL + NORMAL sync: far fewer fsyncs per write (kinder to a Raspberry Pi's SD card), still crash-safe.
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def save_run(self, run_id: str, params: dict[str, Any], summary: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO runs (id, created_at, params, summary) VALUES (?, ?, ?, ?)",
                (run_id, now, json.dumps(params), json.dumps(summary)),
            )
            self._conn.executemany(
                "INSERT OR REPLACE INTO candidates (id, run_id, created_at, updated_at, class, score, ra, dec, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(c["id"], run_id, now, now, c["class"], c["score"], c["ra"], c["dec"], json.dumps(c)) for c in candidates],
            )
            self._conn.commit()

    def _row(self, r: sqlite3.Row) -> dict[str, Any]:
        data = json.loads(r["data"])
        data.update({"status": r["status"], "note": r["note"], "run_id": r["run_id"],
                     "created_at": r["created_at"], "updated_at": r["updated_at"]})
        return data

    def list(self, status: Optional[str] = None, klass: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        q = "SELECT * FROM candidates"
        cond, args = [], []
        if status:
            cond.append("status = ?")
            args.append(status)
        if klass:
            cond.append("class = ?")
            args.append(klass)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY created_at DESC, score DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        return [self._row(r) for r in rows]

    def get(self, cand_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            r = self._conn.execute("SELECT * FROM candidates WHERE id = ?", (cand_id,)).fetchone()
        return self._row(r) if r else None

    def review(self, cand_id: str, status: str, note: Optional[str] = None) -> Optional[dict[str, Any]]:
        if status not in REVIEW_STATUSES:
            raise ValueError(f"status must be one of {REVIEW_STATUSES}")
        with self._lock:
            cur = self._conn.execute(
                "UPDATE candidates SET status = ?, note = COALESCE(?, note), updated_at = ? WHERE id = ?",
                (status, note, _now(), cand_id),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get(cand_id)

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            r = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "created_at": r["created_at"], "params": json.loads(r["params"]),
                "summary": json.loads(r["summary"])}

    def recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r["id"], "created_at": r["created_at"], "params": json.loads(r["params"]),
                 "summary": json.loads(r["summary"])} for r in rows]

    def class_counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT class, COUNT(*) AS n FROM candidates GROUP BY class").fetchall()
        return {r["class"]: r["n"] for r in rows}

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT status, COUNT(*) AS n FROM candidates GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}


_store: Optional[CandidateStore] = None


def get_store() -> CandidateStore:
    global _store
    if _store is None:
        _store = CandidateStore()
    return _store
