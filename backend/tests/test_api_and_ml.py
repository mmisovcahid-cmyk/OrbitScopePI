"""OrbitScope - API Routes & ML Unit Tests
Root, /system and /planetx endpoints, localization, and the public-deployment rate limit.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """FastAPI TestClient fixture."""
    with TestClient(app) as test_client:
        yield test_client


# ============================================================================
# Root and System Route Tests
# ============================================================================

def test_root_endpoint(client: TestClient) -> None:
    """Test GET / returns OrbitScope metadata and operational status."""
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["app"] == "OrbitScope"
    assert "documentation" in data
    assert data["status"] == "operational"


def test_system_health(client: TestClient) -> None:
    """Test GET /api/v1/system/health."""
    res = client.get("/api/v1/system/health")
    assert res.status_code == 200
    payload = res.json()
    assert payload["success"] is True
    assert payload["data"]["status"] == "healthy"
    assert "uptime_seconds" in payload["data"]


def test_system_status(client: TestClient) -> None:
    """Test GET /api/v1/system/status."""
    res = client.get("/api/v1/system/status")
    assert res.status_code == 200
    payload = res.json()
    assert payload["success"] is True
    assert payload["data"]["status"] == "operational"
    assert "components" in payload["data"]
    assert "cache_size" in payload["data"]["components"]


def test_system_datasources(client: TestClient) -> None:
    """Test GET /api/v1/system/datasources."""
    res = client.get("/api/v1/system/datasources")
    assert res.status_code == 200
    payload = res.json()
    assert payload["success"] is True
    assert isinstance(payload["data"], list)
    names = " ".join(d.get("name", "") for d in payload["data"])
    assert "Gaia" in names and "IRSA" in names and "SB Ident" in names
    assert not any(d.get("is_simulated") for d in payload["data"])


# ============================================================================
# Catalog Routes Tests
# ============================================================================

# Catalog endpoints now call live NASA/JPL services; they are tested offline with recorded
# payloads in tests/test_catalog_live.py.


# ============================================================================
# Planet X Routes Tests
# ============================================================================

def test_planetx_evidence(client: TestClient) -> None:
    """Test GET /api/v1/planetx/evidence."""
    res = client.get("/api/v1/planetx/evidence")
    assert res.status_code == 200
    payload = res.json()
    assert payload["success"] is True
    assert len(payload["data"]["evidence"]) >= 5
    assert len(payload["data"]["predictions"]) >= 5
    assert payload["is_simulated"] is False  # literature, not invented data


def test_planetx_tnos(client: TestClient, monkeypatch) -> None:
    """Test GET /api/v1/planetx/tnos (offline: live lookup fails -> literature table)."""
    import app.api.routes.planetx as px

    async def offline():
        raise RuntimeError("offline test")

    monkeypatch.setattr(px, "etno_analysis", offline)
    res = client.get("/api/v1/planetx/tnos")
    assert res.status_code == 200
    payload = res.json()
    assert payload["success"] is True
    assert len(payload["data"]) >= 6
    names = [t["name"] for t in payload["data"]]
    assert any("Sedna" in n for n in names)


def test_planetx_regions(client: TestClient) -> None:
    """Test GET /api/v1/planetx/regions."""
    res = client.get("/api/v1/planetx/regions")
    assert res.status_code == 200
    payload = res.json()
    assert payload["success"] is True
    assert len(payload["data"]) >= 2
    # Verify Batygin & Brown 40-100 deg RA prediction
    primary = payload["data"][0]
    assert primary["ra_min"] == 40.0
    assert primary["ra_max"] == 100.0


# ============================================================================
# i18n Localization Tests
# ============================================================================

def test_i18n_responses(client: TestClient) -> None:
    """Test API responses under English and Azerbaijani locales."""
    # Health check
    res_en = client.get("/api/v1/system/health?locale=en")
    assert res_en.status_code == 200
    assert "healthy" in res_en.json()["message"].lower()

    res_az = client.get("/api/v1/system/health?locale=az")
    assert res_az.status_code == 200
    assert "saz" in res_az.json()["message"].lower()

    # Planet X evidence
    res_ev_az = client.get("/api/v1/planetx/evidence?locale=az")
    assert res_ev_az.status_code == 200
    assert "elmi" in res_ev_az.json()["message"].lower()


def test_rate_limit_only_on_expensive_endpoints() -> None:
    """Expensive requests get 429 (with CORS headers) after the limit; cheap ones never do."""
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from app.core.rate_limit import RateLimitMiddleware, is_limited

    assert is_limited("GET", "/api/v1/spherex/blink.gif") and is_limited("POST", "/api/v1/jobs")
    assert not is_limited("GET", "/api/v1/jobs/abc") and not is_limited("GET", "/api/v1/spherex/status")

    async def ok(request):
        return PlainTextResponse("ok")

    mini = Starlette(routes=[Route("/api/v1/spherex/blink", ok), Route("/api/v1/spherex/status", ok)])
    mini.add_middleware(RateLimitMiddleware, per_minute=2)
    with TestClient(mini) as c:
        assert [c.get("/api/v1/spherex/blink").status_code for _ in range(3)] == [200, 200, 429]
        r = c.get("/api/v1/spherex/blink", params={"locale": "az"})
        assert r.status_code == 429 and "saniyə" in r.json()["detail"] and int(r.headers["Retry-After"]) >= 1
        assert all(c.get("/api/v1/spherex/status").status_code == 200 for _ in range(5))


def test_legacy_simulated_endpoints_are_gone(client: TestClient) -> None:
    for path in ("/api/v1/sky/regions", "/api/v1/observations", "/api/v1/detection/candidates"):
        assert client.get(path).status_code == 404
    assert "simulated" in client.get("/").json()["data"]


def test_validation_errors_are_localized(client: TestClient) -> None:
    az = client.get("/api/v1/spherex/blink", params={"ra": 400, "dec": 0, "locale": "az"})
    assert az.status_code == 422 and "Yanlış parametr 'ra'" in az.json()["detail"] and az.json()["errors"]
    en = client.get("/api/v1/catalog/ephemeris", params={"target": "Ceres", "days": 9999})
    assert en.status_code == 422 and en.json()["detail"] == "Invalid parameter 'days': must be at most 366."
    job = client.post("/api/v1/jobs", json={"kind": "blink", "params": {"ra": 1, "dec": 1, "fov": 9}, "locale": "az"})
    assert job.status_code == 422 and "fov" in job.json()["detail"] and "ən çox 0.5" in job.json()["detail"]
