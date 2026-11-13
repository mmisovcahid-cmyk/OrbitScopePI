"""Offline operation (Raspberry Pi demo without internet): last real answers, clearly labelled.

Nothing may be invented: without a snapshot the original error must still reach the caller.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time

import httpx
import pytest

from app.core import offline
from app.services import etno
from app.services import jpl_catalog as jc
from app.services.spherex_archive import SpherexArchive, SpherexError


@pytest.fixture(autouse=True)
def _clear_caches():
    jc._cache.clear()
    etno._cache.clear()
    yield
    jc._cache.clear()
    etno._cache.clear()


def test_snapshot_roundtrip_and_label():
    offline.save("sbdb", "sbdb:ceres", {"match": {"name": "1 Ceres"}})
    data, saved = offline.load("sbdb", "sbdb:ceres")
    assert data == {"match": {"name": "1 Ceres"}}
    marked = offline.mark(data, saved)
    assert marked["match"]["name"] == "1 Ceres"
    assert marked["offline_snapshot"]["saved_at"].endswith("Z")
    assert offline.load("sbdb", "sbdb:vesta") is None


def test_sbdb_lookup_uses_snapshot_only_when_jpl_is_unreachable(monkeypatch):
    async def down(*args, **kwargs):
        raise jc.JPLUnavailable("ConnectError: no route to host")

    monkeypatch.setattr(jc, "_get", down)
    with pytest.raises(jc.JPLUnavailable):  # no snapshot: the 502 stands
        asyncio.run(jc.sbdb_lookup("1 Ceres"))

    offline.save("sbdb", "sbdb:1 ceres", {"match": {"name": "1 Ceres", "is_simulated": False}})
    res = asyncio.run(jc.sbdb_lookup("1 Ceres"))
    assert res["match"]["name"] == "1 Ceres"
    assert "saved_at" in res["offline_snapshot"]


def test_planetx_uses_snapshot_when_jpl_is_unreachable(monkeypatch):
    async def down(*args, **kwargs):
        raise jc.JPLUnavailable("offline")

    monkeypatch.setattr(jc, "sbdb_query_etnos", down)
    with pytest.raises(jc.JPLUnavailable):
        asyncio.run(etno.etno_analysis())

    offline.save("planetx", etno.SNAPSHOT_KEY, {"objects": [], "source": "NASA/JPL SBDB", "is_simulated": False})
    res = asyncio.run(etno.etno_analysis())
    assert res["source"] == "NASA/JPL SBDB" and "offline_snapshot" in res


def _coverage_file(archive: SpherexArchive, ra: float, dec: float):
    key = f"{ra:.3f}:{dec:.3f}"
    return archive.cache_dir / f"coverage_{hashlib.md5(key.encode()).hexdigest()[:16]}.json"


ROW = {"obs_collection": "spherex_qr", "obs_id": "2025W20_1A_0001_1D4", "t_min": "60800.1", "t_max": "60800.1",
       "em_min": "2.4e-6", "em_max": "3.8e-6", "energy_bandpassname": "SPHEREx-D4"}


class _DownClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        raise httpx.ConnectError("no route to host")


def test_coverage_falls_back_to_last_real_list(tmp_path, monkeypatch):
    archive = SpherexArchive(cache_dir=tmp_path / "spherex")
    monkeypatch.setattr(httpx, "AsyncClient", _DownClient)

    with pytest.raises(SpherexError):  # nothing cached: no invented coverage
        asyncio.run(archive.query_frames(10.0, 20.0))

    cov = _coverage_file(archive, 10.0, 20.0)
    cov.write_text(json.dumps([ROW]), encoding="utf-8")
    old = time.time() - 7 * 24 * 3600
    os.utime(cov, (old, old))  # older than the 6 h TTL: normally IRSA would be asked again
    frames = asyncio.run(archive.query_frames(10.0, 20.0))
    assert [f.detector for f in frames] == [4]
    assert archive.offline_note(10.0, 20.0) is not None
    # a stale list is not kept in memory, so the archive is asked again once it is back
    assert "10.000:20.000" not in archive._coverage_cache


def test_known_offline_skips_the_tap_request(tmp_path, monkeypatch):
    import app.services.spherex_archive as sa

    archive = SpherexArchive(cache_dir=tmp_path / "spherex")
    cov = _coverage_file(archive, 10.0, 20.0)
    cov.write_text(json.dumps([ROW]), encoding="utf-8")
    old = time.time() - 7 * 24 * 3600
    os.utime(cov, (old, old))  # older than the 6 h coverage TTL

    async def offline_now(force: bool = False) -> bool:
        return False

    class _Fail:
        def __init__(self, *a, **k):
            raise AssertionError("no network request may be made when known offline")

    monkeypatch.setattr(sa, "is_online", offline_now)
    monkeypatch.setattr(httpx, "AsyncClient", _Fail)
    frames = asyncio.run(archive.query_frames(10.0, 20.0))
    assert len(frames) == 1 and archive.offline_note(10.0, 20.0)


def test_kiosk_password_only_for_the_pi_itself(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "WIFI_AP_SSID", "OrbitScope")
    monkeypatch.setattr(settings, "WIFI_AP_PASSWORD", "s3cret-pass")
    monkeypatch.setattr(settings, "PUBLIC_URL", "http://10.42.0.1")
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    client = TestClient(app)
    local = client.get("/api/v1/system/kiosk", headers={"X-Real-IP": "127.0.0.1"}).json()["data"]
    phone = client.get("/api/v1/system/kiosk", headers={"X-Real-IP": "10.42.0.23"}).json()["data"]
    assert local["wifi"]["password"] == "s3cret-pass" and local["public_url"] == "http://10.42.0.1"
    assert phone["wifi"] == {"ssid": "OrbitScope", "security": "WPA"}


def test_kiosk_local_check_fails_closed_behind_untrusted_proxy(monkeypatch):
    from types import SimpleNamespace

    from app.api.routes.system import _is_local_client
    from app.core.config import settings

    def req(headers):
        return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers=headers)

    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
    assert _is_local_client(req({}))                                   # kiosk browser, no proxy
    assert not _is_local_client(req({"x-forwarded-for": "10.42.0.23"}))  # visitor through nginx
    assert not _is_local_client(req({"x-real-ip": "10.42.0.23"}))
