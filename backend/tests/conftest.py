"""Shared test setup: keep the suite offline and fast.

JPL SB Ident (~20 s per query) is disabled by default; tests that exercise it install their own
stub with ``monkeypatch.setattr`` (which takes precedence over this fixture).
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_sb_ident_network(monkeypatch):
    import app.services.small_bodies as sb

    async def offline(*args, **kwargs):
        raise RuntimeError("JPL SB Ident is disabled in the test suite")

    monkeypatch.setattr(sb, "objects_in_field", offline)
    yield


@pytest.fixture(autouse=True)
def _catalog_disk_cache_in_tmp(tmp_path, monkeypatch):
    """Tests use fake catalog rows: never let them land in the real on-disk catalog cache."""
    import app.services.catalog_overlay as co

    monkeypatch.setattr(co, "_disk_path", lambda key: tmp_path / f"cat_{abs(hash(key))}.json")
    yield


@pytest.fixture(autouse=True)
def _offline_snapshots_in_tmp(tmp_path, monkeypatch):
    """Snapshots written by tests go to a temp dir; connectivity is assumed (no TCP probes)."""
    import app.core.connectivity as conn
    import app.core.offline as off

    monkeypatch.setattr(off, "snapshot_dir", lambda: tmp_path / "offline")

    async def online(force: bool = False) -> bool:
        return True

    monkeypatch.setattr(conn, "is_online", online)
    for mod in ("app.services.spherex_archive", "app.services.catalog_overlay"):
        monkeypatch.setattr(f"{mod}.is_online", online)
    yield
