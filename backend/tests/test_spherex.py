"""Offline tests for the real-data SPHEREx blink service (no network access)."""
from __future__ import annotations

import base64

import numpy as np
import pytest
from astropy.wcs import WCS
from fastapi.testclient import TestClient

from app.main import app
from app.services import spherex_archive as sa
from app.services.target_resolver import find_builtin, parse_coordinates


# ---------------------------------------------------------------- resolver
@pytest.mark.parametrize(
    "text, ra, dec",
    [
        ("269.452 4.693", 269.452, 4.693),
        ("269.452, -4.693", 269.452, -4.693),
        ("08h55m10.831s -7d14m42.53s", 133.795129, -7.245147),
        ("17:57:48.5 +04:41:36", 269.452083, 4.693333),
        ("17 57 48.5 +04 41 36", 269.452083, 4.693333),
    ],
)
def test_parse_coordinates(text: str, ra: float, dec: float) -> None:
    out = parse_coordinates(text)
    assert out is not None
    assert out[0] == pytest.approx(ra, abs=1e-4)
    assert out[1] == pytest.approx(dec, abs=1e-4)


@pytest.mark.parametrize("text", ["Barnard's Star", "M31", "400 10", "12 -95", ""])
def test_parse_coordinates_rejects_names_and_out_of_range(text: str) -> None:
    assert parse_coordinates(text) is None


@pytest.mark.parametrize("text, tid", [("Barnard's Star", "barnard"), ("eps indi b", "eps-indi-b"),
                                       ("WISE 0855-0714", "wise-0855"), ("RW Aur", "rw-aur"), ("r draconis", "r-dra")])
def test_builtin_targets(text: str, tid: str) -> None:
    t = find_builtin(text)
    assert t is not None and t["id"] == tid


def test_proper_motion_propagation_barnard() -> None:
    # Barnard's Star moves ~10.36"/yr north: 10 years -> ~103.6"
    ra, dec = sa.propagate(269.4485, 4.7394, -801.551, 10362.394, 2016.0, 2026.0)
    assert (dec - 4.7394) * 3600 == pytest.approx(103.62, abs=0.05)
    assert ra < 269.4485


# ---------------------------------------------------------------- grouping
def _rec(mjd: float, det: int = 3) -> sa.FrameRecord:
    return sa.FrameRecord(obs_id=f"OBS{mjd:.0f}_{det}", collection="spherex_qr2", detector=det, mjd=mjd,
                          em_min_um=1.6, em_max_um=2.4)


def test_group_epochs_splits_on_gaps() -> None:
    frames = [_rec(m) for m in (60900, 60905, 60912, 61110, 61120, 61270)]
    groups = sa.group_epochs(frames)
    assert [len(g) for g in groups] == [3, 2, 1]


def test_select_groups_limits_downloads() -> None:
    frames = [_rec(60900 + i) for i in range(20)] + [_rec(61200 + i) for i in range(20)]
    epochs = sa.select_groups(frames, "epoch", per_epoch=4, max_frames=16)
    assert len(epochs) == 2 and all(len(g) == 4 for g in epochs)
    singles = sa.select_groups(frames, "frames", per_epoch=4, max_frames=10)
    assert len(singles) == 10 and all(len(g) == 1 for g in singles)
    assert [g[0].mjd for g in singles] == sorted(g[0].mjd for g in singles)


# ---------------------------------------------------------------- imaging
def test_fill_saturated_holes_fills_interior_only() -> None:
    img = np.ones((21, 21), np.float32)
    img[9:12, 9:12] = np.nan  # saturated core
    img[0, 0:3] = np.nan  # edge gap must stay NaN
    out, filled = sa.fill_saturated_holes(img)
    assert np.isfinite(out[10, 10]) and filled[10, 10]
    assert np.isnan(out[0, 1]) and not filled[0, 1]


def _cutout(shift_px: float = 0.0) -> sa.Cutout:
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [100.0, 10.0]
    w.wcs.crpix = [31.0 + shift_px, 31.0]
    w.wcs.cdelt = [-6.15 / 3600, 6.15 / 3600]
    yy, xx = np.mgrid[0:61, 0:61]
    image = np.exp(-(((xx - 30 - shift_px) ** 2 + (yy - 30) ** 2) / 4.0)).astype(np.float32) * 100
    flags = np.zeros_like(image, dtype=np.int64)
    flags[5, 5] = 1 << sa.DEFAULT_FLAG_BITS["HOT"]
    return sa.Cutout(_rec(60900), "u", image, flags, np.ones_like(image), w, 60900.0, 2.0, dict(sa.DEFAULT_FLAG_BITS))


def test_reproject_keeps_star_at_sky_position() -> None:
    out_wcs = sa.make_target_wcs(100.0, 10.0, 31, 6.15)
    yy, xx = np.mgrid[0:31, 0:31]
    wr, wd = out_wcs.pixel_to_world_values(xx, yy)
    for shift in (0.0, 3.0):  # pointing offset must not move the star on the sky grid
        img, var, mask, _ = sa.reproject_cutout(_cutout(shift), wr, wd)
        y, x = np.unravel_index(np.nanargmax(img), img.shape)
        assert (x, y) == (15, 15)


def test_reproject_masks_flagged_pixels() -> None:
    c = _cutout()
    out_wcs = sa.make_target_wcs(100.0, 10.0, 61, 6.15)
    yy, xx = np.mgrid[0:61, 0:61]
    wr, wd = out_wcs.pixel_to_world_values(xx, yy)
    img, _, mask, stats = sa.reproject_cutout(c, wr, wd)
    assert mask[5, 5] and np.isnan(img[5, 5])
    assert stats.get("HOT", 0) > 0


def test_assemble_coadds_and_encodes(tmp_path) -> None:
    arch = sa.SpherexArchive(cache_dir=tmp_path)
    c1, c2 = _cutout(), _cutout()
    c2.record = _rec(60901)
    out_wcs = sa.make_target_wcs(100.0, 10.0, 31, 6.15)
    frames = arch._assemble([[c1.record, c2.record]], {c1.record.key: c1, c2.record.key: c2},
                            out_wcs, 31, 100.0, 10.0, None, None, 2000.0, False)
    assert len(frames) == 1 and frames[0]["n_frames"] == 2
    arr = np.frombuffer(base64.b64decode(frames[0]["data"]), dtype="<f4").reshape(31, 31)
    assert np.nanargmax(arr) == 15 * 31 + 15
    assert frames[0]["target_px"] == [15.0, 15.0]


def test_aperture_photometry_recovers_flux_and_flags_saturation() -> None:
    c = _cutout()
    p = sa.aperture_photometry(c, 100.0, 10.0, r_ap=3.0)
    assert p is not None and not p["flagged"]
    omega = (6.15 / 206264.806) ** 2
    expected = 100 * 2 * np.pi * 2.0 * (1 - np.exp(-9 / 4.0)) * omega * 1e9  # Gaussian sigma^2 = 2
    assert p["flux_mjy"] == pytest.approx(expected, rel=0.05)
    assert p["wavelength_um"] == pytest.approx(2.0)

    c.flags[29:32, 29:32] |= 1 << sa.DEFAULT_FLAG_BITS["OVERFLOW"]
    c.flags[28:33, 28:33] |= 1 << sa.DEFAULT_FLAG_BITS["HOT"]  # mostly-masked aperture
    sat = sa.aperture_photometry(c, 100.0, 10.0, r_ap=3.0)
    assert sat["saturated"] and sat["flagged"]
    # Every value must be a plain Python type so FastAPI can serialise it (numpy.bool_ caused a 500).
    import json
    json.dumps(sat)
    assert all(type(v) in (int, float, str, bool, type(None)) for v in sat.values())


def test_aperture_photometry_off_image_returns_none() -> None:
    assert sa.aperture_photometry(_cutout(), 100.5, 10.0) is None


def test_select_for_photometry_spreads_over_detectors() -> None:
    frames = [_rec(60900 + i, det) for det in range(1, 7) for i in range(30)]
    picked = sa.select_for_photometry(frames, 36)
    assert len(picked) == 36
    assert {f.detector for f in picked} == {1, 2, 3, 4, 5, 6}


def test_catwise_filters_artifacts_and_untrusted_motion(monkeypatch) -> None:
    import asyncio

    from app.services import catalog_overlay as co

    rows = [
        {"source_name": "A", "ra": "10", "dec": "1", "pmra": "1.0", "pmdec": "0", "sigpmra": "0.01", "sigpmdec": "0.01",
         "w1mpro": "10", "w2mpro": "9", "ab_flags": "00", "nb": "1"},
        {"source_name": "HALO", "ra": "10", "dec": "1", "pmra": "2.0", "pmdec": "0", "sigpmra": "0.01", "sigpmdec": "0.01",
         "w1mpro": "10", "w2mpro": "9", "ab_flags": "0H", "nb": "3"},
        {"source_name": "BLEND", "ra": "10", "dec": "1", "pmra": "2.0", "pmdec": "0", "sigpmra": "0.01", "sigpmdec": "0.01",
         "w1mpro": "10", "w2mpro": "9", "ab_flags": "00", "nb": "2"},
    ]

    async def fake_tap(url, query, extra=None):
        return rows

    monkeypatch.setattr(co, "_tap", fake_tap)
    co._cache.clear()
    res = asyncio.run(co.fetch_catalog("catwise", 10.0, 1.0, 0.05))
    ids = [s["id"] for s in res["sources"]]
    assert ids == ["CWISE A", "CWISE BLEND"]
    assert res["sources"][0]["pmra"] == pytest.approx(1000.0)  # arcsec/yr -> mas/yr
    assert res["sources"][1]["pmra"] == 0.0  # blended: motion not trusted
    assert res["ref_epoch"] == 2015.4


# ---------------------------------------------------------------- API (offline paths)
@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_targets_endpoint(client: TestClient) -> None:
    res = client.get("/api/v1/spherex/targets")
    assert res.status_code == 200
    ids = {t["id"] for t in res.json()["data"]["targets"]}
    assert {"barnard", "eps-indi-b", "wise-0855", "rw-aur", "r-dra"} <= ids


def test_resolve_coordinates_endpoint(client: TestClient) -> None:
    res = client.get("/api/v1/spherex/resolve", params={"q": "10.5 -20.25"})
    assert res.status_code == 200
    d = res.json()["data"]
    assert d["ra"] == pytest.approx(10.5) and d["dec"] == pytest.approx(-20.25) and d["source"] == "coordinates"


def test_challenge_coordinates_recognise_fast_mover(client: TestClient) -> None:
    """The challenge gives WISE 0855 at its ~2010 position; its proper motion must still be applied."""
    d = client.get("/api/v1/spherex/resolve", params={"q": "08h55m10.831s -7d14m42.53s"}).json()["data"]
    assert d["name"] == "WISE 0855-0714" and d["pmra"] == pytest.approx(-8123.7)
    assert 2008 <= d["matched_epoch"] <= 2012


def test_blink_rejects_bad_detector_localized(client: TestClient) -> None:
    res = client.get("/api/v1/spherex/blink", params={"ra": 10, "dec": 10, "detector": "9", "locale": "az"})
    assert res.status_code == 400
    assert "Detektor" in res.json()["detail"]


def test_unhandled_errors_are_json_with_cors(monkeypatch) -> None:
    from app.api.routes import spherex as route

    async def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(route.spherex_archive, "query_frames", boom)
    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.get("/api/v1/spherex/coverage", params={"ra": 10, "dec": 10},
                    headers={"Origin": "http://localhost:5174"})
    assert res.status_code == 500
    assert "RuntimeError" in res.json()["detail"]
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5174"


def test_cache_prune_removes_oldest(tmp_path) -> None:
    import os
    import time as _t

    arch = sa.SpherexArchive(cache_dir=tmp_path)
    cut = tmp_path / "cutouts"
    for i in range(5):
        f = cut / f"c{i}.fits"
        f.write_bytes(b"x" * 400_000)  # 0.4 MB each
        old = _t.time() - (100 - i)
        os.utime(f, (old, old))
    assert arch.cache_stats()["cutouts"] == 5
    res = arch.prune_cache(max_mb=1.0)
    assert res["removed"] == 3
    assert sorted(p.name for p in cut.glob("*.fits")) == ["c3.fits", "c4.fits"]


def test_status_endpoint(client: TestClient, monkeypatch) -> None:
    from app.api.routes import spherex as route

    async def fake_irsa():
        return {"reachable": True, "latency_ms": 1}

    monkeypatch.setattr(route, "_irsa_reachable", fake_irsa)
    d = client.get("/api/v1/spherex/status").json()["data"]
    assert d["irsa"]["reachable"] is True
    assert {"cutouts", "size_mb", "limit_mb"} <= set(d["cache"])
    assert isinstance(d["jobs"], dict)


def test_blink_validates_fov(client: TestClient) -> None:
    assert client.get("/api/v1/spherex/blink", params={"ra": 10, "dec": 10, "fov": 5}).status_code == 422
