"""
OrbitScope - background jobs with progress
==========================================
Blink, detection and photometry requests on a new field can take minutes (IRSA downloads).
Instead of one long HTTP request, the browser submits a job, polls its progress
(stage + done/total) and fetches the result when it is ready. Jobs run in-process as asyncio
tasks; identical requests share one job; finished jobs are kept for a while so a page
reload can pick the result up again.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from app.core.logging_config import get_logger
from app.core.progress import reporter

logger = get_logger(__name__)

MAX_CONCURRENT_JOBS = 3
KEEP_FINISHED_S = 30 * 60


@dataclass
class Job:
    id: str
    kind: str
    key: str
    status: str = "queued"  # queued | running | done | error | cancelled
    stage: str = "queued"
    done: int = 0
    total: int = 0
    created: float = field(default_factory=time.time)
    started: Optional[float] = None
    finished: Optional[float] = None
    result: Any = None
    error: Optional[dict[str, Any]] = None
    task: Optional[asyncio.Task] = None

    def public(self, include_result: bool = True) -> dict[str, Any]:
        now = time.time()
        out: dict[str, Any] = {
            "id": self.id, "kind": self.kind, "status": self.status, "stage": self.stage,
            "done": self.done, "total": self.total,
            "elapsed_s": round((self.finished or now) - (self.started or self.created), 1),
            "queued_s": round((self.started or now) - self.created, 1),
        }
        if self.error:
            out["error"] = self.error
        if include_result and self.status == "done":
            out["result"] = self.result
        return out


ErrorMapper = Callable[[BaseException], dict[str, Any]]


class JobManager:
    def __init__(self, max_concurrent: int = MAX_CONCURRENT_JOBS) -> None:
        self.jobs: dict[str, Job] = {}
        self.by_key: dict[str, str] = {}
        self._max = max_concurrent
        self._sem: Optional[asyncio.Semaphore] = None

    def _semaphore(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self._max)
        return self._sem

    def _cleanup(self) -> None:
        now = time.time()
        for jid in [j.id for j in self.jobs.values() if j.finished and now - j.finished > KEEP_FINISHED_S]:
            job = self.jobs.pop(jid)
            if self.by_key.get(job.key) == jid:
                self.by_key.pop(job.key, None)

    def submit(
        self, kind: str, key: str, factory: Callable[[], Awaitable[Any]], map_error: ErrorMapper
    ) -> Job:
        """Start a job, or return the running/finished job for the same request."""
        self._cleanup()
        existing = self.jobs.get(self.by_key.get(key, ""))
        if existing and existing.status in ("queued", "running", "done"):
            return existing
        job = Job(id=f"JOB-{uuid.uuid4().hex[:10]}", kind=kind, key=key)
        self.jobs[job.id] = job
        self.by_key[key] = job.id

        def on_progress(stage: str, done: int, total: int) -> None:
            job.stage, job.done, job.total = stage, done, total

        async def run() -> None:
            async with self._semaphore():
                job.status, job.stage, job.started = "running", "starting", time.time()
                try:
                    with reporter(on_progress):
                        job.result = await factory()
                    job.status, job.stage = "done", "done"
                except asyncio.CancelledError:
                    job.status, job.stage = "cancelled", "cancelled"
                    raise
                except BaseException as exc:  # noqa: BLE001 - reported to the client
                    job.status, job.stage = "error", "error"
                    job.error = map_error(exc)
                    if job.error.get("status", 500) >= 500:
                        logger.exception(f"Job {job.id} ({kind}) failed: {exc}")
                finally:
                    job.finished = time.time()

        job.task = asyncio.create_task(run())
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> Optional[Job]:
        job = self.jobs.get(job_id)
        if job and job.task and not job.task.done():
            job.task.cancel()
        return job

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for j in self.jobs.values():
            out[j.status] = out.get(j.status, 0) + 1
        return out


job_manager = JobManager()
