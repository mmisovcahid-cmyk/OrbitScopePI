"""OrbitScope Ground Node API - the Raspberry Pi as an observing station (see services/ground_node.py)."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.services import ground_node as gn

router = APIRouter(prefix="/api/v1/ground", tags=["Ground Node"])

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "not_found": "This session does not exist.",
        "no_images": "No usable images: upload JPEG, PNG, TIFF or FITS frames.",
        "too_many": "Too many frames: at most {n} per session.",
        "too_few_frames": "At least 3 frames of the same field are needed to find moving objects.",
        "mixed_sizes": "All frames must have the same size and orientation.",
        "no_camera": "No Raspberry Pi camera on this machine.",
        "camera_failed": "The camera did not deliver a frame: {detail}",
        "ok": "OK",
    },
    "az": {
        "not_found": "Belə sessiya yoxdur.",
        "no_images": "Yararlı şəkil yoxdur: JPEG, PNG, TIFF və ya FITS kadrları yükləyin.",
        "too_many": "Kadr çoxdur: bir sessiyada ən çox {n}.",
        "too_few_frames": "Hərəkət edən obyektləri tapmaq üçün eyni sahənin ən azı 3 kadrı lazımdır.",
        "mixed_sizes": "Bütün kadrlar eyni ölçüdə və istiqamətdə olmalıdır.",
        "no_camera": "Bu cihazda Raspberry Pi kamerası yoxdur.",
        "camera_failed": "Kamera kadr vermədi: {detail}",
        "ok": "OK",
    },
}


def _err(exc: gn.GroundNodeError, locale: str) -> HTTPException:
    msgs = MESSAGES.get(locale, MESSAGES["en"])
    text = msgs.get(exc.code, exc.detail).format(n=gn.MAX_FRAMES, detail=exc.detail)
    status = 404 if exc.code == "not_found" else 503 if exc.code in ("no_camera", "camera_failed") else 400
    return HTTPException(status_code=status, detail=text)


def _ok(data: Any, locale: str) -> dict[str, Any]:
    return {"success": True, "data": data, "message": MESSAGES.get(locale, MESSAGES["en"])["ok"], "is_simulated": False}


@router.get("/status", summary="Station inputs: Pi camera, upload, plate solver")
async def station_status(locale: str = "en") -> dict[str, Any]:
    return _ok(await asyncio.to_thread(gn.status), locale)


@router.get("/sessions", summary="Observing sessions on this station")
async def sessions(locale: str = "en") -> dict[str, Any]:
    return _ok(await asyncio.to_thread(gn.list_sessions), locale)


@router.post("/sessions", summary="Upload an image sequence (same field, tripod, 5-30 s exposures)")
async def upload(files: list[UploadFile] = File(...), label: str = Form(""), locale: str = Form("en")) -> dict[str, Any]:
    blobs = [(f.filename or "frame", await f.read()) for f in files]
    try:
        return _ok(await asyncio.to_thread(gn.create_upload_session, blobs, label), locale)
    except gn.GroundNodeError as exc:
        raise _err(exc, locale)


class CaptureRequest(BaseModel):
    frames: int = Field(5, ge=3, le=60)
    exposure_s: float = Field(2.0, ge=0.001, le=60.0)
    gain: float = Field(8.0, ge=1.0, le=16.0)
    locale: str = "en"


@router.post("/capture", summary="Take a frame sequence with the Pi camera")
async def capture(req: CaptureRequest) -> dict[str, Any]:
    try:
        sid = await asyncio.to_thread(gn.capture_frames, req.frames, req.exposure_s, req.gain)
        return _ok(await asyncio.to_thread(gn.get_session, sid), req.locale)
    except gn.GroundNodeError as exc:
        raise _err(exc, req.locale)


@router.post("/sessions/{sid}/analyze", summary="Find trails, plate-solve, link to SPHEREx")
async def analyze(sid: str, locale: str = Query("en")) -> dict[str, Any]:
    try:
        return _ok(await asyncio.to_thread(gn.analyze, sid), locale)
    except gn.GroundNodeError as exc:
        raise _err(exc, locale)


@router.get("/sessions/{sid}", summary="One session with its frames and analysis")
async def session(sid: str, locale: str = "en") -> dict[str, Any]:
    try:
        return _ok(await asyncio.to_thread(gn.get_session, sid), locale)
    except gn.GroundNodeError as exc:
        raise _err(exc, locale)


@router.get("/sessions/{sid}/frames/{index}.jpg", summary="Stretched preview of one frame")
async def frame(sid: str, index: int, locale: str = "en") -> Response:
    try:
        blob = await asyncio.to_thread(gn.frame_preview, sid, index)
    except gn.GroundNodeError as exc:
        raise _err(exc, locale)
    return Response(blob, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})
