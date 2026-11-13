"""
OrbitScope - extreme TNO orbits from JPL and the Planet Nine clustering statistic
=================================================================================
The Planet Nine hypothesis (Batygin & Brown 2016) rests on the observation that distant,
detached Kuiper-belt objects have their orbits' perihelia (longitude of perihelion
varpi = Omega + omega) bunched in one direction. Here the orbits are fetched LIVE from the
JPL Small-Body Database and the clustering is measured with the Rayleigh test.

Caveat reported to the user: surveys find eTNOs only where they looked, so observational
selection can mimic clustering (Shankman et al. 2017; Napier et al. 2021).
"""
from __future__ import annotations

import asyncio
import math
from typing import Any

from cachetools import TTLCache

from app.core.logging_config import get_logger
from app.services import jpl_catalog as jc

logger = get_logger(__name__)

# Distant detached objects discussed in the Planet Nine literature (designations JPL understands).
ETNO_DESIGNATIONS = [
    "90377", "2012 VP113", "2004 VN112", "2010 GB174", "2013 SY99", "2014 SR349", "2015 TG387",
    "2007 TG422", "2013 RF98", "2015 RX245", "2014 FE72", "2013 FT28", "2015 KG163", "2016 QV89",
    "2016 QU89", "2018 VM35", "2015 BP519", "2013 UH15", "2003 SS422", "2000 CR105",
]
MIN_A_AU = 150.0
MIN_Q_AU = 30.0

_cache: TTLCache = TTLCache(maxsize=4, ttl=12 * 3600)


def rayleigh(angles_deg: list[float]) -> dict[str, float]:
    """Rayleigh test for a preferred direction (small-sample corrected p-value, Zar 2010)."""
    n = len(angles_deg)
    if n < 3:
        return {"n": n, "mean_deg": float("nan"), "R": float("nan"), "Z": float("nan"), "p": float("nan")}
    c = sum(math.cos(math.radians(a)) for a in angles_deg)
    s = sum(math.sin(math.radians(a)) for a in angles_deg)
    r_bar = math.hypot(c, s) / n
    z = n * r_bar**2
    p = math.exp(-z) * (1 + (2 * z - z**2) / (4 * n) - (24 * z - 132 * z**2 + 76 * z**3 - 9 * z**4) / (288 * n**2))
    return {"n": n, "mean_deg": round(math.degrees(math.atan2(s, c)) % 360.0, 1), "R": round(r_bar, 3),
            "Z": round(z, 3), "p": round(min(max(p, 0.0), 1.0), 5)}


MAX_CONDITION_CODE = 5  # JPL orbit uncertainty 0 (best) .. 9; above 5 the angles are poorly known


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _row(r: dict[str, Any]) -> dict[str, Any] | None:
    a, q, om, w = _f(r.get("a")), _f(r.get("q")), _f(r.get("om")), _f(r.get("w"))
    if None in (a, q, om, w):
        return None
    des = str(r.get("pdes") or "").strip()
    cc = r.get("condition_code")
    return {
        "designation": des, "name": str(r.get("full_name") or des).strip(),
        "a_au": a, "e": _f(r.get("e")), "i_deg": _f(r.get("i")), "q_au": q, "ad_au": _f(r.get("ad")),
        "om_deg": om, "w_deg": w, "varpi_deg": round((om + w) % 360.0, 2),
        "H": _f(r.get("H")), "condition_code": str(cc) if cc not in (None, "") else None,
        "data_arc_days": _f(r.get("data_arc")),
        "url": f"https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr={des.replace(' ', '%20')}",
    }


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "n": len(rows),
        "varpi": rayleigh([r["varpi_deg"] for r in rows]),
        "node": rayleigh([r["om_deg"] for r in rows]),
        "argperi": rayleigh([r["w_deg"] for r in rows]),
    }


async def etno_analysis() -> dict[str, Any]:
    """Clustering of extreme TNO orbits, on two samples, both fetched live from JPL.

    - complete: EVERY object in SBDB with a >= 150 AU and q >= 30 AU and a well-determined orbit
      (condition code <= 5) - an objective selection, nothing hand-picked;
    - literature: the ~20 objects usually discussed in Planet Nine papers.
    Comparing the two shows how much the result depends on which objects one picks.
    """
    if "result" in _cache:
        return _cache["result"]
    raw = await jc.sbdb_query_etnos(MIN_A_AU, MIN_Q_AU)
    rows = [r for r in (_row(x) for x in raw) if r]
    if not rows:
        raise jc.JPLUnavailable("no eTNO orbits could be retrieved")
    lit_set = {d.upper() for d in ETNO_DESIGNATIONS}
    found: set[str] = set()
    for r in rows:
        cc = r["condition_code"]
        r["in_sample"] = cc is not None and cc.isdigit() and int(cc) <= MAX_CONDITION_CODE
        # numbered objects: pdes is the number, the provisional designation is in the full name
        hit = {d for d in lit_set if d == r["designation"].upper() or f"({d})" in r["name"].upper()
               or r["name"].upper().startswith(d + " ")}
        r["in_literature"] = bool(hit)
        found |= hit
    sample = [r for r in rows if r["in_sample"]]
    literature = [r for r in rows if r["in_literature"]]
    complete = _stats(sample)
    out = {
        "objects": sorted(rows, key=lambda r: -r["a_au"]),
        "selection": {"min_a_au": MIN_A_AU, "min_q_au": MIN_Q_AU, "max_condition_code": MAX_CONDITION_CODE,
                      "n_total": len(rows)},
        "varpi": complete["varpi"], "node": complete["node"], "argperi": complete["argperi"],
        "literature": {**_stats(literature), "designations": ETNO_DESIGNATIONS,
                       "missing": len(lit_set - found)},
        "source": "NASA/JPL Small-Body Database Query API (live orbits)",
        "is_simulated": False,
        "missing": 0,
    }
    _cache["result"] = out
    return out
