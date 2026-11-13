"""
OrbitScope Ground Node - a sensor-agnostic observing station on the Raspberry Pi
================================================================================
Frames arrive from any source and go through one analysis chain:

    source (Pi camera | uploaded image sequence | telescope, later via INDI)
      -> frame + time + place  (EXIF / FITS header)
      -> trail detection       (satellites and planes leave lines in 5-30 s exposures)
      -> plate solving         (astrometry.net, offline, when installed)
      -> link to the same sky direction in SPHEREx

Honesty rules (project invariant): every session records where its frames came from (the EXIF
camera model of an uploaded phone image is shown as such, never as the Pi camera); detections are
"trails", not discoveries; what cannot be done (no timestamp, no solver, no camera) is said.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

MAX_FRAMES = 120
ANALYSIS_MAX_PX = 1600          # frames are analysed at <= this size (speed on the Pi)
PREVIEW_MAX_PX = 1280
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".fits", ".fit", ".fts"}

# EXIF tags
_DATETIME_ORIGINAL, _OFFSET_ORIGINAL, _MAKE, _MODEL, _EXPOSURE, _ISO = 36867, 36881, 271, 272, 33434, 34855
_EXIF_IFD, _GPS_IFD = 0x8769, 0x8825


class GroundNodeError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def root_dir() -> Path:
    return Path(settings.SPHEREX_CACHE_DIR).parent / "ground"


def _session_dir(sid: str) -> Path:
    if not sid or not all(c.isalnum() or c == "-" for c in sid):
        raise GroundNodeError("not_found", "unknown session")
    return root_dir() / sid


# ------------------------------------------------------------------ metadata
def _ratio(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _gps_deg(vals: Any, ref: Any) -> Optional[float]:
    try:
        d, m, s = (float(x) for x in vals)
    except (TypeError, ValueError):
        return None
    deg = d + m / 60.0 + s / 3600.0
    return -deg if str(ref).upper() in ("S", "W") else deg


def read_metadata(path: Path) -> dict[str, Any]:
    """Time (UTC when the offset is known), place, camera and exposure of one frame."""
    meta: dict[str, Any] = {"time_utc": None, "time_local": None, "time_note": None, "lat": None, "lon": None,
                            "camera": None, "exposure_s": None, "iso": None}
    if path.suffix.lower() in (".fits", ".fit", ".fts"):
        from astropy.io import fits

        with fits.open(path) as hdul:
            h = hdul[0].header
            meta["camera"] = " ".join(str(h.get(k, "")) for k in ("TELESCOP", "INSTRUME")).strip() or None
            meta["exposure_s"] = _ratio(h.get("EXPTIME") or h.get("EXPOSURE"))
            if h.get("DATE-OBS"):
                meta["time_utc"] = str(h["DATE-OBS"]).replace(" ", "T").rstrip("Z") + "Z"
            meta["lat"], meta["lon"] = _ratio(h.get("SITELAT")), _ratio(h.get("SITELONG"))
        return meta

    with Image.open(path) as im:
        exif = im.getexif()
    sub = exif.get_ifd(_EXIF_IFD) if exif else {}
    gps = exif.get_ifd(_GPS_IFD) if exif else {}
    make, model = exif.get(_MAKE), exif.get(_MODEL)
    meta["camera"] = " ".join(str(x).strip() for x in (make, model) if x) or None
    meta["exposure_s"] = _ratio(sub.get(_EXPOSURE))
    meta["iso"] = sub.get(_ISO)
    raw = sub.get(_DATETIME_ORIGINAL) or exif.get(306)  # DateTimeOriginal, else DateTime
    if raw:
        try:
            local = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
            meta["time_local"] = local.isoformat()
            off = sub.get(_OFFSET_ORIGINAL)
            if off and len(str(off)) >= 6:
                sign = -1 if str(off)[0] == "-" else 1
                hh, mm = int(str(off)[1:3]), int(str(off)[4:6])
                utc = local - sign * timedelta(hours=hh, minutes=mm)
                meta["time_utc"] = utc.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                meta["time_note"] = "no_timezone"
        except ValueError:
            meta["time_note"] = "unreadable_time"
    else:
        meta["time_note"] = "no_time"
    if gps:
        meta["lat"] = _gps_deg(gps.get(2), gps.get(1))
        meta["lon"] = _gps_deg(gps.get(4), gps.get(3))
    return meta


# -------------------------------------------------------------------- images
def load_gray(path: Path, max_px: int = ANALYSIS_MAX_PX) -> np.ndarray:
    """Frame as float32 luminance, downscaled so the longer side is <= max_px."""
    if path.suffix.lower() in (".fits", ".fit", ".fts"):
        from astropy.io import fits

        data = np.asarray(fits.getdata(path), dtype=np.float32)
        while data.ndim > 2:
            data = data[0] if data.shape[0] <= 4 else data.mean(axis=0)
        step = max(1, int(math.ceil(max(data.shape) / max_px)))
        return np.nan_to_num(data[::step, ::step])
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("L")
        im.thumbnail((max_px, max_px))
        return np.asarray(im, dtype=np.float32)


def detect_trails(frames: list[np.ndarray], k_sigma: float = 5.0, min_len_px: float = 40.0,
                  min_elongation: float = 6.0) -> list[dict[str, Any]]:
    """Straight trails that appear in one frame but not in its neighbours.

    Background of frame i = median of up to two frames on each side, grey-dilated by a few
    pixels, so stars that drift slightly between exposures (fixed tripod, rotating sky) do not
    leave residuals. What remains above k_sigma is labelled; long, thin components are trails.
    Planes usually leave several collinear dashes (blinking lights); they are reported as
    separate trails and flagged `dashed` when collinear pieces exist in the same frame.
    """
    n = len(frames)
    if n < 3:
        raise GroundNodeError("too_few_frames", "at least 3 frames of the same field are needed")
    shape = frames[0].shape
    if any(f.shape != shape for f in frames):
        raise GroundNodeError("mixed_sizes", "all frames must have the same size and orientation")
    trails: list[dict[str, Any]] = []
    for i, frame in enumerate(frames):
        nb = [frames[j] for j in range(max(0, i - 2), min(n, i + 3)) if j != i]
        bg = ndimage.grey_dilation(np.median(np.stack(nb), axis=0), size=(5, 5))
        resid = frame - bg
        mad = float(np.median(np.abs(resid - np.median(resid)))) * 1.4826 or 1.0
        # Bridge 1-px gaps (thin diagonal trails, JPEG blocks) instead of eroding: an opening
        # would break a faint 1-2 px trail into dashes.
        mask = ndimage.binary_closing(resid > k_sigma * mad, structure=np.ones((3, 3)))
        labels, count = ndimage.label(mask, structure=np.ones((3, 3)))
        found: list[dict[str, Any]] = []
        for sl, lab in zip(ndimage.find_objects(labels), range(1, count + 1)):
            if sl is None:
                continue
            ys, xs = np.nonzero(labels[sl] == lab)
            if len(xs) < min_len_px:
                continue
            xs = xs + sl[1].start
            ys = ys + sl[0].start
            pts = np.stack([xs, ys], axis=1).astype(np.float64)
            c = pts.mean(axis=0)
            evals, evecs = np.linalg.eigh(np.cov((pts - c).T))
            major = evecs[:, 1]
            proj = (pts - c) @ major
            length = float(proj.max() - proj.min())
            width = float(math.sqrt(max(evals[0], 1e-6)) * 4.0)
            if length < min_len_px or length / max(width, 1.0) < min_elongation:
                continue
            p0, p1 = c + major * proj.min(), c + major * proj.max()
            found.append({
                "frame": i, "x0": round(float(p0[0]), 1), "y0": round(float(p0[1]), 1),
                "x1": round(float(p1[0]), 1), "y1": round(float(p1[1]), 1),
                "length_px": round(length, 1),
                "angle_deg": round(math.degrees(math.atan2(major[1], major[0])) % 180.0, 1),
                "peak_sigma": round(float(resid[ys, xs].max() / mad), 1),
            })
        for t in found:  # collinear dashes in one frame: probably an aircraft's blinking lights
            t["dashed"] = sum(1 for u in found if u is not t and abs(u["angle_deg"] - t["angle_deg"]) < 3.0
                              and _line_dist(t, u["x0"], u["y0"]) < 6.0) > 0
        trails.extend(found)
    return trails


def _line_dist(t: dict[str, Any], x: float, y: float) -> float:
    dx, dy = t["x1"] - t["x0"], t["y1"] - t["y0"]
    norm = math.hypot(dx, dy) or 1.0
    return abs(dy * (x - t["x0"]) - dx * (y - t["y0"])) / norm


# ------------------------------------------------------------- plate solving
def solver_available() -> bool:
    return shutil.which("solve-field") is not None


def plate_solve(path: Path, timeout_s: int = 120) -> dict[str, Any]:
    """Sky position of a frame with astrometry.net (offline). Never guesses."""
    if not solver_available():
        return {"status": "unavailable",
                "reason": "astrometry.net is not installed on this station (sudo apt install astrometry.net "
                          "astrometry-data-4100 or wide-field index files)"}
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / ("frame" + path.suffix.lower())
        if path.suffix.lower() in (".fits", ".fit", ".fts"):
            shutil.copy(path, src)
        else:  # solve on a moderate-size grey image: faster, and phone JPEG noise matters less
            Image.fromarray(np.clip(load_gray(path, 2000), 0, 255).astype(np.uint8)).save(src.with_suffix(".png"))
            src = src.with_suffix(".png")
        cmd = ["solve-field", str(src), "--dir", tmp, "--no-plots", "--overwrite", "--downsample", "2",
               "--scale-units", "degwidth", "--scale-low", "1", "--scale-high", "120",
               "--cpulimit", str(timeout_s), "--tweak-order", "3", "--new-fits", "none", "--corr", "none",
               "--rdls", "none", "--match", "none", "--index-xyls", "none", "--solved", "none"]
        try:
            subprocess.run(cmd, capture_output=True, timeout=timeout_s + 30, check=False)
        except subprocess.TimeoutExpired:
            return {"status": "failed", "reason": f"no solution within {timeout_s} s"}
        wcs_file = src.with_suffix(".wcs")
        if not wcs_file.exists():
            return {"status": "failed", "reason": "astrometry.net found no match (too few stars, clouds, or "
                                                  "no index files for this field size)"}
        from astropy.io import fits
        from astropy.wcs import WCS

        header = fits.getheader(wcs_file)
        w = WCS(header)
        with Image.open(src) as im:
            width, height = im.size
        ra, dec = (float(v) for v in w.all_pix2world([[width / 2.0, height / 2.0]], 0)[0])
        corners = w.all_pix2world([[0, height / 2.0], [width, height / 2.0]], 0)
        from astropy.coordinates import SkyCoord
        import astropy.units as u

        a = SkyCoord(corners[0][0] * u.deg, corners[0][1] * u.deg)
        b = SkyCoord(corners[1][0] * u.deg, corners[1][1] * u.deg)
        return {"status": "solved", "ra": round(ra, 4), "dec": round(dec, 4),
                "field_width_deg": round(float(a.separation(b).deg), 2), "solved_size": [width, height],
                "wcs": {k: header[k] for k in header if k[:2] in ("CR", "CD", "CT", "A_", "B_", "AP", "BP") or k in ("A_ORDER", "B_ORDER")},
                "solver": "astrometry.net (local)"}


# --------------------------------------------------------------- Pi camera
def camera_available() -> bool:
    return shutil.which("rpicam-still") is not None or shutil.which("libcamera-still") is not None


def capture_frames(count: int, exposure_s: float, gain: float = 8.0) -> str:
    """Take `count` frames with the Pi camera into a new session; returns its id."""
    exe = shutil.which("rpicam-still") or shutil.which("libcamera-still")
    if not exe:
        raise GroundNodeError("no_camera", "no Raspberry Pi camera software on this machine (rpicam-still)")
    sid, d = _new_session("pi_camera", f"Pi camera, {count} x {exposure_s:g} s")
    try:
        for i in range(count):
            out = d / "frames" / f"{i:03d}.jpg"
            started = datetime.now(timezone.utc)
            res = subprocess.run([exe, "-n", "--immediate", "-o", str(out), "--shutter", str(int(exposure_s * 1e6)),
                                  "--gain", f"{gain:g}", "--awbgains", "1,1", "--denoise", "off"],
                                 capture_output=True, timeout=exposure_s * 3 + 30, check=False)
            if res.returncode != 0 or not out.exists():
                raise GroundNodeError("camera_failed", (res.stderr or b"").decode(errors="replace")[-300:] or "capture failed")
            _append_frame(d, out, {"time_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"), "exposure_s": exposure_s,
                                   "camera": "Raspberry Pi camera (this station)", "time_note": None})
    except Exception:
        _write(d, {**_read(d), "status": "failed"})
        raise
    return sid


# ----------------------------------------------------------------- sessions
def _read(d: Path) -> dict[str, Any]:
    return json.loads((d / "session.json").read_text(encoding="utf-8"))


def _write(d: Path, data: dict[str, Any]) -> None:
    tmp = d / "session.json.tmp"
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(d / "session.json")


def _new_session(source: str, label: str) -> tuple[str, Path]:
    sid = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    d = root_dir() / sid
    (d / "frames").mkdir(parents=True, exist_ok=True)
    _write(d, {"id": sid, "source": source, "label": label, "created": time.time(), "frames": [],
               "status": "new", "analysis": None})
    return sid, d


def _append_frame(d: Path, path: Path, meta: Optional[dict[str, Any]] = None) -> None:
    data = _read(d)
    data["frames"].append({"file": path.name, **(meta or read_metadata(path))})
    _write(d, data)


def create_upload_session(files: list[tuple[str, bytes]], label: str = "") -> dict[str, Any]:
    """Store an uploaded image sequence (e.g. phone frames from a tripod)."""
    usable = [(n, b) for n, b in files if Path(n).suffix.lower() in IMAGE_SUFFIXES and b]
    if not usable:
        raise GroundNodeError("no_images", "no JPEG, PNG, TIFF or FITS files in the upload")
    if len(usable) > MAX_FRAMES:
        raise GroundNodeError("too_many", f"at most {MAX_FRAMES} frames per session")
    sid, d = _new_session("upload", label.strip()[:120])
    for i, (name, blob) in enumerate(sorted(usable, key=lambda x: x[0])):
        out = d / "frames" / f"{i:03d}{Path(name).suffix.lower()}"
        out.write_bytes(blob)
        try:
            meta = read_metadata(out)
        except Exception as exc:  # noqa: BLE001 - unreadable file: drop it, say so
            out.unlink(missing_ok=True)
            logger.warning(f"ground node: unreadable upload {name}: {exc}")
            continue
        _append_frame(d, out, {**meta, "original_name": Path(name).name})
    data = _read(d)
    if not data["frames"]:
        shutil.rmtree(d, ignore_errors=True)
        raise GroundNodeError("no_images", "none of the uploaded files could be read as an image")
    # frames in time order when every frame has a time, else in file-name order
    if all(f.get("time_utc") or f.get("time_local") for f in data["frames"]):
        data["frames"].sort(key=lambda f: f.get("time_utc") or f.get("time_local"))
    cams = sorted({f["camera"] for f in data["frames"] if f.get("camera")})
    data["label"] = data["label"] or f"Uploaded, {len(data['frames'])} frames"
    data["provenance"] = f"Uploaded image sequence ({', '.join(cams) if cams else 'camera unknown'})"
    _write(d, data)
    return data


def analyze(sid: str) -> dict[str, Any]:
    d = _session_dir(sid)
    if not d.exists():
        raise GroundNodeError("not_found", "unknown session")
    data = _read(d)
    paths = [d / "frames" / f["file"] for f in data["frames"]]
    t0 = time.perf_counter()
    frames = [load_gray(p) for p in paths]
    trails = detect_trails(frames)
    mid = paths[len(paths) // 2]
    solve = plate_solve(mid)
    if solve.get("status") == "solved":  # trail ends on the sky
        _trails_to_sky(trails, solve, frames[0].shape)
    has_time = all(f.get("time_utc") for f in data["frames"])
    has_place = all(f.get("lat") is not None for f in data["frames"])
    data["analysis"] = {
        "frames": len(frames), "size_px": [frames[0].shape[1], frames[0].shape[0]],
        "trails": trails, "n_trails": len(trails), "n_dashed": sum(1 for t in trails if t.get("dashed")),
        "plate_solve": solve,
        "satellite_id": {"status": "pending" if has_time and has_place else "unavailable",
                         "reason": None if has_time and has_place else
                         "needs the UTC time and place of every frame (EXIF time with timezone + GPS)"},
        "elapsed_s": round(time.perf_counter() - t0, 1),
    }
    data["status"] = "analyzed"
    _write(d, data)
    return data


def _trails_to_sky(trails: list[dict[str, Any]], solve: dict[str, Any], shape: tuple[int, int]) -> None:
    from astropy.wcs import WCS

    w = WCS(solve["wcs"])
    sw, sh = solve["solved_size"]
    sx, sy = sw / shape[1], sh / shape[0]
    for t in trails:
        (ra0, de0), (ra1, de1) = w.all_pix2world([[t["x0"] * sx, t["y0"] * sy], [t["x1"] * sx, t["y1"] * sy]], 0)
        t["sky"] = {"ra0": round(float(ra0), 3), "dec0": round(float(de0), 3),
                    "ra1": round(float(ra1), 3), "dec1": round(float(de1), 3)}


def list_sessions() -> list[dict[str, Any]]:
    out = []
    root = root_dir()
    if root.exists():
        for d in sorted(root.iterdir(), reverse=True):
            try:
                s = _read(d)
            except (OSError, ValueError):
                continue
            a = s.get("analysis") or {}
            out.append({k: s.get(k) for k in ("id", "source", "label", "provenance", "created", "status")}
                       | {"n_frames": len(s.get("frames", [])), "n_trails": a.get("n_trails"),
                          "solved": (a.get("plate_solve") or {}).get("status") == "solved"})
    return out


def get_session(sid: str) -> dict[str, Any]:
    d = _session_dir(sid)
    if not d.exists():
        raise GroundNodeError("not_found", "unknown session")
    return _read(d)


def frame_preview(sid: str, index: int) -> bytes:
    d = _session_dir(sid)
    data = _read(d)
    if not 0 <= index < len(data["frames"]):
        raise GroundNodeError("not_found", "no such frame")
    img = load_gray(d / "frames" / data["frames"][index]["file"], PREVIEW_MAX_PX)
    lo, hi = np.percentile(img, [1, 99.7])
    img = np.clip((img - lo) / max(hi - lo, 1e-6), 0, 1) ** 0.6 * 255
    import io

    buf = io.BytesIO()
    Image.fromarray(img.astype(np.uint8)).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def status() -> dict[str, Any]:
    return {"camera": camera_available(), "plate_solver": solver_available(), "sessions": len(list_sessions()),
            "inputs": {"pi_camera": camera_available(), "upload": True, "indi_telescope": False}}
