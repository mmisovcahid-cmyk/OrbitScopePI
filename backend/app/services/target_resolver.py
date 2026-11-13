"""
OrbitScope - Target resolver
============================
Turns user input into ICRS coordinates (+ proper motion when known):

* decimal degrees           "269.452 4.693" / "269.452, +4.693"
* sexagesimal               "08h55m10.831s -7d14m42.53s" / "17:57:48.5 +04:41:36"
* built-in challenge targets (Gaia DR3 / SIMBAD values)
* any object name via CDS Sesame (several mirrors), then NED as a last resort
"""
from __future__ import annotations

import math
import re
from typing import Any, Optional
from urllib.parse import quote

import astropy.units as u
import httpx
from astropy.coordinates import SkyCoord
from cachetools import TTLCache

from app.core import offline
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Challenge targets. Positions/PM from Gaia DR3 (epoch 2016.0) or SIMBAD (epoch 2000.0).
BUILTIN_TARGETS: list[dict[str, Any]] = [
    {
        "id": "barnard", "name": "Barnard's Star", "aliases": ["barnard", "barnards star", "barnard's star", "gj 699", "v2500 oph"],
        "ra": 269.44850252543836, "dec": 4.739420051112412, "pmra": -801.551, "pmdec": 10362.394, "ref_epoch": 2016.0,
        "kind": "high_pm_star", "note": "Highest proper motion star: ~10.4\"/yr northward.", "detector": 3,
    },
    {
        "id": "eps-indi-b", "name": "Epsilon Indi B", "aliases": ["eps indi b", "epsilon indi b", "ε indi b", "eps ind b", "epsilon indi ba"],
        "ra": 331.07645259656397, "dec": -56.79381206688221, "pmra": 3981.977, "pmdec": -2466.832, "ref_epoch": 2016.0,
        "kind": "brown_dwarf_binary", "note": "Pair of brown dwarfs moving ~4.7\"/yr.", "detector": 4,
    },
    {
        "id": "wise-0855", "name": "WISE 0855-0714", "aliases": ["wise 0855", "wise 0855-0714", "wise j085510.83-071442.5", "wise0855"],
        "ra": 133.81890825, "dec": -7.247048, "pmra": -8123.7, "pmdec": 673.2, "ref_epoch": 2000.0,
        "kind": "brown_dwarf", "note": "Coldest known brown dwarf, ~8.2\"/yr westward. Brightest near 4.5 µm (detector 6).", "detector": 6,
    },
    {
        "id": "rw-aur", "name": "RW Aurigae", "aliases": ["rw aur", "rw aurigae"],
        "ra": 76.95608119552952, "dec": 30.401204589097233, "pmra": 2.641, "pmdec": -27.398, "ref_epoch": 2016.0,
        "kind": "variable_star", "note": "Young variable star with deep dimming events.", "detector": 3,
    },
    {
        "id": "r-dra", "name": "R Draconis", "aliases": ["r dra", "r draconis"],
        "ra": 248.1673783672889, "dec": 66.75500674547219, "pmra": -20.643, "pmdec": 6.149, "ref_epoch": 2016.0,
        "kind": "variable_star", "note": "Mira variable (period ~246 d).", "detector": 3,
    },
]

SESAME_MIRRORS = [
    "https://cds.unistra.fr/cgi-bin/nph-sesame/-oI/SNV",
    "http://vizier.cfa.harvard.edu/viz-bin/nph-sesame/-oI/SNV",
]
NED_LOOKUP = "https://ned.ipac.caltech.edu/srs/ObjectLookup"

_cache: TTLCache = TTLCache(maxsize=512, ttl=24 * 3600)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower().replace("_", " ").replace("-", " ").replace("’", "'"))


def parse_coordinates(text: str) -> Optional[tuple[float, float]]:
    """Parse decimal or sexagesimal coordinates. Returns (ra_deg, dec_deg) or None."""
    s = text.strip()
    m = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*[, ]\s*([+-]?\d+(?:\.\d+)?)\s*", s)
    if m:
        ra, dec = float(m.group(1)), float(m.group(2))
        if 0 <= ra < 360 and -90 <= dec <= 90:
            return ra, dec
        return None
    if not re.search(r"\d", s) or not re.search(r"[hHdD:°'\"\s]", s):
        return None
    try:
        parts = s.replace(",", " ")
        tokens = parts.split()
        first = tokens[0] if tokens else ""
        # "12h34m.." / "12:34:56" / "12 34 56 +12 34 56" -> hours; "123d45m.." -> degrees
        ra_unit = u.deg if re.search(r"[dD°]", first) else u.hourangle
        c = SkyCoord(parts, unit=(ra_unit, u.deg), frame="icrs")
        return float(c.ra.deg), float(c.dec.deg)
    except Exception:
        return None


def find_builtin(text: str) -> Optional[dict[str, Any]]:
    n = _norm(text)
    for t in BUILTIN_TARGETS:
        if n == t["id"] or n == _norm(t["name"]) or n in (_norm(a) for a in t["aliases"]):
            return t
    return None


COORD_MATCH_ARCSEC = 30.0


def builtin_near(ra: float, dec: float) -> Optional[tuple[dict[str, Any], int]]:
    """A challenge target whose track (1990-2035) passes within 30" of these coordinates.

    Coordinates of a fast mover are only valid at one epoch: the challenge lists WISE 0855 at
    its ~2010 position, about 2' from where SPHEREx sees it. Recognising the target lets the
    proper motion be applied, so the viewer is centred on the object and marks it.
    """
    best: Optional[tuple[float, dict[str, Any], int]] = None
    for t in BUILTIN_TARGETS:
        if abs(t["dec"] - dec) > 0.2:
            continue
        cosd = math.cos(math.radians(t["dec"]))
        for year in range(1990, 2036):
            dt = year - t["ref_epoch"]
            tra = t["ra"] + t["pmra"] / 3.6e6 * dt / max(cosd, 1e-6)
            tdec = t["dec"] + t["pmdec"] / 3.6e6 * dt
            sep = math.hypot((tra - ra) * cosd, tdec - dec) * 3600.0
            if sep <= COORD_MATCH_ARCSEC and (best is None or sep < best[0]):
                best = (sep, t, year)
    return (best[1], best[2]) if best else None


async def _sesame(client: httpx.AsyncClient, name: str) -> Optional[dict[str, Any]]:
    for url in SESAME_MIRRORS:
        try:
            resp = await client.get(f"{url}?{quote(name)}")
        except httpx.HTTPError:
            continue
        if resp.status_code != 200:
            continue
        ra = dec = pmra = pmdec = None
        for line in resp.text.splitlines():
            if line.startswith("%J ") and ra is None:
                p = line.split()
                ra, dec = float(p[1]), float(p[2])
            elif line.startswith("%P ") and pmra is None:
                p = line.split()
                try:
                    pmra, pmdec = float(p[1]), float(p[2])
                except (IndexError, ValueError):
                    pass
        if ra is not None:
            return {"ra": ra, "dec": dec, "pmra": pmra, "pmdec": pmdec, "ref_epoch": 2000.0, "source": "CDS Sesame"}
    return None


async def _ned(client: httpx.AsyncClient, name: str) -> Optional[dict[str, Any]]:
    try:
        resp = await client.post(NED_LOOKUP, data={"json": '{"name":{"v":"%s"}}' % name.replace('"', "")})
        pos = resp.json().get("Preferred", {}).get("Position")
        if pos:
            return {"ra": float(pos["RA"]), "dec": float(pos["Dec"]), "pmra": None, "pmdec": None, "ref_epoch": 2000.0, "source": "NED"}
    except Exception:
        return None
    return None


async def resolve(text: str) -> Optional[dict[str, Any]]:
    """Resolve free-form input. Returns dict with ra/dec/pm/name/source or None."""
    if not text or not text.strip():
        return None
    query = text.strip()
    coords = parse_coordinates(query)
    if coords:
        known = builtin_near(coords[0], coords[1])
        if known:
            t, year = known
            return {**{k: t[k] for k in ("ra", "dec", "pmra", "pmdec", "ref_epoch", "note", "detector")},
                    "name": t["name"], "id": t["id"], "source": "coordinates -> built-in target (Gaia DR3 / SIMBAD)",
                    "matched_epoch": year}
        return {"name": None, "ra": coords[0], "dec": coords[1], "pmra": None, "pmdec": None,
                "ref_epoch": 2000.0, "source": "coordinates"}

    builtin = find_builtin(query)
    if builtin:
        return {**{k: builtin[k] for k in ("ra", "dec", "pmra", "pmdec", "ref_epoch", "note", "detector")},
                "name": builtin["name"], "id": builtin["id"], "source": "built-in (Gaia DR3 / SIMBAD)"}

    key = _norm(query)
    if key in _cache:
        return _cache[key]
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        result = await _sesame(client, query) or await _ned(client, query)
    if result:
        result["name"] = query
        _cache[key] = result
        offline.save("names", key, result)
        return result
    # Sesame and NED both failed or did not know the name: a position resolved earlier still holds
    # (catalog positions do not change), so offline demos keep working for names used before.
    snap = offline.load("names", key)
    if snap is not None:
        return offline.mark(snap[0], snap[1])
    return None
