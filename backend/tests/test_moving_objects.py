"""Tests for the real-data moving-object search (synthetic, offline)."""
from __future__ import annotations

import numpy as np
import pytest

from app.pipeline import moving_objects as mo
from app.services import small_bodies as sb

N = 61


def _star_field(rng: np.random.Generator) -> np.ndarray:
    img = np.zeros((N, N))
    yy, xx = np.mgrid[0:N, 0:N]
    for _ in range(25):
        x, y, f = rng.uniform(5, N - 5), rng.uniform(5, N - 5), rng.uniform(5, 60)
        img += f * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / 2.0)
    return img


def _blob(x: float, y: float, amp: float) -> np.ndarray:
    yy, xx = np.mgrid[0:N, 0:N]
    return amp * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / 2.0)


def _visits(rng, n_visits=4, per_visit=4, start=61000.0):
    """Exposure times: visits a day apart, 4 exposures ~2.2 min apart each."""
    return [start + v * 1.0 + k * 0.0015 for v in range(n_visits) for k in range(per_visit)]


def test_asteroid_found_in_one_visit_and_cosmic_ray_rejected() -> None:
    rng = np.random.default_rng(1)
    sky = _star_field(rng)
    mjds = _visits(rng)
    frames = []
    for i, t in enumerate(mjds):
        img = sky * rng.uniform(0.95, 1.05) + rng.normal(0, 1.0, (N, N))
        if 4 <= i < 8:  # visit 2: asteroid moving 0.6 px per exposure
            k = i - 4
            img += _blob(20 + 0.6 * k, 40 - 0.3 * k, 12.0)
        if i == 13:  # single-frame cosmic ray
            img[10, 50] += 40.0
        frames.append(img)
    res = mo.search(frames, [None] * len(frames), mjds, [(1,)] * len(frames), 6.15, mode="asteroids")
    tracks = [t for t in res["tracks"] if mo.classify(t, "asteroids", 6.15)[0] == "moving_object"]
    assert len(tracks) == 1
    t = tracks[0]
    assert len(t.detections) >= 3
    assert {d.frame for d in t.detections} <= {4, 5, 6, 7}
    x, y = t.position_at(mjds[4])
    assert abs(x - 20) < 1.0 and abs(y - 40) < 1.0
    # rate: 0.6 px / 0.0015 d = 400 px/day in x
    assert t.rate_px_per_day[0] == pytest.approx(400, rel=0.35)
    # the cosmic ray never forms a track
    assert all(not (abs(d.x - 50) < 2 and abs(d.y - 10) < 2) for tr in res["tracks"] for d in tr.detections)


def test_static_field_gives_no_moving_objects() -> None:
    rng = np.random.default_rng(2)
    sky = _star_field(rng)
    mjds = _visits(rng)
    frames = [sky * rng.uniform(0.9, 1.1) + rng.normal(0, 1.0, (N, N)) for _ in mjds]
    res = mo.search(frames, [None] * len(frames), mjds, [(1,)] * len(frames), 6.15, mode="asteroids")
    kinds = [mo.classify(t, "asteroids", 6.15)[0] for t in res["tracks"]]
    assert kinds.count("moving_object") == 0


def _paired_run(exposures_with_object: int):
    """D1 and D4 expose simultaneously; 4 visits of 2 exposures each."""
    rng = np.random.default_rng(3)
    sky = _star_field(rng)
    mjds, dets, frames = [], [], []
    for v in range(4):
        for k in range(2):
            for det in (1, 4):
                t = 61000.0 + v + k * 0.0015
                img = sky * rng.uniform(0.95, 1.05) + rng.normal(0, 1.0, (N, N))
                if v == 1 and k < exposures_with_object:
                    img += _blob(30 + 0.5 * k, 30, 15.0)
                mjds.append(t)
                dets.append((det,))
                frames.append(img)
    res = mo.search(frames, [None] * len(frames), mjds, dets, 6.15, mode="asteroids")
    return [(t, mo.classify(t, "asteroids", 6.15)[0]) for t in res["tracks"]]


def test_paired_detectors_confirm_detection_over_two_exposures() -> None:
    good = [t for t, k in _paired_run(2) if k == "moving_object"]
    assert len(good) == 1
    assert {d.detectors[0] for d in good[0].detections} == {1, 4}
    assert len(good[0].detections) == 4


def test_single_simultaneous_pair_is_only_low_confidence() -> None:
    kinds = [k for _, k in _paired_run(1)]
    assert "moving_object" not in kinds


def test_stationary_transient_is_not_a_mover() -> None:
    """A residual that reappears at the same spot in other visits (persistence, variable)."""
    rng = np.random.default_rng(7)
    sky = _star_field(rng)
    mjds = _visits(rng, n_visits=5)
    frames = []
    for i, _ in enumerate(mjds):
        img = sky + rng.normal(0, 1.0, (N, N))
        if 4 <= i < 8 or 12 <= i < 14:  # visit 2 (4 exposures) and part of visit 4
            img += _blob(40.0 + 0.2 * (i % 4), 20.0, 14.0)
        frames.append(img)
    res = mo.search(frames, [None] * len(frames), mjds, [(1,)] * len(frames), 6.15, mode="asteroids")
    kinds = [mo.classify(t, "asteroids", 6.15)[0] for t in res["tracks"]]
    assert "moving_object" not in kinds
    assert "stationary_transient" in kinds


def test_proper_motion_star_detected_across_epochs() -> None:
    rng = np.random.default_rng(4)
    base = _star_field(rng)
    mjds = [60900.0, 61080.0, 61270.0]  # ~6 months apart
    frames = []
    for k, t in enumerate(mjds):
        img = base + rng.normal(0, 0.3, (N, N)) + _blob(30, 28 + 1.2 * k, 40.0)  # 1.2 px per epoch north
        frames.append(img)
    res = mo.search(frames, [None] * 3, mjds, [(3,)] * 3, 6.15, mode="proper_motion")
    pm = [t for t in res["tracks"] if mo.classify(t, "proper_motion", 6.15)[0] == "proper_motion"]
    assert len(pm) == 1
    assert pm[0].rate_px_per_day[1] > 0  # moving north (+y)
    assert abs(pm[0].x0 - 30) < 1.0


def test_variable_star_is_not_a_mover() -> None:
    rng = np.random.default_rng(5)
    base = _star_field(rng)
    mjds = [60900.0, 61080.0, 61270.0]
    frames = [base + rng.normal(0, 0.3, (N, N)) + _blob(15, 45, a) for a in (5.0, 60.0, 5.0)]
    res = mo.search(frames, [None] * 3, mjds, [(3,)] * 3, 6.15, mode="proper_motion")
    kinds = [mo.classify(t, "proper_motion", 6.15)[0] for t in res["tracks"]]
    assert "proper_motion" not in kinds


def _shifted_field(seed: int, shift: tuple[float, float]) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.zeros((N, N))
    yy, xx = np.mgrid[0:N, 0:N]
    for _ in range(30):
        x, y, f = rng.uniform(6, N - 6), rng.uniform(6, N - 6), rng.uniform(20, 80)
        img += f * np.exp(-((xx - x - shift[0]) ** 2 + (yy - y - shift[1]) ** 2) / 2.0)
    return img


def test_global_registration_offset_is_not_proper_motion() -> None:
    """A whole-frame shift (WCS residual) must be removed, not reported as motion."""
    rng = np.random.default_rng(9)
    mjds = [60900.0, 61080.0, 61270.0]
    frames = [_shifted_field(11, s) + rng.normal(0, 0.3, (N, N)) for s in ((0, 0), (0.4, -0.3), (0.8, -0.6))]
    res = mo.search(frames, [None] * 3, mjds, [(3,)] * 3, 6.15, mode="proper_motion")
    kinds = [mo.classify(t, "proper_motion", 6.15)[0] for t in res["tracks"]]
    assert "proper_motion" not in kinds
    assert res["sources_measured"] >= 10


def test_proper_motion_rate_and_direction() -> None:
    rng = np.random.default_rng(12)
    mjds = [60900.0, 61265.25]  # exactly one year
    frames = []
    for k in range(2):
        img = _shifted_field(13, (0, 0)) + rng.normal(0, 0.3, (N, N))
        img += _blob(40 - 1.0 * k, 20 + 0.0 * k, 60.0)  # 1 px/yr towards +x... here -x = east
        frames.append(img)
    res = mo.search(frames, [None] * 2, mjds, [(3,)] * 2, 6.15, mode="proper_motion")
    pm = [t for t in res["tracks"] if mo.classify(t, "proper_motion", 6.15)[0] == "proper_motion"]
    assert len(pm) == 1
    vx, vy = pm[0].rate_px_per_day
    assert vx * 365.25 == pytest.approx(-1.0, abs=0.25)  # moving east (-x) about 1 px/yr
    assert abs(vy * 365.25) < 0.25


def test_masked_pixels_are_ignored() -> None:
    rng = np.random.default_rng(6)
    sky = _star_field(rng)
    mjds = _visits(rng)
    frames, masks = [], []
    for i, _ in enumerate(mjds):
        img = sky + rng.normal(0, 1.0, (N, N))
        m = np.zeros((N, N), bool)
        if 4 <= i < 8:
            img += _blob(25, 25, 30.0)
            m[22:29, 22:29] = True  # flagged by the pipeline
        frames.append(img)
        masks.append(m)
    res = mo.search(frames, masks, mjds, [(1,)] * len(frames), 6.15, mode="asteroids")
    assert not any(abs(d.x - 25) < 3 and abs(d.y - 25) < 3 for t in res["tracks"] for d in t.detections)


# ---------------------------------------------------------------- SB Ident helpers
def test_sb_ident_parsing_and_prediction() -> None:
    payload = {
        "fields_second": ["Object name", "Astrometric RA (hh:mm:ss)", "Astrometric Dec (dd mm'ss\")",
                          "Dist. from center RA (\")", "Dist. from center Dec (\")", "Dist. from center Norm (\")",
                          "Visual magnitude (V)", "RA rate (\"/h)", "Dec rate (\"/h)"],
        "data_second_pass": [
            ["2591 Dworetsky (1949 PS)", "00:40:34.53", "+04 11'47.0\"", "517.", "707.", "875.7", "17.1", "2.608E+01", "1.190E+01"],
            ["P/2019 LD2 (ATLAS)", "00:40:00.00", "-00 30'00.0\"", "0", "0", "0", "16.0", "-3.6E+01", "0"],
        ],
    }
    objs = sb.parse_sb_ident(payload, 61000.0)
    assert len(objs) == 2
    assert objs[0]["ra"] == pytest.approx((40 / 60 + 34.53 / 3600) * 15, abs=1e-6)
    assert objs[0]["dec"] == pytest.approx(4 + 11 / 60 + 47 / 3600, abs=1e-6)
    assert objs[1]["dec"] == pytest.approx(-0.5, abs=1e-6)
    assert objs[0]["kind"] == "asteroid" and objs[1]["kind"] == "comet"
    ra, dec = sb.predict(objs[0], 61000.0 + 1 / 24)  # one hour later
    assert (dec - objs[0]["dec"]) * 3600 == pytest.approx(11.9, abs=1e-6)
    assert (ra - objs[0]["ra"]) * 3600 * np.cos(np.radians(objs[0]["dec"])) == pytest.approx(26.08, abs=1e-3)


def test_sexagesimal_formatting_round_trips() -> None:
    assert sb._sexa_ra(10.0) == "00-40-00.00"
    assert sb._sexa_dec(-0.5) == "-00-30-00.0"
    assert sb._sexa_dec(4.196389) == "+04-11-47.0"


def test_cluster_times() -> None:
    cl = sb.cluster_times([61000.0, 61000.0015, 61000.003, 61001.0, 61001.2, 61005.0])
    assert [len(c) for c in cl] == [3, 2, 1]
