"""Background job API: progress, de-duplication, errors, cancellation (offline, stubbed archive)."""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.core.progress import gather_with_progress, report, reporter
from app.main import app
from app.services import jobs as jobs_mod
from app.services.spherex_archive import SpherexError, spherex_archive


@pytest.fixture()
def fresh_jobs(monkeypatch):
    mgr = jobs_mod.JobManager()
    monkeypatch.setattr(jobs_mod, "job_manager", mgr)
    import app.api.routes.jobs as jr
    monkeypatch.setattr(jr, "job_manager", mgr)
    return mgr


def _poll(c: TestClient, job_id: str, timeout: float = 10.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = c.get(f"/api/v1/jobs/{job_id}").json()["data"]
        if d["status"] in ("done", "error", "cancelled"):
            return d
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_blink_job_reports_progress_and_returns_result(fresh_jobs, monkeypatch) -> None:
    seen: list[tuple[str, int, int]] = []

    async def fake_build(**kw):
        report("coverage")
        await gather_with_progress("download", (asyncio.sleep(0.05) for _ in range(4)))
        report("assemble")
        await asyncio.sleep(0.2)
        return {"target": {}, "frames": [1, 2], "kw": kw}

    monkeypatch.setattr(spherex_archive, "build_blink", fake_build)
    with TestClient(app) as c:
        r = c.post("/api/v1/jobs", json={"kind": "blink", "params": {"ra": 10, "dec": 4, "fov": 0.1}})
        assert r.status_code == 200
        job = r.json()["data"]
        assert job["status"] in ("queued", "running")
        # progress becomes visible while running
        t0 = time.time()
        while time.time() - t0 < 5:
            d = c.get(f"/api/v1/jobs/{job['id']}", params={"include_result": False}).json()["data"]
            seen.append((d["stage"], d["done"], d["total"]))
            if d["status"] == "done":
                break
            time.sleep(0.02)
        final = _poll(c, job["id"])
    assert final["status"] == "done"
    assert final["result"]["frames"] == [1, 2]
    assert final["result"]["kw"]["fov_deg"] == 0.1
    stages = {s for s, _, _ in seen}
    assert "assemble" in stages or "download" in stages


def test_identical_requests_share_one_job(fresh_jobs, monkeypatch) -> None:
    calls = 0

    async def fake_build(**kw):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.1)
        return {"target": {}}

    monkeypatch.setattr(spherex_archive, "build_blink", fake_build)
    body = {"kind": "blink", "params": {"ra": 1, "dec": 2}}
    with TestClient(app) as c:
        a = c.post("/api/v1/jobs", json=body).json()["data"]["id"]
        b = c.post("/api/v1/jobs", json=body).json()["data"]["id"]
        assert a == b
        _poll(c, a)
    assert calls == 1


def test_archive_error_is_localized(fresh_jobs, monkeypatch) -> None:
    async def fake_build(**kw):
        raise SpherexError("no_coverage", "nothing")

    monkeypatch.setattr(spherex_archive, "build_blink", fake_build)
    with TestClient(app) as c:
        jid = c.post("/api/v1/jobs", json={"kind": "blink", "params": {"ra": 1, "dec": 2}, "locale": "az"}).json()["data"]["id"]
        d = _poll(c, jid)
    assert d["status"] == "error"
    assert d["error"]["status"] == 404
    assert "SPHEREx" in d["error"]["detail"] and "müşahidə" in d["error"]["detail"]


def test_cancel_running_job(fresh_jobs, monkeypatch) -> None:
    async def slow(**kw):
        await asyncio.sleep(30)
        return {"target": {}}

    monkeypatch.setattr(spherex_archive, "build_blink", slow)
    with TestClient(app) as c:
        jid = c.post("/api/v1/jobs", json={"kind": "blink", "params": {"ra": 3, "dec": 4}}).json()["data"]["id"]
        time.sleep(0.1)
        assert c.delete(f"/api/v1/jobs/{jid}").status_code == 200
        d = _poll(c, jid)
    assert d["status"] == "cancelled"


def test_invalid_params_rejected(fresh_jobs) -> None:
    with TestClient(app) as c:
        assert c.post("/api/v1/jobs", json={"kind": "blink", "params": {"ra": 1, "dec": 2, "fov": 9}}).status_code == 422
        assert c.post("/api/v1/jobs", json={"kind": "nope", "params": {}}).status_code == 422
        assert c.get("/api/v1/jobs/JOB-missing").status_code == 404


def test_reporter_is_scoped() -> None:
    got = []
    report("outside")  # no-op without a reporter
    with reporter(lambda s, d, t: got.append((s, d, t))):
        report("inside", 1, 2)
    report("after")
    assert got == [("inside", 1, 2)]
