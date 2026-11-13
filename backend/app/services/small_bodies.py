"""
OrbitScope - Known solar-system objects in a field (JPL SB Ident)
=================================================================
For a sky field and a time, asks the NASA/JPL Small-Body Identification API which numbered
and unnumbered asteroids and comets are inside, with their positions and on-sky rates.

SPHEREx exposures of one field come in short visits (a few exposures within minutes),
separated by hours to days. We query once per visit cluster and extrapolate linearly with
the returned rates to each exposure time (accurate to well under a pixel over < 1 day for
main-belt objects). Geocentric positions are used: SPHEREx is in low Earth orbit, so the
parallax for main-belt objects is below 1 arcsec (< 0.2 SPHEREx pixel).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Optional

import httpx
from astropy.time import Time
from cachetools import TTLCache

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

SB_IDENT_URL = "https://ssd-api.jpl.nasa.gov/sb_ident.api"
CLUSTER_GAP_DAYS = 0.3

_mem: TTLCache = TTLCache(maxsize=512, ttl=24 * 3600)
_sem = asyncio.Semaphore(3)


def _sexa_ra(ra_deg: float) -> str:
    h = (ra_deg % 360.0) / 15.0
    hh = int(h)
    m = (h - hh) * 60.0
    mm = int(m)
    ss = (m - mm) * 60.0
    if ss >= 59.995:
        ss, mm = 0.0, mm + 1
    if mm >= 60:
        mm, hh = 0, (hh + 1) % 24
    return f"{hh:02d}-{mm:02d}-{ss:05.2f}"


def _sexa_dec(dec_deg: float) -> str:
    sign = "-" if dec_deg < 0 else "+"
    a = abs(dec_deg)
    dd = int(a)
    m = (a - dd) * 60.0
    mm = int(m)
    ss = (m - mm) * 60.0
    if ss >= 59.95:
        ss, mm = 0.0, mm + 1
    if mm >= 60:
        mm, dd = 0, dd + 1
    return f"{sign}{dd:02d}-{mm:02d}-{ss:04.1f}"


def parse_ra(text: str) -> float:
    h, m, s = (float(x) for x in text.strip().split(":"))
    return (h + m / 60.0 + s / 3600.0) * 15.0


def parse_dec(text: str) -> float:
    m = re.match(r"\s*([+-]?)(\d+)\s+(\d+)'([\d.]+)", text)
    if not m:
        raise ValueError(f"bad dec {text!r}")
    sign = -1.0 if m.group(1) == "-" else 1.0
    return sign * (float(m.group(2)) + float(m.group(3)) / 60.0 + float(m.group(4)) / 3600.0)


def _num(text: Any) -> Optional[float]:
    try:
        v = float(str(text).strip())
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def parse_sb_ident(payload: dict[str, Any], mjd: float) -> list[dict[str, Any]]:
    fields = payload.get("fields_second") or payload.get("fields_first") or []
    rows = payload.get("data_second_pass") or payload.get("data_first_pass") or []
    idx = {name: i for i, name in enumerate(fields)}

    def col(row: list[Any], prefix: str) -> Any:
        for name, i in idx.items():
            if name.startswith(prefix):
                return row[i]
        return None

    out = []
    for row in rows:
        try:
            ra = parse_ra(col(row, "Astrometric RA"))
            dec = parse_dec(col(row, "Astrometric Dec"))
        except Exception:
            continue
        name = str(col(row, "Object name") or "").strip()
        out.append({
            "name": name,
            "kind": "comet" if re.search(r"(^|\s)(\d+[PCDXI]/|[PCDXI]/\d)", name) else "asteroid",
            "ra": ra, "dec": dec, "mjd": mjd,
            "vmag": _num(col(row, "Visual magnitude")),
            # RA rate is the on-sky rate (dRA*cos(Dec)), arcsec/hour - same convention as JPL Horizons.
            "rate_ra": _num(col(row, "RA rate")) or 0.0,
            "rate_dec": _num(col(row, "Dec rate")) or 0.0,
        })
    return out


async def objects_in_field(
    ra: float, dec: float, half_width_deg: float, mjd: float, vmag_lim: float = 21.0
) -> list[dict[str, Any]]:
    """Known asteroids/comets inside a square field at time `mjd` (cached in memory and on disk)."""
    key = f"{ra:.4f}:{dec:.4f}:{half_width_deg:.3f}:{mjd:.4f}:{vmag_lim:.1f}"
    if key in _mem:
        return _mem[key]
    cache_dir = Path(settings.SPHEREX_CACHE_DIR) / "sbident"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{hashlib.md5(key.encode()).hexdigest()[:20]}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _mem[key] = data
            return data
        except Exception:
            path.unlink(missing_ok=True)

    t = Time(mjd, format="mjd").to_datetime()
    params = {
        "mpc-code": "500",
        "obs-time": t.strftime("%Y-%m-%d_%H:%M:%S"),
        "fov-ra-center": _sexa_ra(ra),
        "fov-dec-center": _sexa_dec(dec),
        "fov-ra-hwidth": f"{half_width_deg:.4f}",
        "fov-dec-hwidth": f"{half_width_deg:.4f}",
        "two-pass": "true",
        "suppress-first-pass": "true",
        "vmag-lim": f"{vmag_lim:.1f}",
    }
    async with _sem:
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=150.0) as client:
                    resp = await client.get(SB_IDENT_URL, params=params)
                if resp.status_code == 200:
                    break
                logger.warning(f"SB Ident HTTP {resp.status_code}: {resp.text[:200]}")
            except httpx.HTTPError as exc:
                logger.warning(f"SB Ident request failed: {exc}")
            await asyncio.sleep(2.0 * (attempt + 1))
        else:
            raise RuntimeError("JPL SB Ident did not respond")
    payload = resp.json()
    data = parse_sb_ident(payload, mjd)
    _mem[key] = data
    try:
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass
    return data


def cluster_times(mjds: list[float], gap: float = CLUSTER_GAP_DAYS) -> list[list[float]]:
    clusters: list[list[float]] = []
    for m in sorted(mjds):
        if clusters and m - clusters[-1][-1] <= gap:
            clusters[-1].append(m)
        else:
            clusters.append([m])
    return clusters


def predict(obj: dict[str, Any], mjd: float) -> tuple[float, float]:
    """Linear extrapolation with the SB Ident rates (good to << 1 px within a day)."""
    dt_h = (mjd - obj["mjd"]) * 24.0
    dec = obj["dec"] + obj["rate_dec"] * dt_h / 3600.0
    ra = obj["ra"] + obj["rate_ra"] * dt_h / 3600.0 / max(math.cos(math.radians(obj["dec"])), 1e-6)
    return ra % 360.0, dec


async def known_objects_for_frames(
    ra: float, dec: float, fov_deg: float, frame_mjds: list[float], vmag_lim: float = 21.0
) -> dict[str, Any]:
    """Known small bodies for every frame time: one SB Ident query per visit cluster."""
    clusters = cluster_times(frame_mjds)
    half = fov_deg / 2.0 + 0.05
    results = await asyncio.gather(
        *(objects_in_field(ra, dec, half, (c[0] + c[-1]) / 2.0, vmag_lim) for c in clusters),
        return_exceptions=True,
    )
    objects: dict[str, dict[str, Any]] = {}
    errors = 0
    for res in results:
        if isinstance(res, Exception):
            errors += 1
            logger.warning(f"SB Ident cluster failed: {res}")
            continue
        for o in res:
            # Keep the ephemeris closest in time for each object.
            objects.setdefault(o["name"], o)
    per_frame: list[list[dict[str, Any]]] = []
    for m in frame_mjds:
        here = []
        for c, res in zip(clusters, results):
            if isinstance(res, Exception) or not (c[0] - 1e-6 <= m <= c[-1] + 1e-6):
                continue
            for o in res:
                p_ra, p_dec = predict(o, m)
                here.append({"name": o["name"], "kind": o["kind"], "vmag": o["vmag"], "ra": p_ra, "dec": p_dec,
                             "rate_ra": o["rate_ra"], "rate_dec": o["rate_dec"]})
        per_frame.append(here)
    return {
        "objects": list(objects.values()),
        "per_frame": per_frame,
        "n_queries": len(clusters),
        "failed_queries": errors,
        "vmag_lim": vmag_lim,
        "source": "NASA/JPL Small-Body Identification API (geocentric)",
    }
