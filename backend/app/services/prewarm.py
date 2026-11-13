"""Fill the SPHEREx cache for the challenge targets, so a demo never waits for IRSA.

The first view of a new field downloads 16-96 cutouts from IRSA (30-90 s). For the five
challenge targets everything a visitor is likely to open is downloaded in advance:

- Blink (default view) for all six detectors, and the Comparison page's deeper stacks;
- the spectrum / light curve (Photometry panel default);
- the Gaia DR3 / CatWISE2020 overlays of the Blink view (kept on disk);
- the three Detection examples (626 Notburga, epsilon Indi B, WISE 0855), saved as runs once,
  so Sky Explorer and the Detection page show real results immediately.

Used by ``scripts/prewarm.py`` and, when ``PREWARM_ON_STARTUP`` is true, by the app at startup
(in the background; requests are served normally meanwhile).
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Same defaults as the frontend (lib/spherex.ts DEFAULT_QUERY, ComparisonPage, PhotometryPanel).
BLINK_DEFAULTS = dict(fov=0.1, mode="epoch", per_epoch=4, max_frames=16)
COMPARISON_PER_EPOCH = 6
PHOT_MAX_FRAMES = 96

# Detection examples shown as presets on the Detection page (frontend/src/pages/DetectionPage.tsx).
DEMO_RUNS: list[dict[str, Any]] = [
    {"target": "9.6915 4.0152", "search": "asteroids", "detectors": [1, 4], "fov_deg": 0.3, "pass_index": 0},
    {"target": "Epsilon Indi B", "search": "proper_motion", "detectors": [4], "fov_deg": 0.1},
    {"target": "WISE 0855-0714", "search": "proper_motion", "detectors": [6], "fov_deg": 0.1},
]

Log = Callable[[str], None]


def _same_run(saved: dict[str, Any], want: dict[str, Any], tgt: dict[str, Any]) -> bool:
    p = saved.get("params", {})
    return (p.get("search") == want["search"] and p.get("detectors") == want["detectors"]
            and abs(float(p.get("fov") or 0) - want["fov_deg"]) < 1e-6
            and abs(float(p.get("ra") or 0) - tgt["ra"]) < 1e-3 and abs(float(p.get("dec") or 0) - tgt["dec"]) < 1e-3
            and (want.get("pass_index") is None or p.get("pass_index") == want["pass_index"]))


async def prewarm(
    target_ids: Optional[set[str]] = None,
    all_detectors: bool = True,
    photometry: bool = True,
    demo_runs: bool = True,
    log: Log = logger.info,
) -> bool:
    """Returns True when everything succeeded."""
    from app.api.routes import spherex as sx
    from app.services.candidate_store import get_store
    from app.services.catalog_overlay import fetch_catalog
    from app.services.detection_service import run_detection
    from app.services.spherex_archive import spherex_archive
    from app.services.target_resolver import BUILTIN_TARGETS, resolve

    ok = True
    t_all = time.perf_counter()
    targets = [t for t in BUILTIN_TARGETS if target_ids is None or t["id"] in target_ids]
    for t in targets:
        dets = [1, 2, 3, 4, 5, 6] if all_detectors else [int(t.get("detector", 3))]
        for det in dets:
            t0 = time.perf_counter()
            try:
                res = await sx._build(t["name"], None, None, None, None, None, BLINK_DEFAULTS["fov"], str(det),
                                      BLINK_DEFAULTS["mode"], BLINK_DEFAULTS["per_epoch"], BLINK_DEFAULTS["max_frames"], "en")
                log(f"{t['name']}: blink D{det} {len(res['frames'])} frames ({time.perf_counter() - t0:.0f} s)")
                if det == dets[0]:  # same grid for every detector: overlays once per target
                    g = res["grid"]
                    for cat in ("gaia", "catwise"):
                        try:  # same call as the Blink page's overlay request
                            await fetch_catalog(cat, g["ra"], g["dec"], radius_deg=g["fov_deg"] * 0.75, limit=1500)
                        except Exception as exc:  # noqa: BLE001
                            log(f"{t['name']}: {cat} overlay FAILED - {exc}")
            except Exception as exc:  # noqa: BLE001 - report and continue
                ok = False
                log(f"{t['name']}: blink D{det} FAILED - {getattr(exc, 'detail', exc)}")
        try:  # Comparison page (deeper stacks, default detector)
            await sx._build(t["name"], None, None, None, None, None, BLINK_DEFAULTS["fov"], str(t.get("detector", 3)),
                            "epoch", COMPARISON_PER_EPOCH, BLINK_DEFAULTS["max_frames"], "en")
        except Exception as exc:  # noqa: BLE001
            ok = False
            log(f"{t['name']}: comparison FAILED - {getattr(exc, 'detail', exc)}")
        if photometry:
            t0 = time.perf_counter()
            try:
                d = await spherex_archive.photometry(ra=t["ra"], dec=t["dec"], detectors=None, max_frames=PHOT_MAX_FRAMES,
                                                     pmra=t.get("pmra"), pmdec=t.get("pmdec"),
                                                     ref_epoch=t.get("ref_epoch") or 2000.0)
                log(f"{t['name']}: spectrum {d['n_good']}/{d['n_points']} good points ({time.perf_counter() - t0:.0f} s)")
            except Exception as exc:  # noqa: BLE001
                ok = False
                log(f"{t['name']}: spectrum FAILED - {exc}")

    if demo_runs:
        store = get_store()
        saved = store.recent_runs(limit=200)
        for want in DEMO_RUNS:
            tgt = await resolve(want["target"])
            if not tgt:
                continue
            if any(_same_run(r, want, tgt) for r in saved):
                log(f"demo run {want['target']} ({want['search']}): already saved")
                continue
            t0 = time.perf_counter()
            try:
                kw = {k: v for k, v in want.items() if k not in ("target",)}
                r = await run_detection(tgt, **kw)
                log(f"demo run {want['target']} ({want['search']}): {r['summary']['by_class']} ({time.perf_counter() - t0:.0f} s)")
            except Exception as exc:  # noqa: BLE001
                ok = False
                log(f"demo run {want['target']} FAILED - {exc}")

    stats = spherex_archive.cache_stats()
    log(f"prewarm done in {time.perf_counter() - t_all:.0f} s; cache {stats.get('cutouts')} cutouts, {stats.get('size_mb')} MB")
    return ok
