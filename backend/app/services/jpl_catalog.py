"""
OrbitScope - live NASA/JPL catalog access (no simulated fallbacks)
==================================================================
* SBDB  (ssd-api.jpl.nasa.gov/sbdb.api)    object data, orbit, physical parameters, discovery,
                                           close approaches; multiple matches are returned as a list
* Horizons (ssd.jpl.nasa.gov/api/horizons.api)  observer ephemeris (geocentric, CSV, degrees)
* SB Ident (via app.services.small_bodies) known asteroids/comets inside a sky field at a time

If JPL is unreachable the caller gets a ``JPLUnavailable`` error - nothing is invented.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from astropy.time import Time
from cachetools import TTLCache

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

SBDB_URL = settings.JPL_SBDB_URL
HORIZONS_URL = settings.JPL_HORIZONS_URL

MAJOR_BODIES = {
    "sun": "10", "mercury": "199", "venus": "299", "moon": "301", "mars": "499", "jupiter": "599",
    "saturn": "699", "uranus": "799", "neptune": "899", "pluto": "999",
}

_cache: TTLCache = TTLCache(maxsize=512, ttl=6 * 3600)


class JPLUnavailable(Exception):
    pass


class NotFound(Exception):
    pass


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


_sem: Optional[asyncio.Semaphore] = None


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(4)  # JPL answers bursts of requests with HTTP 503
    return _sem


async def _get(url: str, params: dict[str, str], timeout: float = 45.0) -> httpx.Response:
    """GET with at most 4 concurrent JPL requests and retries on 429/503."""
    last: Optional[httpx.Response] = None
    async with _semaphore():
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    last = await client.get(url, params=params)
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise JPLUnavailable(f"{type(exc).__name__}: {exc}") from exc
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if last.status_code not in (429, 503):
                return last
            await asyncio.sleep(1.5 * (attempt + 1))
    assert last is not None
    return last


# ------------------------------------------------------------------------ SBDB
def parse_sbdb(data: dict[str, Any], query: str) -> dict[str, Any]:
    obj = data.get("object", {})
    orbit = data.get("orbit", {}) or {}
    el = {e.get("name"): _f(e.get("value")) for e in orbit.get("elements", []) if isinstance(e, dict)}
    phys = {p.get("name"): p.get("value") for p in data.get("phys_par", []) or [] if isinstance(p, dict)}
    kind = str(obj.get("kind", ""))
    is_comet = kind.startswith("c")
    per_d = el.get("per")
    now = datetime.now(timezone.utc)

    approaches = []
    for ca in data.get("ca_data", []) or []:
        try:
            when = datetime.strptime(ca["cd"], "%Y-%b-%d %H:%M").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        dist = _f(ca.get("dist"))
        approaches.append({"date": ca["cd"], "body": ca.get("body", "Earth"), "distance_au": dist,
                           "distance_ld": round(dist / 0.0025695, 2) if dist else None,
                           "velocity_km_s": _f(ca.get("v_rel")), "future": when >= now})
    upcoming = [a for a in approaches if a["future"]][:8]
    recent = [a for a in approaches if not a["future"]][-3:]

    disc = data.get("discovery") or {}
    spec = phys.get("spec_B") or phys.get("spec_T")
    return {
        "designation": obj.get("des"),
        "name": obj.get("fullname") or obj.get("shortname") or obj.get("des"),
        "spkid": obj.get("spkid"),
        "kind": "comet" if is_comet else "asteroid",
        "numbered": kind.endswith("n"),
        "orbit_class": obj.get("orbit_class") or {},
        "neo": bool(obj.get("neo")),
        "pha": bool(obj.get("pha")),
        "elements": {
            "a_au": el.get("a"), "e": el.get("e"), "i_deg": el.get("i"), "om_deg": el.get("om"),
            "w_deg": el.get("w"), "ma_deg": el.get("ma"), "q_au": el.get("q"), "ad_au": el.get("ad"),
            "period_yr": round(per_d / 365.25, 3) if per_d else None, "tp_jd": el.get("tp"),
            "epoch_jd": _f(orbit.get("epoch")), "moid_au": _f(orbit.get("moid")), "t_jup": _f(orbit.get("t_jup")),
        },
        "physical": {
            "H": _f(phys.get("H")), "G": _f(phys.get("G")), "diameter_km": _f(phys.get("diameter")),
            "albedo": _f(phys.get("albedo")), "rotation_h": _f(phys.get("rot_per")), "spectral_type": spec,
            "extent": phys.get("extent"), "density": _f(phys.get("density")),
        },
        "orbit_quality": {
            "condition_code": orbit.get("condition_code"), "n_obs": orbit.get("n_obs_used"),
            "first_obs": orbit.get("first_obs"), "last_obs": orbit.get("last_obs"),
            "data_arc_days": orbit.get("data_arc"), "solution": orbit.get("soln_date"),
        },
        "discovery": {"text": disc.get("discovery"), "date": disc.get("date"), "who": disc.get("who"),
                      "location": disc.get("location")} if disc else None,
        "close_approaches": {"upcoming": upcoming, "recent": recent, "total": len(approaches)},
        "source": "NASA/JPL Small-Body Database (SBDB API)",
        "url": f"https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr={obj.get('spkid') or query}",
        "is_simulated": False,
    }


SBDB_QUERY_URL = SBDB_URL.replace("sbdb.api", "sbdb_query.api")
ETNO_FIELDS = ["pdes", "full_name", "a", "e", "i", "q", "om", "w", "ad", "H", "condition_code", "data_arc", "n_obs_used"]


async def sbdb_query_etnos(min_a_au: float, min_q_au: float) -> list[dict[str, Any]]:
    """Every object in SBDB with a >= min_a and q >= min_q (JPL SBDB Query API), as dicts."""
    key = f"etnoq:{min_a_au}:{min_q_au}"
    if key in _cache:
        return _cache[key]
    cdata = json.dumps({"AND": [f"a|GE|{min_a_au:g}", f"q|GE|{min_q_au:g}"]})
    resp = await _get(SBDB_QUERY_URL, {"fields": ",".join(ETNO_FIELDS), "sb-cdata": cdata}, timeout=60.0)
    if resp.status_code != 200:
        raise JPLUnavailable(f"SBDB Query HTTP {resp.status_code}")
    payload = resp.json()
    fields = payload.get("fields") or ETNO_FIELDS
    rows = [dict(zip(fields, r)) for r in payload.get("data", [])]
    _cache[key] = rows
    return rows


async def sbdb_lookup(query: str) -> dict[str, Any]:
    """Returns {"match": object} or {"matches": [...]} (several objects fit the query)."""
    q = query.strip()
    key = f"sbdb:{q.lower()}"
    if key in _cache:
        return _cache[key]
    resp = await _get(SBDB_URL, {"sstr": q, "phys-par": "1", "ca-data": "1", "discovery": "1"})
    if resp.status_code == 300 or (resp.status_code == 200 and resp.json().get("code") == "300"):
        lst = resp.json().get("list", [])
        out: dict[str, Any] = {"matches": [{"designation": m.get("pdes"), "name": m.get("name")} for m in lst][:50]}
    elif resp.status_code == 200:
        data = resp.json()
        if "object" not in data:
            raise NotFound(q)
        out = {"match": parse_sbdb(data, q)}
    elif resp.status_code in (400, 404):
        raise NotFound(q)
    else:
        raise JPLUnavailable(f"SBDB HTTP {resp.status_code}")
    _cache[key] = out
    return out


# -------------------------------------------------------------------- Horizons
def horizons_command(query: str, sbdb: Optional[dict[str, Any]]) -> str:
    if sbdb:
        if sbdb["kind"] == "comet":
            return f"DES={sbdb['designation']};CAP;"
        return f"DES={sbdb['spkid']};"
    return MAJOR_BODIES.get(query.strip().lower(), query.strip())


def parse_horizons_csv(text: str) -> list[dict[str, Any]]:
    soe, eoe = text.find("$$SOE"), text.find("$$EOE")
    if soe < 0 or eoe < soe:
        return []
    header_line = ""
    for line in reversed(text[:soe].splitlines()):
        if "Date" in line and "," in line:
            header_line = line
            break
    cols = [c.strip() for c in header_line.split(",")]
    rows = []
    for rec in csv.reader(io.StringIO(text[soe + 5:eoe].strip())):
        if not rec:
            continue
        row = dict(zip(cols, (r.strip() for r in rec)))
        mag = _f(row.get("APmag")) if "APmag" in row else _f(row.get("T-mag"))
        rows.append({
            "time_utc": row.get("Date__(UT)__HR:MN") or rec[0].strip(),
            "ra_deg": _f(row.get("R.A._(ICRF)")), "dec_deg": _f(row.get("DEC_(ICRF)")),
            "magnitude": mag, "r_au": _f(row.get("r")), "delta_au": _f(row.get("delta")),
            "elongation_deg": _f(row.get("S-O-T")), "phase_deg": _f(row.get("S-T-O")),
        })
    return [r for r in rows if r["ra_deg"] is not None]


async def ephemeris(query: str, start: Optional[str] = None, days: int = 7, step: str = "1d") -> dict[str, Any]:
    q = query.strip()
    sbdb: Optional[dict[str, Any]] = None
    if q.lower() not in MAJOR_BODIES:
        found = await sbdb_lookup(q)
        if "matches" in found:
            return {"matches": found["matches"]}
        sbdb = found["match"]
    t0 = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start else datetime.now(timezone.utc)
    t1 = t0 + timedelta(days=max(1, min(days, 366)))
    cmd = horizons_command(q, sbdb)
    key = f"hz:{cmd}:{t0:%Y-%m-%d %H}:{t1:%Y-%m-%d}:{step}"
    if key in _cache:
        return _cache[key]
    params = {
        "format": "json", "COMMAND": f"'{cmd}'", "OBJ_DATA": "'NO'", "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'", "CENTER": "'500@399'", "START_TIME": f"'{t0:%Y-%m-%d %H:%M}'",
        "STOP_TIME": f"'{t1:%Y-%m-%d %H:%M}'", "STEP_SIZE": f"'{step}'",
        "QUANTITIES": "'1,9,19,20,23,24'", "CSV_FORMAT": "'YES'", "ANG_FORMAT": "'DEG'",
    }
    resp = await _get(HORIZONS_URL, params, timeout=60.0)
    if resp.status_code != 200:
        raise JPLUnavailable(f"Horizons HTTP {resp.status_code}")
    text = resp.json().get("result", "")
    rows = parse_horizons_csv(text)
    if not rows:
        if "Matching small-bodies" in text or "Multiple major-bodies" in text:
            raise NotFound(f"{q} (ambiguous in Horizons)")
        raise NotFound(q)
    name_line = next((ln for ln in text.splitlines() if ln.startswith("Target body name")), "")
    out = {
        "target": q, "resolved_name": name_line.split(":", 1)[1].split("{")[0].strip() if name_line else q,
        "command": cmd, "center": "Earth (geocentric)", "step": step,
        "rows": rows, "source": "NASA/JPL Horizons API", "is_simulated": False,
    }
    _cache[key] = out
    return out


# ---------------------------------------------------------------- field search
async def known_in_field(ra: float, dec: float, radius_deg: float, when: Optional[str] = None,
                         vmag_lim: float = 21.0) -> dict[str, Any]:
    """Known asteroids/comets within radius of (ra, dec) at time `when` (UTC ISO date/time, default now)."""
    from app.services.small_bodies import objects_in_field

    t = datetime.fromisoformat(when).replace(tzinfo=timezone.utc) if when else datetime.now(timezone.utc)
    mjd = float(Time(t).mjd)
    try:
        objs = await objects_in_field(ra, dec, max(radius_deg, 0.01), mjd, vmag_lim)
    except Exception as exc:
        raise JPLUnavailable(str(exc)) from exc
    out = []
    for o in objs:
        d_ra = (o["ra"] - ra + 540.0) % 360.0 - 180.0
        sep = math.hypot(d_ra * math.cos(math.radians(dec)), o["dec"] - dec)
        if sep <= radius_deg:
            out.append({**o, "separation_arcmin": round(sep * 60.0, 2),
                        "rate_arcsec_per_hour": round(math.hypot(o["rate_ra"], o["rate_dec"]), 2)})
    out.sort(key=lambda o: o["separation_arcmin"])
    return {"time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "ra": ra, "dec": dec, "radius_deg": radius_deg,
            "vmag_lim": vmag_lim, "objects": out, "source": "NASA/JPL Small-Body Identification API",
            "is_simulated": False}
