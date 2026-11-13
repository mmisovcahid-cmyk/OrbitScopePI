"""Candidate store (SQLite) and review/export API - offline."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import candidate_store as cs


def _cand(cid: str, klass: str = "unknown_mover") -> dict:
    return {
        "id": cid, "search": "asteroids", "class": klass, "score": 0.9, "ra": 10.0, "dec": 4.0, "x": 1, "y": 2,
        "t0_mjd": 61000.0, "t0_date": "2025-12-01T00:00:00Z", "match": None,
        "detections": [
            {"frame": 0, "mjd": 61000.0, "date": "2025-12-01T00:00:00Z", "x": 1, "y": 2, "ra": 10.0, "dec": 4.0,
             "z": 7.5, "flux": 1.0, "detectors": [1], "on_star": False},
            {"frame": 1, "mjd": 61000.0015, "date": "2025-12-01T00:02:10Z", "x": 1.2, "y": 2, "ra": 9.9999, "dec": 4.0,
             "z": 8.1, "flux": 1.0, "detectors": [4], "on_star": False},
        ],
    }


@pytest.fixture()
def store(tmp_path, monkeypatch):
    s = cs.CandidateStore(tmp_path / "test.db")
    monkeypatch.setattr(cs, "_store", s)
    return s


def test_store_save_list_review(store) -> None:
    store.save_run("RUN-1", {"search": "asteroids"}, {"n": 2}, [_cand("SPX-A"), _cand("SPX-B", "known_sso")])
    assert {c["id"] for c in store.list()} == {"SPX-A", "SPX-B"}
    assert [c["id"] for c in store.list(klass="known_sso")] == ["SPX-B"]
    upd = store.review("SPX-A", "real", "clearly moving in blink")
    assert upd["status"] == "real" and upd["note"] == "clearly moving in blink"
    assert store.counts() == {"real": 1, "unreviewed": 1}
    assert store.review("NOPE", "real") is None
    with pytest.raises(ValueError):
        store.review("SPX-A", "maybe")


def test_store_survives_reopen(tmp_path) -> None:
    path = tmp_path / "persist.db"
    cs.CandidateStore(path).save_run("RUN-1", {}, {}, [_cand("SPX-P")])
    assert cs.CandidateStore(path).get("SPX-P")["class"] == "unknown_mover"


def test_review_and_export_api(store) -> None:
    store.save_run("RUN-1", {}, {}, [_cand("SPX-API")])
    with TestClient(app) as c:
        res = c.get("/api/v1/spherex/candidates")
        assert res.status_code == 200 and res.json()["data"]["candidates"][0]["id"] == "SPX-API"

        res = c.patch("/api/v1/spherex/candidates/SPX-API", json={"status": "artifact", "note": "ghost"})
        assert res.status_code == 200 and res.json()["data"]["status"] == "artifact"
        assert c.get("/api/v1/spherex/candidates", params={"status": "artifact"}).json()["data"]["counts"] == {"artifact": 1}

        assert c.patch("/api/v1/spherex/candidates/SPX-API", json={"status": "bogus"}).status_code == 422
        bad = c.patch("/api/v1/spherex/candidates/NOPE", json={"status": "real"}, params={"locale": "az"})
        assert bad.status_code == 404 and "tapılmadı" in bad.json()["detail"]

        csv = c.get("/api/v1/spherex/candidates/SPX-API/export")
        assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
        lines = csv.text.strip().splitlines()
        assert lines[0].startswith("candidate,class,date_utc") and len(lines) == 3
        assert "SPX-API,unknown_mover,2025-12-01T00:00:00Z" in lines[1]


def test_detect_validates_search_type() -> None:
    with TestClient(app) as c:
        assert c.get("/api/v1/spherex/detect", params={"ra": 10, "dec": 4, "search": "planets"}).status_code == 422
