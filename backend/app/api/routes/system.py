"""OrbitScope - System Monitoring API Endpoints
Provides system health checks, runtime metrics, cache statistics, and external NASA/JPL data source diagnostics.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
from typing import Any, Dict, Optional
import httpx
from fastapi import APIRouter, Query, Request

from app.core.cache import catalog_cache, observation_cache, pipeline_cache
from app.core.config import settings
from app.core.logging_config import get_logger
from app.models.schemas import ApiResponse, SystemStatus

logger = get_logger("routes.system")

router = APIRouter(prefix="/api/v1/system", tags=["System"])

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "health_success": "System is healthy",
        "status_success": "System status retrieved successfully",
        "datasources_success": "Data sources status retrieved successfully",
    },
    "az": {
        "health_success": "Sistem saz vəziyyətdədir",
        "status_success": "Sistem statusu uğurla əldə edildi",
        "datasources_success": "Məlumat mənbələrinin statusu uğurla əldə edildi",
    },
}


def _get_msg(locale: str, key: str) -> str:
    loc = locale.lower() if locale else "en"
    return MESSAGES.get(loc, MESSAGES["en"]).get(key, MESSAGES["en"].get(key, ""))


def _get_uptime_seconds(request: Request) -> float:
    """Calculate server uptime in seconds."""
    startup_time = getattr(request.app.state, "startup_time", None)
    if not startup_time:
        return 0.0
    now = datetime.now(timezone.utc)
    return (now - startup_time).total_seconds()


@router.get(
    "/health",
    response_model=ApiResponse,
    summary="System health check",
    description="Returns runtime status, server uptime, and software version.",
)
async def health_check(
    request: Request,
    locale: str = Query("en", description="Preferred response locale (en or az)"),
) -> ApiResponse:
    """Perform basic health check."""
    uptime = _get_uptime_seconds(request)
    data = {
        "status": "healthy",
        "uptime_seconds": round(uptime, 2),
        "version": settings.APP_VERSION,
        "app_name": settings.APP_NAME,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return ApiResponse(
        success=True,
        data=data,
        message=_get_msg(locale, "health_success"),
        locale=locale,
        is_simulated=False,
    )


@router.get(
    "/status",
    response_model=ApiResponse,
    summary="System detailed status",
    description="Returns uptime, cache statistics, saved candidates and background jobs.",
)
async def system_status(
    request: Request,
    locale: str = Query("en", description="Preferred response locale (en or az)"),
) -> ApiResponse:
    """Return comprehensive system status."""
    from app.services.candidate_store import get_store
    from app.services.jobs import job_manager
    from app.services.spherex_archive import spherex_archive

    from app.core import offline
    from app.core.connectivity import is_online

    uptime = _get_uptime_seconds(request)
    online = await is_online()
    live = "live" if online else "offline (cached data only)"
    total_cache_size = (
        getattr(catalog_cache, "size", 0)
        + getattr(observation_cache, "size", 0)
        + getattr(pipeline_cache, "size", 0)
    )
    try:
        cutouts = spherex_archive.cache_stats()
    except Exception as exc:  # noqa: BLE001 - status must never fail
        cutouts = {"error": str(exc)}

    status_data = SystemStatus(
        status="operational",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        uptime_seconds=round(uptime, 2),
        components={
            "data_sources": {
                "IRSA_SPHEREX": live,
                "GAIA_DR3": live,
                "CATWISE2020": live,
                "JPL_SBDB": live,
                "JPL_HORIZONS": live,
                "JPL_SB_IDENT": live,
            },
            "network": {"online": online, **offline.stats()},
            "cache_size": total_cache_size,
            "spherex_cutout_cache": cutouts,
            "candidates": get_store().counts(),
            "jobs": job_manager.stats(),
            "rate_limit_per_minute": settings.RATE_LIMIT_PER_MINUTE,
        },
    )

    return ApiResponse(
        success=True,
        data=status_data,
        message=_get_msg(locale, "status_success"),
        locale=locale,
        is_simulated=False,
    )


def _is_local_client(request: Request) -> bool:
    """True for the kiosk browser on the Pi itself (directly, or through the bundled nginx)."""
    loopback = ("127.0.0.1", "::1", "localhost")
    host = request.client.host if request.client else ""
    if settings.TRUST_PROXY_HEADERS:
        host = (request.headers.get("x-real-ip") or host).strip()
    # Fail closed: a proxy that names any non-loopback client means a visitor, even when the
    # proxy headers are not otherwise trusted (nginx alone would make every visitor 127.0.0.1).
    for h in ("x-real-ip", "x-forwarded-for"):
        named = [v.strip() for v in request.headers.get(h, "").split(",") if v.strip()]
        if any(v not in loopback for v in named):
            return False
    return host in loopback


@router.get(
    "/kiosk",
    response_model=ApiResponse,
    summary="Kiosk screen info (Wi-Fi access point + public address)",
    description="What the kiosk screen shows as QR codes. The Wi-Fi password is only returned to the Pi itself.",
)
async def kiosk_info(
    request: Request,
    locale: str = Query("en", description="Preferred response locale (en or az)"),
) -> ApiResponse:
    local = _is_local_client(request)
    wifi = None
    if settings.WIFI_AP_SSID:
        wifi = {"ssid": settings.WIFI_AP_SSID, "security": "WPA" if settings.WIFI_AP_PASSWORD else "nopass"}
        if local and settings.WIFI_AP_PASSWORD:
            wifi["password"] = settings.WIFI_AP_PASSWORD
    return ApiResponse(
        success=True,
        data={"public_url": settings.PUBLIC_URL or None, "wifi": wifi, "local_client": local},
        message=_get_msg(locale, "status_success"),
        locale=locale,
        is_simulated=False,
    )


@router.get(
    "/datasources",
    response_model=ApiResponse,
    summary="List external data sources and verify reachability",
    description="Pings NASA/JPL and IRSA endpoints with short timeouts to verify network reachability and service status.",
)
async def list_datasources(
    request: Request,
    locale: str = Query("en", description="Preferred response locale (en or az)"),
) -> ApiResponse:
    """Ping external astronomical services and return status."""
    async def _ping_endpoint(url: str, name: str, params: Optional[dict] = None) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=3.5) as client:
                resp = await client.get(url, params=params)
                latency_ms = round((time.perf_counter() - start) * 1000, 2)
                return {
                    "name": name,
                    "endpoint": url,
                    "status": "online" if resp.status_code < 500 else "degraded",
                    "http_status": resp.status_code,
                    "latency_ms": latency_ms,
                    "is_live": True,
                }
        except httpx.TimeoutException:
            return {
                "name": name,
                "endpoint": url,
                "status": "degraded (timeout)",
                "latency_ms": 3500.0,
                "is_live": False,
            }
        except Exception as err:
            return {
                "name": name,
                "endpoint": url,
                "status": "offline",
                "error": str(err),
                "is_live": False,
            }

    # Parallel ping probes of every archive the real-data pages use
    results = await asyncio.gather(
        _ping_endpoint(settings.IRSA_TAP_URL, "NASA/IPAC IRSA (SPHEREx, CatWISE2020)", {"REQUEST": "getCapabilities"}),
        _ping_endpoint("https://gea.esac.esa.int/tap-server/tap/availability", "ESA Gaia Archive (DR3)"),
        _ping_endpoint(settings.JPL_SBDB_URL, "NASA/JPL Small-Body Database", {"sstr": "Ceres"}),
        _ping_endpoint(settings.JPL_HORIZONS_URL, "NASA/JPL Horizons System", {"format": "json"}),
        _ping_endpoint("https://ssd-api.jpl.nasa.gov/sb_ident.api", "NASA/JPL SB Ident"),
        return_exceptions=True,
    )

    data_sources_list: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, dict):
            data_sources_list.append(r)
        else:
            data_sources_list.append({"status": "unknown", "error": str(r)})

    return ApiResponse(
        success=True,
        data=data_sources_list,
        message=_get_msg(locale, "datasources_success"),
        locale=locale,
        is_simulated=False,
    )
