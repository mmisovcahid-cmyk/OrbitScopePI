"""
OrbitScope API - Real SPHEREx blink endpoints
=============================================
/api/v1/spherex/targets     challenge test targets
/api/v1/spherex/resolve     name / coordinate resolver
/api/v1/spherex/coverage    which SPHEREx frames cover a position
/api/v1/spherex/blink       co-registered time series of real SPHEREx images (JSON, float32 frames)
/api/v1/spherex/blink.gif   the same series as an animated GIF (for sharing / embedding)
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import io
import time
from typing import Any, Optional

import httpx

import numpy as np
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from PIL import Image, ImageDraw

from app.core.config import settings
from app.core.logging_config import get_logger
from pydantic import BaseModel, Field

from app.services.candidate_store import get_store
from app.services.catalog_overlay import CatalogError, fetch_catalog
from app.services.detection_service import run_detection
from app.services.spherex_archive import DETECTOR_BANDS, SpherexError, spherex_archive
from app.services.target_resolver import BUILTIN_TARGETS, resolve

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/spherex", tags=["SPHEREx (real data)"])

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "ok": "SPHEREx frames loaded",
        "not_resolved": "Could not resolve '{q}'. Enter an object name or coordinates (e.g. 08h55m10.8s -07d14m42s).",
        "no_coverage": "SPHEREx has not observed this position in the public releases yet.",
        "no_detector_coverage": "No SPHEREx frames for the selected detector at this position. Try another detector.",
        "no_band_coverage": "No SPHEREx exposure sees this position inside the selected wavelength band yet. Choose a wider band.",
        "no_data": "SPHEREx frames were found, but none had valid pixels at this position.",
        "upstream": "The IRSA archive did not respond correctly. Please try again in a moment.",
        "bad_detector": "Detector must be 1-6 or 'all'.",
        "catalog_down": "The reference catalog service is not responding. Try again later.",
        "candidate_not_found": "Candidate not found.",
        "review_forbidden": "Reviewing candidates on this server needs the team's review token.",
        "bad_pass": "That survey pass does not exist for this position.",
    },
    "az": {
        "ok": "SPHEREx kadrları yükləndi",
        "not_resolved": "'{q}' tapılmadı. Obyekt adı və ya koordinat daxil edin (məs. 08h55m10.8s -07d14m42s).",
        "no_coverage": "SPHEREx bu mövqeni ictimai buraxılışlarda hələ müşahidə etməyib.",
        "no_detector_coverage": "Seçilmiş detektor üçün bu mövqedə SPHEREx kadrı yoxdur. Başqa detektor seçin.",
        "no_band_coverage": "Bu mövqeni seçilmiş dalğa uzunluğu zolağında görən SPHEREx ekspozisiyası hələ yoxdur. Daha geniş zolaq seçin.",
        "no_data": "SPHEREx kadrları tapıldı, lakin bu mövqedə etibarlı piksel yoxdur.",
        "upstream": "IRSA arxivi düzgün cavab vermədi. Bir az sonra yenidən cəhd edin.",
        "bad_detector": "Detektor 1-6 və ya 'all' olmalıdır.",
        "catalog_down": "İstinad kataloq servisi cavab vermir. Bir az sonra yenidən cəhd edin.",
        "candidate_not_found": "Namizəd tapılmadı.",
        "review_forbidden": "Bu serverdə namizədləri qiymətləndirmək üçün komandanın review tokeni lazımdır.",
        "bad_pass": "Bu mövqe üçün belə müşahidə keçidi yoxdur.",
    },
}


def _msg(locale: str, key: str, **kw: Any) -> str:
    table = MESSAGES.get((locale or "en").lower(), MESSAGES["en"])
    return table.get(key, MESSAGES["en"][key]).format(**kw)


def _parse_detectors(detector: str, locale: str) -> Optional[list[int]]:
    d = (detector or "all").strip().lower()
    if d in ("all", "", "0"):
        return None
    try:
        dets = sorted({int(x) for x in d.split(",") if x.strip()})
    except ValueError:
        raise HTTPException(status_code=400, detail=_msg(locale, "bad_detector"))
    if not dets or any(x < 1 or x > 6 for x in dets):
        raise HTTPException(status_code=400, detail=_msg(locale, "bad_detector"))
    return dets


async def _target_from_query(
    target: Optional[str], ra: Optional[float], dec: Optional[float],
    pmra: Optional[float], pmdec: Optional[float], ref_epoch: Optional[float], locale: str,
) -> dict[str, Any]:
    if ra is not None and dec is not None:
        return {"name": target or None, "ra": ra, "dec": dec, "pmra": pmra, "pmdec": pmdec,
                "ref_epoch": ref_epoch or 2000.0, "source": "coordinates"}
    if not target:
        raise HTTPException(status_code=400, detail=_msg(locale, "not_resolved", q=""))
    res = await resolve(target)
    if not res:
        raise HTTPException(status_code=404, detail=_msg(locale, "not_resolved", q=target))
    return res


def _raise_archive(exc: SpherexError, locale: str) -> None:
    status = 404 if exc.code in ("no_coverage", "no_detector_coverage", "no_band_coverage", "no_data") else 400 if exc.code == "bad_pass" else 502
    raise HTTPException(status_code=status, detail=_msg(locale, exc.code if exc.code in MESSAGES["en"] else "upstream"))


_status_cache: dict[str, Any] = {}


async def _irsa_reachable() -> dict[str, Any]:
    """Cheap TAP round-trip (cached 5 min) to tell users whether IRSA is up."""
    now = time.time()
    if _status_cache.get("t", 0) > now - 300:
        return _status_cache["irsa"]
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(spherex_archive.tap_url, data={
                "LANG": "ADQL", "FORMAT": "csv",
                "QUERY": "SELECT table_name FROM TAP_SCHEMA.tables WHERE table_name = 'spherex.obscore'"})
        ok = r.status_code == 200 and "spherex.obscore" in r.text
        info = {"reachable": ok, "latency_ms": round((time.perf_counter() - t0) * 1000), "http": r.status_code}
    except httpx.HTTPError as exc:
        info = {"reachable": False, "error": type(exc).__name__}
    _status_cache.update({"t": now, "irsa": info})
    return info


@router.get("/status", summary="Real-data service health: IRSA, cache, candidates, jobs")
async def status() -> dict[str, Any]:
    from app.services.jobs import job_manager

    irsa = await _irsa_reachable()
    try:
        counts = get_store().counts()
    except Exception:
        counts = {}
    return {"success": True, "data": {
        "irsa": irsa,
        "cache": await asyncio.to_thread(spherex_archive.cache_stats),
        "candidates": counts,
        "jobs": job_manager.stats(),
        "data_source": "NASA/IPAC IRSA - SPHEREx (collections matched by prefix 'spherex', new releases picked up automatically)",
    }}


@router.get("/targets", summary="Challenge test targets")
async def list_targets() -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "targets": [{k: t[k] for k in ("id", "name", "ra", "dec", "pmra", "pmdec", "ref_epoch", "kind", "note", "detector")} for t in BUILTIN_TARGETS],
            "detectors": [{"id": d, "wavelength_um": list(b)} for d, b in DETECTOR_BANDS.items()],
        },
    }


@router.get("/resolve", summary="Resolve object name or coordinates")
async def resolve_target(q: str = Query(..., min_length=1, max_length=200), locale: str = "en") -> dict[str, Any]:
    res = await resolve(q)
    if not res:
        raise HTTPException(status_code=404, detail=_msg(locale, "not_resolved", q=q))
    return {"success": True, "data": res}


@router.get("/coverage", summary="SPHEREx frames covering a position")
async def coverage(
    ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90), locale: str = "en"
) -> dict[str, Any]:
    try:
        frames = await spherex_archive.query_frames(ra, dec)
    except SpherexError as exc:
        _raise_archive(exc, locale)
    return {"success": True, "data": spherex_archive.summarize(frames)}


async def _build(
    target, ra, dec, pmra, pmdec, ref_epoch, fov, detector, mode, per_epoch, max_frames, locale, pass_index=None,
    wl_min=None, wl_max=None,
) -> dict[str, Any]:
    tgt = await _target_from_query(target, ra, dec, pmra, pmdec, ref_epoch, locale)
    dets = _parse_detectors(detector, locale)
    try:
        result = await spherex_archive.build_blink(
            ra=tgt["ra"], dec=tgt["dec"], fov_deg=fov, detectors=dets, mode=mode,
            per_epoch=per_epoch, max_frames=max_frames, pass_index=pass_index,
            pmra=tgt.get("pmra"), pmdec=tgt.get("pmdec"), ref_epoch=tgt.get("ref_epoch") or 2000.0,
            wl_min=wl_min, wl_max=wl_max,
        )
    except SpherexError as exc:
        _raise_archive(exc, locale)
    result["target"].update({"name": tgt.get("name"), "resolver": tgt.get("source"), "note": tgt.get("note")})
    return result


@router.get("/blink", summary="Co-registered SPHEREx image time series around a position")
async def blink(
    target: Optional[str] = Query(None, max_length=200, description="Object name or coordinate string"),
    ra: Optional[float] = Query(None, ge=0, lt=360),
    dec: Optional[float] = Query(None, ge=-90, le=90),
    pmra: Optional[float] = Query(None, description="Proper motion in RA*cos(dec), mas/yr"),
    pmdec: Optional[float] = Query(None, description="Proper motion in Dec, mas/yr"),
    ref_epoch: Optional[float] = Query(None, description="Epoch of ra/dec (Julian year)"),
    fov: float = Query(0.1, ge=0.02, le=0.5, description="Field of view (deg)"),
    detector: str = Query("3", description="1-6, comma list, or 'all'"),
    mode: str = Query("epoch", pattern="^(epoch|frames|pass)$"),
    pass_index: Optional[int] = Query(None, ge=0, le=50),
    per_epoch: int = Query(4, ge=1, le=12),
    max_frames: int = Query(16, ge=2, le=48),
    wl_min: Optional[float] = Query(None, ge=0.7, le=5.1, description="Band lower edge (um), applied per exposure"),
    wl_max: Optional[float] = Query(None, ge=0.7, le=5.1, description="Band upper edge (um)"),
    locale: str = "en",
) -> dict[str, Any]:
    data = await _build(target, ra, dec, pmra, pmdec, ref_epoch, fov, detector, mode, per_epoch, max_frames, locale, pass_index,
                        wl_min, wl_max)
    return {"success": True, "message": _msg(locale, "ok"), "data": data}


@router.get("/photometry", summary="Spectrum + light curve of one position from many SPHEREx exposures")
async def photometry(
    target: Optional[str] = Query(None, max_length=200),
    ra: Optional[float] = Query(None, ge=0, lt=360),
    dec: Optional[float] = Query(None, ge=-90, le=90),
    pmra: Optional[float] = None,
    pmdec: Optional[float] = None,
    ref_epoch: Optional[float] = None,
    detector: str = Query("all", description="1-6, comma list, or 'all'"),
    max_frames: int = Query(60, ge=6, le=96),
    aperture_px: float = Query(2.0, ge=1.0, le=4.0),
    locale: str = "en",
) -> dict[str, Any]:
    tgt = await _target_from_query(target, ra, dec, pmra, pmdec, ref_epoch, locale)
    dets = _parse_detectors(detector, locale)
    try:
        data = await spherex_archive.photometry(
            ra=tgt["ra"], dec=tgt["dec"], detectors=dets, max_frames=max_frames,
            pmra=tgt.get("pmra"), pmdec=tgt.get("pmdec"), ref_epoch=tgt.get("ref_epoch") or 2000.0,
            aperture_px=aperture_px,
        )
    except SpherexError as exc:
        _raise_archive(exc, locale)
    data["position"]["name"] = tgt.get("name")
    return {"success": True, "data": data}


@router.get("/overlay", summary="Reference catalog sources (Gaia DR3 / CatWISE2020) around a position")
async def overlay(
    ra: float = Query(..., ge=0, lt=360),
    dec: float = Query(..., ge=-90, le=90),
    fov: float = Query(0.1, ge=0.02, le=0.5),
    catalog: str = Query("gaia", pattern="^(gaia|catwise)$"),
    limit: int = Query(1500, ge=10, le=5000),
    locale: str = "en",
) -> dict[str, Any]:
    try:
        data = await fetch_catalog(catalog, ra, dec, radius_deg=fov * 0.75, limit=limit)
    except CatalogError as exc:
        logger.warning(f"overlay {catalog} failed: {exc}")
        raise HTTPException(status_code=502, detail=_msg(locale, "catalog_down"))
    return {"success": True, "data": data}


@router.get("/detect", summary="Search real SPHEREx frames for moving objects (asteroids or proper motion)")
async def detect(
    target: Optional[str] = Query(None, max_length=200),
    ra: Optional[float] = Query(None, ge=0, lt=360),
    dec: Optional[float] = Query(None, ge=-90, le=90),
    pmra: Optional[float] = None,
    pmdec: Optional[float] = None,
    ref_epoch: Optional[float] = None,
    search: str = Query("asteroids", pattern="^(asteroids|proper_motion)$"),
    fov: float = Query(0.2, ge=0.05, le=0.5),
    detector: str = Query("1,4", description="1-6, comma list, or 'all'"),
    pass_index: Optional[int] = Query(None, ge=0, le=50, description="Survey pass for asteroid searches (default: richest)"),
    max_frames: int = Query(36, ge=6, le=48),
    z_thresh: float = Query(5.0, ge=3.0, le=20.0),
    vmag_lim: float = Query(21.0, ge=10.0, le=25.0),
    locale: str = "en",
) -> dict[str, Any]:
    tgt = await _target_from_query(target, ra, dec, pmra, pmdec, ref_epoch, locale)
    dets = _parse_detectors(detector, locale)
    try:
        data = await run_detection(tgt, search=search, fov_deg=fov, detectors=dets, pass_index=pass_index,
                                   max_frames=max_frames, z_thresh=z_thresh, vmag_lim=vmag_lim)
    except SpherexError as exc:
        _raise_archive(exc, locale)
    return {"success": True, "data": data}


@router.get("/candidates", summary="Saved candidates (with review status)")
async def list_candidates(
    status: Optional[str] = Query(None, pattern="^(unreviewed|real|artifact|unsure)$"),
    klass: Optional[str] = Query(None, alias="class", max_length=40),
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    store = get_store()
    return {"success": True, "data": {"candidates": store.list(status, klass, limit), "counts": store.counts()}}


@router.get("/candidates/{cand_id}", summary="One saved candidate with the parameters of its search run")
async def get_candidate(cand_id: str, locale: str = "en") -> dict[str, Any]:
    store = get_store()
    c = store.get(cand_id)
    if not c:
        raise HTTPException(status_code=404, detail=_msg(locale, "candidate_not_found"))
    return {"success": True, "data": {**c, "run": store.get_run(c["run_id"])}}


@router.get("/overview", summary="Real-data overview for the dashboard")
async def overview() -> dict[str, Any]:
    from app.services.jobs import job_manager

    store = get_store()
    irsa = await _irsa_reachable()
    return {"success": True, "data": {
        "irsa": irsa,
        "cache": await asyncio.to_thread(spherex_archive.cache_stats),
        "review_counts": store.counts(),
        "class_counts": store.class_counts(),
        "recent_runs": store.recent_runs(8),
        "recent_candidates": store.list(limit=200),
        "targets": [{k: t[k] for k in ("id", "name", "ra", "dec", "kind", "note", "detector")} for t in BUILTIN_TARGETS],
        "jobs": job_manager.stats(),
        "is_simulated": False,
    }}


class ReviewBody(BaseModel):
    status: str = Field(..., pattern="^(unreviewed|real|artifact|unsure)$")
    note: Optional[str] = Field(None, max_length=2000)


@router.patch("/candidates/{cand_id}", summary="Review a candidate (real / artifact / unsure)")
async def review_candidate(
    cand_id: str, body: ReviewBody, locale: str = "en",
    x_review_token: Optional[str] = Header(None),
) -> dict[str, Any]:
    # On a public server anyone could otherwise mark candidates real/artifact.
    if settings.REVIEW_TOKEN and not hmac.compare_digest(x_review_token or "", settings.REVIEW_TOKEN):
        raise HTTPException(status_code=403, detail=_msg(locale, "review_forbidden"))
    updated = get_store().review(cand_id, body.status, body.note)
    if not updated:
        raise HTTPException(status_code=404, detail=_msg(locale, "candidate_not_found"))
    return {"success": True, "data": updated}


@router.get("/candidates/{cand_id}/export", summary="Export candidate astrometry (CSV)")
async def export_candidate(cand_id: str, locale: str = "en") -> Response:
    c = get_store().get(cand_id)
    if not c:
        raise HTTPException(status_code=404, detail=_msg(locale, "candidate_not_found"))
    lines = ["candidate,class,date_utc,mjd,ra_deg,dec_deg,detector,snr"]
    for d in c["detections"]:
        lines.append(f"{c['id']},{c['class']},{d['date']},{d['mjd']:.6f},{d['ra']:.6f},{d['dec']:.6f},"
                     f"{'/'.join(map(str, d['detectors']))},{d['z']}")
    return Response("\n".join(lines) + "\n", media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{cand_id}.csv"'})


def _render_png_frames(data: dict[str, Any], scale: int = 4) -> list[Image.Image]:
    w, h = data["grid"]["width"], data["grid"]["height"]
    vmin, vmax = data["stretch_hint"]["vmin"], data["stretch_hint"]["vmax"]
    span = max(vmax - vmin, 1e-9)
    images = []
    for f in data["frames"]:
        arr = np.frombuffer(base64.b64decode(f["data"]), dtype="<f4").reshape(h, w)
        x = np.clip((np.nan_to_num(arr, nan=vmin) - vmin) / span, 0, 1)
        y = np.arcsinh(10 * x) / np.arcsinh(10)
        img = Image.fromarray((np.flipud(y) * 255).astype(np.uint8), mode="L").resize((w * scale, h * scale), Image.NEAREST)
        img = img.convert("RGB")
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, w * scale, 14], fill=(0, 0, 0))
        draw.text((4, 2), f"SPHEREx {f['date'][:10]}  D{','.join(map(str, f['detectors']))}", fill=(255, 255, 255))
        if f.get("target_px"):
            tx, ty = f["target_px"]
            cx, cy = (tx + 0.5) * scale, (h - ty - 0.5) * scale
            r = 6 * scale
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(56, 189, 248))
        images.append(img)
    return images


@router.get("/blink.gif", summary="Animated GIF of the SPHEREx time series (embeddable)")
async def blink_gif(
    target: Optional[str] = Query(None, max_length=200),
    ra: Optional[float] = Query(None, ge=0, lt=360),
    dec: Optional[float] = Query(None, ge=-90, le=90),
    pmra: Optional[float] = None,
    pmdec: Optional[float] = None,
    ref_epoch: Optional[float] = None,
    fov: float = Query(0.1, ge=0.02, le=0.5),
    detector: str = "3",
    mode: str = Query("epoch", pattern="^(epoch|frames|pass)$"),
    pass_index: Optional[int] = Query(None, ge=0, le=50),
    per_epoch: int = Query(4, ge=1, le=12),
    max_frames: int = Query(16, ge=2, le=48),
    wl_min: Optional[float] = Query(None, ge=0.7, le=5.1, description="Band lower edge (um), applied per exposure"),
    wl_max: Optional[float] = Query(None, ge=0.7, le=5.1, description="Band upper edge (um)"),
    delay_ms: int = Query(600, ge=50, le=5000),
    locale: str = "en",
) -> Response:
    data = await _build(target, ra, dec, pmra, pmdec, ref_epoch, fov, detector, mode, per_epoch, max_frames, locale, pass_index,
                        wl_min, wl_max)
    frames = _render_png_frames(data)
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=delay_ms, loop=0)
    return Response(content=buf.getvalue(), media_type="image/gif", headers={"Cache-Control": "public, max-age=3600"})
