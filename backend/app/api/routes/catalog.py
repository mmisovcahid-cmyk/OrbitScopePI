"""OrbitScope - live NASA/JPL catalog endpoints
==============================================
/api/v1/catalog/object/{query}   SBDB object (or a list of matches when ambiguous)
/api/v1/catalog/search?query=    same lookup, always returned as a list
/api/v1/catalog/ephemeris        JPL Horizons geocentric observer ephemeris
/api/v1/catalog/nearby           known asteroids/comets in a sky field (JPL SB Ident)

Every response is real JPL data. When JPL cannot be reached the endpoint answers 502 with
an explanation; it never substitutes invented values.
"""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query

from app.core.logging_config import get_logger
from app.services import jpl_catalog as jc

logger = get_logger("routes.catalog")

router = APIRouter(prefix="/api/v1/catalog", tags=["Catalog (NASA/JPL, live)"])

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "ok": "Data retrieved from NASA/JPL",
        "matches": "Several objects match - choose one",
        "not_found": "No object matching '{q}' in the JPL Small-Body Database.",
        "unavailable": "NASA/JPL did not respond ({why}). Please try again in a moment.",
        "bad_time": "Invalid date. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM.",
    },
    "az": {
        "ok": "Məlumat NASA/JPL-dən alındı",
        "matches": "Bir neçə obyekt uyğun gəlir - birini seçin",
        "not_found": "JPL Kiçik Cisimlər Bazasında '{q}' sorğusuna uyğun obyekt yoxdur.",
        "unavailable": "NASA/JPL cavab vermədi ({why}). Bir az sonra yenidən cəhd edin.",
        "bad_time": "Tarix yanlışdır. YYYY-MM-DD və ya YYYY-MM-DDTHH:MM formatından istifadə edin.",
    },
}


def _msg(locale: str, key: str, **kw: Any) -> str:
    return MESSAGES.get((locale or "en").lower(), MESSAGES["en"]).get(key, MESSAGES["en"][key]).format(**kw)


def _handle(exc: Exception, locale: str, q: str = "") -> HTTPException:
    if isinstance(exc, jc.NotFound):
        return HTTPException(status_code=404, detail=_msg(locale, "not_found", q=q))
    if isinstance(exc, jc.JPLUnavailable):
        return HTTPException(status_code=502, detail=_msg(locale, "unavailable", why=str(exc)[:120]))
    logger.exception(f"catalog error: {exc}")
    return HTTPException(status_code=500, detail=f"Internal error: {type(exc).__name__}")


@router.get("/object/{designation:path}", summary="Object data from JPL SBDB (or the list of matches)")
async def get_object(designation: str, locale: str = "en") -> dict[str, Any]:
    q = unquote(designation).strip()
    if not q:
        raise HTTPException(status_code=400, detail="Empty query")
    try:
        res = await jc.sbdb_lookup(q)
    except Exception as exc:
        raise _handle(exc, locale, q)
    if "matches" in res:
        return {"success": True, "message": _msg(locale, "matches"), "data": {"matches": res["matches"]}, "is_simulated": False}
    return {"success": True, "message": _msg(locale, "ok"), "data": res["match"], "is_simulated": False}


@router.get("/search", summary="Search JPL SBDB (returns a list)")
async def search(query: str = Query(..., min_length=1, max_length=200), locale: str = "en") -> dict[str, Any]:
    try:
        res = await jc.sbdb_lookup(query)
    except jc.NotFound:
        return {"success": True, "data": [], "is_simulated": False}
    except Exception as exc:
        raise _handle(exc, locale, query)
    items = res["matches"] if "matches" in res else [{"designation": res["match"]["designation"], "name": res["match"]["name"]}]
    return {"success": True, "data": items, "is_simulated": False}


@router.get("/ephemeris", summary="Geocentric ephemeris from JPL Horizons")
async def get_ephemeris(
    target: str = Query(..., min_length=1, max_length=200),
    start: Optional[str] = Query(None, description="YYYY-MM-DD (default: now)"),
    days: int = Query(7, ge=1, le=366),
    step: str = Query("1d", pattern=r"^\d{1,3}[mhd]$"),
    locale: str = "en",
) -> dict[str, Any]:
    if start:
        try:
            jc.datetime.strptime(start, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail=_msg(locale, "bad_time"))
    try:
        res = await jc.ephemeris(target, start=start, days=days, step=step)
    except Exception as exc:
        raise _handle(exc, locale, target)
    if "matches" in res:
        return {"success": True, "message": _msg(locale, "matches"), "data": res, "is_simulated": False}
    return {"success": True, "message": _msg(locale, "ok"), "data": res, "is_simulated": False}


@router.get("/nearby", summary="Known asteroids/comets in a sky field (JPL SB Ident)")
async def nearby(
    ra: float = Query(..., ge=0.0, lt=360.0),
    dec: float = Query(..., ge=-90.0, le=90.0),
    radius_arcsec: Optional[float] = Query(None, gt=0, le=7200),
    radius: Optional[float] = Query(None, gt=0, le=2.0, description="Radius in degrees (alternative)"),
    time: Optional[str] = Query(None, description="UTC, e.g. 2025-06-24T11:00 (default: now)"),
    vmag_lim: float = Query(21.0, ge=8, le=25),
    locale: str = "en",
) -> dict[str, Any]:
    r_deg = (radius_arcsec / 3600.0) if radius_arcsec else (radius or 0.25)
    if time:
        try:
            jc.datetime.fromisoformat(time)
        except ValueError:
            raise HTTPException(status_code=400, detail=_msg(locale, "bad_time"))
    try:
        res = await jc.known_in_field(ra, dec, r_deg, time, vmag_lim)
    except Exception as exc:
        raise _handle(exc, locale)
    return {"success": True, "message": _msg(locale, "ok"), "data": res, "is_simulated": False}
