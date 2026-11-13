"""Live NASA/JPL catalog layer, tested offline with payloads in the real API formats."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import etno, jpl_catalog as jc

SBDB_CERES = {
    "object": {"fullname": "1 Ceres (A801 AA)", "des": "1", "kind": "an", "spkid": "20000001",
               "orbit_class": {"code": "MBA", "name": "Main-belt Asteroid"}, "neo": False, "pha": False},
    "orbit": {"epoch": "2461200.5", "moid": "1.58", "t_jup": "3.31", "condition_code": "0", "n_obs_used": 1075,
              "first_obs": "1995-01-05", "last_obs": "2021-03-23", "data_arc": "9520",
              "elements": [{"name": "a", "value": "2.77"}, {"name": "e", "value": "0.0796"}, {"name": "i", "value": "10.59"},
                           {"name": "om", "value": "80.25"}, {"name": "w", "value": "73.3"}, {"name": "q", "value": "2.55"},
                           {"name": "ad", "value": "2.99"}, {"name": "per", "value": "1680.5"}]},
    "phys_par": [{"name": "H", "value": "3.34"}, {"name": "diameter", "value": "939.4"}, {"name": "albedo", "value": "0.090"}],
    "discovery": {"discovery": "Discovered 1801-01-01 by Piazzi, G. at Palermo", "date": "1801-Jan-01", "who": "Piazzi, G.", "location": "Palermo"},
    "ca_data": [{"cd": "2056-Jun-26 01:01", "body": "Hygiea", "dist": "0.02583", "v_rel": "4.68"},
                {"cd": "1905-Jan-01 00:00", "body": "Vesta", "dist": "0.1", "v_rel": "5.0"}],
}

HORIZONS_TEXT = """*** header ***
 Date__(UT)__HR:MN, , , R.A._(ICRF), DEC_(ICRF),    APmag,  S-brt,                r,       rdot,             delta,     deldot,     S-O-T,/r,     S-T-O,
********************************************************************************************************************************************************
$$SOE
 2026-Nov-12 00:00, , ,   115.63604,   24.55862,    8.041,  6.802,   2.642084556205, -1.2374014,  2.05393053904499,-21.7486790,  115.9,/L,   19.6,
 2026-Nov-13 00:00, , ,   115.60001,   24.56000,    8.030,  6.800,   2.641000000000, -1.2000000,  2.04000000000000,-21.0000000,  116.5,/L,   19.4,
$$EOE
"""


class FakeResp:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


@pytest.fixture(autouse=True)
def clear_cache():
    jc._cache.clear()
    etno._cache.clear()
    yield


def _fake_get(table):
    async def fake(url, params, timeout=45.0):
        key = params.get("sstr") or params.get("COMMAND")
        status, payload = table[key]
        if status == "down":
            raise jc.JPLUnavailable("ConnectError: offline")
        return FakeResp(status, payload)
    return fake


def test_sbdb_object_parsed(monkeypatch) -> None:
    monkeypatch.setattr(jc, "_get", _fake_get({"Ceres": (200, SBDB_CERES)}))
    with TestClient(app) as c:
        d = c.get("/api/v1/catalog/object/Ceres").json()["data"]
    assert d["name"] == "1 Ceres (A801 AA)" and d["kind"] == "asteroid" and d["spkid"] == "20000001"
    assert d["elements"]["a_au"] == 2.77 and d["elements"]["period_yr"] == pytest.approx(4.601, abs=1e-3)
    assert d["physical"]["diameter_km"] == 939.4 and d["neo"] is False and d["pha"] is False
    assert d["close_approaches"]["upcoming"][0]["body"] == "Hygiea"
    assert d["close_approaches"]["recent"][0]["body"] == "Vesta"
    assert d["is_simulated"] is False and "JPL" in d["source"]


def test_sbdb_multiple_matches_and_not_found(monkeypatch) -> None:
    table = {"Halley": (300, {"code": "300", "list": [{"pdes": "2688", "name": "2688 Halley (1982 HG1)"}, {"pdes": "1P", "name": "1P/Halley"}]}),
             "nothing": (200, {"code": "200", "message": "specified object was not found"})}
    monkeypatch.setattr(jc, "_get", _fake_get(table))
    with TestClient(app) as c:
        m = c.get("/api/v1/catalog/object/Halley").json()["data"]["matches"]
        assert [x["designation"] for x in m] == ["2688", "1P"]
        r = c.get("/api/v1/catalog/object/nothing", params={"locale": "az"})
        assert r.status_code == 404 and "tapılmadı" not in r.json()["detail"] and "yoxdur" in r.json()["detail"]


def test_jpl_down_gives_502_not_fake_data(monkeypatch) -> None:
    monkeypatch.setattr(jc, "_get", _fake_get({"Ceres": ("down", {})}))
    with TestClient(app) as c:
        r = c.get("/api/v1/catalog/object/Ceres")
    assert r.status_code == 502
    assert "JPL" in r.json()["detail"]


def test_horizons_csv_parsing_and_command(monkeypatch) -> None:
    rows = jc.parse_horizons_csv(HORIZONS_TEXT)
    assert len(rows) == 2
    assert rows[0]["ra_deg"] == pytest.approx(115.63604) and rows[0]["dec_deg"] == pytest.approx(24.55862)
    assert rows[0]["magnitude"] == pytest.approx(8.041) and rows[0]["r_au"] == pytest.approx(2.642084556205)
    assert rows[0]["delta_au"] == pytest.approx(2.05393053904499) and rows[0]["elongation_deg"] == pytest.approx(115.9)
    assert rows[0]["phase_deg"] == pytest.approx(19.6)
    ceres = jc.parse_sbdb(SBDB_CERES, "Ceres")
    assert jc.horizons_command("Ceres", ceres) == "DES=20000001;"
    assert jc.horizons_command("1P", {**ceres, "kind": "comet", "designation": "1P"}) == "DES=1P;CAP;"
    assert jc.horizons_command("Mars", None) == "499"

    monkeypatch.setattr(jc, "_get", _fake_get({
        "Ceres": (200, SBDB_CERES),
        "'DES=20000001;'": (200, {"result": "Target body name: 1 Ceres (A801 AA)   {source: JPL#48}\n" + HORIZONS_TEXT}),
    }))
    with TestClient(app) as c:
        d = c.get("/api/v1/catalog/ephemeris", params={"target": "Ceres", "days": 2}).json()["data"]
    assert d["resolved_name"] == "1 Ceres (A801 AA)" and len(d["rows"]) == 2 and d["is_simulated"] is False


def test_nearby_uses_sb_ident(monkeypatch) -> None:
    import app.services.small_bodies as sb

    async def fake_field(ra, dec, hw, mjd, vlim):
        return [{"name": "626 Notburga (A907 CH)", "kind": "asteroid", "ra": 9.6915, "dec": 4.0152, "mjd": mjd,
                 "vmag": 13.5, "rate_ra": 45.19, "rate_dec": 45.93},
                {"name": "far away", "kind": "asteroid", "ra": 11.0, "dec": 4.0, "mjd": mjd, "vmag": 18.0, "rate_ra": 1, "rate_dec": 1}]

    monkeypatch.setattr(sb, "objects_in_field", fake_field)
    with TestClient(app) as c:
        d = c.get("/api/v1/catalog/nearby", params={"ra": 9.69, "dec": 4.015, "radius": 0.3, "time": "2025-06-24T11:10"}).json()["data"]
    assert [o["name"] for o in d["objects"]] == ["626 Notburga (A907 CH)"]  # second is outside the circle
    assert d["objects"][0]["rate_arcsec_per_hour"] == pytest.approx(64.44, abs=0.01)
    assert d["time_utc"] == "2025-06-24T11:10:00Z"


def test_get_retries_on_503_then_succeeds(monkeypatch) -> None:
    import httpx

    calls = {"n": 0}

    async def fake_get(self, url, params=None):
        calls["n"] += 1
        return httpx.Response(503 if calls["n"] < 3 else 200, json={"ok": True})

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(jc.asyncio, "sleep", no_sleep)
    jc._sem = None
    resp = asyncio.run(jc._get("https://example.invalid", {}))
    assert resp.status_code == 200 and calls["n"] == 3


def test_rayleigh_and_etno_clustering(monkeypatch) -> None:
    r = etno.rayleigh([60, 62, 58, 61, 59, 63])
    assert r["p"] < 0.01 and abs(r["mean_deg"] - 60.5) < 1
    spread = etno.rayleigh([0, 60, 120, 180, 240, 300])
    assert spread["p"] > 0.5

    rows = []
    for i, des in enumerate(etno.ETNO_DESIGNATIONS):  # literature objects: tightly clustered
        rows.append({"pdes": des, "full_name": f"({des})", "a": str(300 + i), "e": "0.8", "i": "10", "q": "40",
                     "om": str(100 + 2 * i), "w": str(300 - i), "ad": "600", "H": "5", "condition_code": "2"})
    for i in range(40):  # other well-determined objects: random orientations
        rows.append({"pdes": f"2099 X{i}", "full_name": f"(2099 X{i})", "a": "200", "e": "0.8", "i": "10", "q": "35",
                     "om": str((i * 97) % 360), "w": str((i * 53) % 360), "ad": "400", "H": "6", "condition_code": "4"})
    rows.append({"pdes": "2099 BAD", "full_name": "(2099 BAD)", "a": "500", "e": "0.9", "i": "5", "q": "40",
                 "om": "60", "w": "0", "ad": "900", "H": "8", "condition_code": "9"})  # poor orbit: excluded

    async def fake_query(min_a, min_q):
        assert (min_a, min_q) == (150.0, 30.0)
        return rows

    monkeypatch.setattr(jc, "sbdb_query_etnos", fake_query)
    res = asyncio.run(etno.etno_analysis())
    assert res["varpi"]["n"] == len(etno.ETNO_DESIGNATIONS) + 40  # complete sample, poor orbit excluded
    lit = res["literature"]
    assert lit["n"] == len(etno.ETNO_DESIGNATIONS) and lit["missing"] == 0 and lit["varpi"]["p"] < 0.001
    assert res["varpi"]["p"] > lit["varpi"]["p"]  # random extra objects dilute the clustering
    bad = next(o for o in res["objects"] if o["designation"] == "2099 BAD")
    assert bad["in_sample"] is False
