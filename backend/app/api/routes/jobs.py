"""
OrbitScope API - background jobs
================================
POST   /api/v1/jobs              {"kind": "blink"|"detect"|"photometry", "params": {...}, "locale": "en"}
GET    /api/v1/jobs/{id}         status, stage, done/total, and the result once finished
DELETE /api/v1/jobs/{id}         cancel

The params are validated with the same limits as the direct endpoints
(/api/v1/spherex/blink, /detect, /photometry), and the result payload is identical to their
``data`` field. The direct endpoints stay available for scripts, embeds and GIF export.
"""
from __future__ import annotations

import json
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.core.validation_i18n import localize_errors

from app.api.routes import spherex as sx
from app.services.detection_service import run_detection
from app.services.jobs import job_manager
from app.services.spherex_archive import SpherexError, spherex_archive

router = APIRouter(prefix="/api/v1/jobs", tags=["Background jobs"])


class TargetParams(BaseModel):
    target: Optional[str] = Field(None, max_length=200)
    ra: Optional[float] = Field(None, ge=0, lt=360)
    dec: Optional[float] = Field(None, ge=-90, le=90)
    pmra: Optional[float] = None
    pmdec: Optional[float] = None
    ref_epoch: Optional[float] = None


class BlinkParams(TargetParams):
    fov: float = Field(0.1, ge=0.02, le=0.5)
    detector: str = "3"
    mode: Literal["epoch", "frames", "pass"] = "epoch"
    per_epoch: int = Field(4, ge=1, le=12)
    max_frames: int = Field(16, ge=2, le=48)
    pass_index: Optional[int] = Field(None, ge=0, le=50)
    wl_min: Optional[float] = Field(None, ge=0.7, le=5.1)
    wl_max: Optional[float] = Field(None, ge=0.7, le=5.1)


class DetectParams(TargetParams):
    search: Literal["asteroids", "proper_motion"] = "asteroids"
    fov: float = Field(0.2, ge=0.05, le=0.5)
    detector: str = "1,4"
    pass_index: Optional[int] = Field(None, ge=0, le=50)
    max_frames: int = Field(36, ge=6, le=48)
    z_thresh: float = Field(5.0, ge=3.0, le=20.0)
    vmag_lim: float = Field(21.0, ge=10.0, le=25.0)


class PhotometryParams(TargetParams):
    detector: str = "all"
    max_frames: int = Field(60, ge=6, le=96)
    aperture_px: float = Field(2.0, ge=1.0, le=4.0)


PARAM_MODELS = {"blink": BlinkParams, "detect": DetectParams, "photometry": PhotometryParams}


class JobRequest(BaseModel):
    kind: Literal["blink", "detect", "photometry"]
    params: dict[str, Any] = Field(default_factory=dict)
    locale: str = "en"


def _error_mapper(locale: str):
    def map_error(exc: BaseException) -> dict[str, Any]:
        if isinstance(exc, HTTPException):
            return {"status": exc.status_code, "detail": exc.detail}
        if isinstance(exc, SpherexError):
            code = exc.code if exc.code in sx.MESSAGES["en"] else "upstream"
            status = 404 if code in ("no_coverage", "no_detector_coverage", "no_data") else 400 if code == "bad_pass" else 502
            return {"status": status, "detail": sx._msg(locale, code), "code": code}
        return {"status": 500, "detail": f"Internal server error: {type(exc).__name__}"}

    return map_error


@router.post("", summary="Start a background job (blink / detect / photometry)")
async def create_job(req: JobRequest) -> dict[str, Any]:
    model = PARAM_MODELS[req.kind]
    try:
        p = model(**req.params)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=localize_errors(exc.errors(include_url=False), req.locale or "en"))
    locale = req.locale or "en"
    key = f"{req.kind}:{locale}:{json.dumps(p.model_dump(), sort_keys=True)}"

    async def factory() -> Any:
        if isinstance(p, BlinkParams):
            data = await sx._build(p.target, p.ra, p.dec, p.pmra, p.pmdec, p.ref_epoch, p.fov, p.detector, p.mode,
                                   p.per_epoch, p.max_frames, locale, p.pass_index, p.wl_min, p.wl_max)
            return data
        tgt = await sx._target_from_query(p.target, p.ra, p.dec, p.pmra, p.pmdec, p.ref_epoch, locale)
        dets = sx._parse_detectors(p.detector, locale)
        if isinstance(p, DetectParams):
            return await run_detection(tgt, search=p.search, fov_deg=p.fov, detectors=dets, pass_index=p.pass_index,
                                       max_frames=p.max_frames, z_thresh=p.z_thresh, vmag_lim=p.vmag_lim)
        data = await spherex_archive.photometry(
            ra=tgt["ra"], dec=tgt["dec"], detectors=dets, max_frames=p.max_frames,
            pmra=tgt.get("pmra"), pmdec=tgt.get("pmdec"), ref_epoch=tgt.get("ref_epoch") or 2000.0,
            aperture_px=p.aperture_px,
        )
        data["position"]["name"] = tgt.get("name")
        return data

    job = job_manager.submit(req.kind, key, factory, _error_mapper(locale))
    return {"success": True, "data": job.public(include_result=False)}


@router.get("/{job_id}", summary="Job status, progress and result")
async def get_job(job_id: str, include_result: bool = True) -> dict[str, Any]:
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return {"success": True, "data": job.public(include_result=include_result)}


@router.delete("/{job_id}", summary="Cancel a running job")
async def cancel_job(job_id: str) -> dict[str, Any]:
    job = job_manager.cancel(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return {"success": True, "data": job.public(include_result=False)}
