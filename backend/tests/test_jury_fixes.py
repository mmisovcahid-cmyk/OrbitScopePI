"""Regression tests for the fixes found by the jury-readiness audit (offline, synthetic data)."""
from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.pipeline import moving_objects as mo
from app.services import candidate_store as cs
from app.services.spherex_archive import FrameRecord, SpherexArchive

N = 61


def _blob(x: float, y: float, amp: float) -> np.ndarray:
    yy, xx = np.mgrid[0:N, 0:N]
    return amp * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / 2.0)


def _det(frame, mjd, x, y, z, det=1):
    return mo.Detection(frame, mjd, (det,), x, y, z, z, False)


# ---------------------------------------------------------------- proper motion: forced target
def test_faint_target_is_measured_with_forced_astrometry() -> None:
    """A target too faint for the blind search (S/N ~6 < 10) is still measured and reported."""
    rng = np.random.default_rng(11)
    mjds = [60800.0, 60990.0, 61170.0]
    frames = [rng.normal(0, 1.0, (N, N)) + _blob(30 + 0.9 * k, 30, 5.0) for k in range(3)]  # moves 0.9 px/epoch
    blind = mo.search(frames, [None] * 3, mjds, [(6,)] * 3, 6.15, mode="proper_motion")
    assert not blind["tracks"]  # too faint for the blind search
    forced = mo.search(frames, [None] * 3, mjds, [(6,)] * 3, 6.15, mode="proper_motion", forced=[(30.9, 30.0)])
    assert len(forced["tracks"]) == 1
    tr = forced["tracks"][0]
    assert tr.extra["forced"] is True and tr.rate_px_per_day[0] > 0
    assert mo.classify(tr, "proper_motion", 6.15)[0] in ("proper_motion", "target_measurement")


def test_nonlinear_epochs_are_not_proper_motion() -> None:
    """Three epochs that jump back and forth (blend / edge effect) must not become a PM candidate."""
    rng = np.random.default_rng(12)
    mjds = [60800.0, 60990.0, 61170.0]
    xs = [30.0, 33.0, 30.2]  # out and back: no linear motion
    frames = [rng.normal(0, 0.3, (N, N)) + _blob(x, 25, 40.0) for x in xs]
    res = mo.search(frames, [None] * 3, mjds, [(4,)] * 3, 6.15, mode="proper_motion")
    assert not [t for t in res["tracks"] if mo.classify(t, "proper_motion", 6.15)[0] == "proper_motion"]


# ---------------------------------------------------------------- asteroids: quality rules
def _track(dets, visits=1):
    tr = mo.fit_track(dets)
    tr.visits = visits
    tr.extra.update(mo.track_quality(tr, [d.mjd for d in dets], [d.detectors for d in dets],
                                     {d.frame for d in dets}, (175, 175)))
    return tr


def test_zigzag_residual_is_not_a_mover() -> None:
    t = 61000.0
    dets = [_det(0, t, 100.0, 50.0, 9), _det(1, t + 0.0015, 99.3, 50.2, 9),
            _det(2, t + 0.003, 100.1, 50.8, 9), _det(3, t + 0.0045, 99.2, 50.6, 9)]
    tr = _track(dets)
    ok, why = mo.mover_quality_ok(tr)
    assert not ok and "no_steady_motion" in why
    assert mo.classify(tr, "asteroids", 6.15)[0] != "moving_object"


def test_flux_jump_is_not_a_mover() -> None:
    t = 61000.0
    dets = [_det(0, t, 100.0, 50.0, 5.5), _det(1, t + 0.0015, 101.0, 50.5, 6.0), _det(2, t + 0.0045, 103.0, 51.5, 50.0)]
    tr = _track(dets)
    ok, why = mo.mover_quality_ok(tr)
    assert not ok and "flux_jump" in why


def test_steady_bright_mover_passes_quality_rules() -> None:
    t = 61000.0  # like 626 Notburga: ~1 px per visit, consistent brightness, all four exposures
    dets = [_det(k, t + 0.0015 * k, 88.2 - 0.3 * k, 87.4 + 0.2 * k, 300 + 10 * k) for k in range(4)]
    tr = _track(dets)
    ok, why = mo.mover_quality_ok(tr)
    assert ok, why
    assert mo.classify(tr, "asteroids", 6.15)[0] == "moving_object"


def test_three_faint_points_are_low_confidence() -> None:
    t = 61000.0
    dets = [_det(k, t + 0.0015 * k, 50.0 - 0.6 * k, 120.0 - 0.3 * k, 6.0) for k in range(3)]
    tr = _track(dets)
    assert mo.classify(tr, "asteroids", 6.15)[0] == "low_confidence"


# ---------------------------------------------------------------- archive: withdrawn files
def test_withdrawn_collection_is_skipped(tmp_path) -> None:
    a = SpherexArchive(cache_dir=tmp_path)
    for i in range(12):
        a._urls[f"spherex_qr2:OBS{i}:D1"] = ""  # datalink: no Level-2 file
    a._urls["spherex_qr2:OBS99:D1"] = "https://irsa.example/level2_x.fits"
    a._urls["spherex_dr1:OBS1:D1"] = "https://irsa.example/level2_y.fits"
    qr2 = FrameRecord(obs_id="OBS50", collection="spherex_qr2", detector=1, mjd=61000.0, em_min_um=0.75, em_max_um=1.1)
    dr1 = FrameRecord(obs_id="OBS51", collection="spherex_dr1", detector=1, mjd=61000.0, em_min_um=0.75, em_max_um=1.1)
    assert a.available(qr2) is False and a.available(dr1) is True


# ---------------------------------------------------------------- review token
def test_review_needs_token_when_configured(tmp_path, monkeypatch) -> None:
    from app.core.config import settings

    s = cs.CandidateStore(tmp_path / "t.db")
    monkeypatch.setattr(cs, "_store", s)
    s.save_run("RUN-T", {}, {}, [{"id": "SPX-T", "search": "asteroids", "class": "unknown_mover", "score": 1.0,
                                  "ra": 1.0, "dec": 2.0, "t0_mjd": 61000.0, "detections": []}])
    monkeypatch.setattr(settings, "REVIEW_TOKEN", "team-secret")
    with TestClient(app) as c:
        no = c.patch("/api/v1/spherex/candidates/SPX-T", json={"status": "real"}, params={"locale": "az"})
        assert no.status_code == 403 and "token" in no.json()["detail"]
        bad = c.patch("/api/v1/spherex/candidates/SPX-T", json={"status": "real"}, headers={"X-Review-Token": "nope"})
        assert bad.status_code == 403
        ok = c.patch("/api/v1/spherex/candidates/SPX-T", json={"status": "real"}, headers={"X-Review-Token": "team-secret"})
        assert ok.status_code == 200 and ok.json()["data"]["status"] == "real"


@pytest.mark.parametrize("q,name", [("269.452 4.693", "Barnard's Star"), ("331.0765 -56.7938", "Epsilon Indi B")])
def test_target_coordinates_resolve_to_builtin(q, name) -> None:
    with TestClient(app) as c:
        d = c.get("/api/v1/spherex/resolve", params={"q": q}).json()["data"]
    assert d["name"] == name and d["pmra"] is not None
