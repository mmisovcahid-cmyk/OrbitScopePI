"""Ground Node: upload, EXIF metadata, trail detection, honest 'unavailable' answers."""
from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.services import ground_node as gn


@pytest.fixture(autouse=True)
def _ground_dir_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(gn, "root_dir", lambda: tmp_path / "ground")
    monkeypatch.setattr(gn, "solver_available", lambda: False)
    yield


def _star_field(seed: int = 1, shape=(300, 400), n=120, shift=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = rng.normal(20.0, 3.0, shape)
    srng = np.random.default_rng(99)  # same stars in every frame
    ys, xs = srng.integers(5, shape[0] - 5, n), srng.integers(5, shape[1] - 5, n)
    for y, x in zip(ys, xs):
        img[y - 1:y + 2, x + shift - 1:x + shift + 2] += 120.0
    return img


def _with_trail(img: np.ndarray) -> np.ndarray:
    out = img.copy()
    for t in range(0, 220):
        x, y = 60 + t, 50 + int(t * 0.6)
        out[y:y + 2, x] += 90.0
    return out


def test_detects_one_trail_and_ignores_slightly_drifting_stars():
    frames = [_star_field(i, shift=i) for i in range(5)]  # stars drift 1 px per frame
    frames[2] = _with_trail(frames[2])
    trails = gn.detect_trails(frames)
    assert len(trails) == 1
    t = trails[0]
    assert t["frame"] == 2 and t["length_px"] > 150
    assert 25 < t["angle_deg"] < 37  # atan(0.6) = 31 deg


def test_no_trail_no_detection():
    assert gn.detect_trails([_star_field(i) for i in range(4)]) == []


def test_too_few_frames():
    with pytest.raises(gn.GroundNodeError):
        gn.detect_trails([_star_field(1), _star_field(2)])


def _jpeg(arr: np.ndarray, when: str | None = "2026:11:13 19:30:05", offset: str | None = "+04:00") -> bytes:
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    exif = Image.Exif()
    exif[271], exif[272] = "Samsung", "SM-S918B"
    sub = exif.get_ifd(0x8769)
    if when:
        sub[36867] = when
    if offset:
        sub[36881] = offset
    sub[33434] = 10.0
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=95, exif=exif)
    return buf.getvalue()


def test_exif_time_is_converted_to_utc(tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(_jpeg(_star_field()))
    meta = gn.read_metadata(p)
    assert meta["time_utc"] == "2026-11-13T15:30:05Z"
    assert meta["camera"] == "Samsung SM-S918B" and meta["exposure_s"] == 10.0


def test_exif_without_timezone_is_flagged(tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(_jpeg(_star_field(), offset=None))
    meta = gn.read_metadata(p)
    assert meta["time_utc"] is None and meta["time_note"] == "no_timezone"


def test_upload_and_analyze_api_labels_provenance_and_missing_solver():
    from app.main import app

    client = TestClient(app)
    frames = [_star_field(i) for i in range(5)]
    frames[3] = _with_trail(frames[3])
    files = [("files", (f"IMG_{i:02d}.jpg", _jpeg(f, when=f"2026:11:13 19:30:{i * 10:02d}"), "image/jpeg"))
             for i, f in enumerate(frames)]
    r = client.post("/api/v1/ground/sessions", files=files, data={"label": "test night", "locale": "en"})
    assert r.status_code == 200, r.text
    s = r.json()["data"]
    assert s["source"] == "upload" and "Samsung SM-S918B" in s["provenance"]
    a = client.post(f"/api/v1/ground/sessions/{s['id']}/analyze").json()["data"]["analysis"]
    assert a["n_trails"] >= 1 and a["trails"][0]["frame"] == 3
    assert a["plate_solve"]["status"] == "unavailable" and "astrometry.net" in a["plate_solve"]["reason"]
    assert a["satellite_id"]["status"] == "unavailable"  # no GPS in these frames: says why
    assert client.get(f"/api/v1/ground/sessions/{s['id']}/frames/0.jpg").headers["content-type"] == "image/jpeg"
    assert client.get("/api/v1/ground/sessions").json()["data"][0]["n_trails"] >= 1


def test_capture_without_camera_is_a_clear_503(monkeypatch):
    from app.main import app

    monkeypatch.setattr(gn.shutil, "which", lambda name: None)
    r = TestClient(app).post("/api/v1/ground/capture", json={"frames": 3, "exposure_s": 1, "locale": "az"})
    assert r.status_code == 503 and "kamera" in r.json()["detail"].lower()


def test_session_id_cannot_escape_the_directory():
    with pytest.raises(gn.GroundNodeError):
        gn.get_session("../../etc")
