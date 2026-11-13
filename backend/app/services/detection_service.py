"""
OrbitScope - real-data moving-object detection service
======================================================
Glue between the SPHEREx archive (frames), the moving-object search, the reference
catalogs (JPL SB Ident for asteroids/comets, Gaia DR3 + CatWISE for stars and brown dwarfs)
and the candidate store.

search="asteroids"      individual exposures of one survey pass  -> solar-system objects
search="proper_motion"  one stack per survey pass (months apart) -> high proper-motion stars,
                        brown dwarfs, plus variable sources
"""
from __future__ import annotations

import asyncio
import math
import time
import uuid
from typing import Any, Optional

import numpy as np

from app.core.logging_config import get_logger
from app.core.progress import report
from app.pipeline import moving_objects as mo
from app.services.candidate_store import get_store
from app.services.catalog_overlay import CatalogError, fetch_catalog
from app.services.small_bodies import known_objects_for_frames
from app.services.spherex_archive import mjd_to_iso, mjd_to_year, propagate, spherex_archive

logger = get_logger(__name__)

SSO_MATCH_PX = 5.0  # ~30 arcsec: ephemeris + centroid tolerance
MAX_MOVER_RMS = mo.MAX_MOVER_RMS_PX
STAR_MATCH_PX = 2.0


def _pa_deg(dx_px: float, dy_px: float) -> float:
    """Position angle (deg, east of north) of a motion vector on the north-up/east-left grid."""
    return (math.degrees(math.atan2(-dx_px, dy_px)) + 360.0) % 360.0


TARGET_CONFIRM_SIGMA = 3.0  # one source with a known predicted motion: no look-elsewhere penalty


def _target_check(tgt: dict[str, Any], tr: Any, meas_pmra: float, meas_pmdec: float, pix: float) -> dict[str, Any]:
    """Compare the measured motion of the requested target with its catalog proper motion.

    A blind search over thousands of sources needs 5 sigma; testing one source against a
    predicted motion needs much less, so 3 sigma plus agreement within 3 errors confirms it.
    """
    sig = float(tr.extra.get("pm_sigma") or 0.0)
    span_yr = (max(d.mjd for d in tr.detections) - min(d.mjd for d in tr.detections)) / 365.25
    err_px = float(tr.extra.get("pos_err_px") or 0.0)
    err_mas = (err_px * pix * 1000.0 * math.sqrt(2.0) / span_yr) if span_yr > 0 else None
    out: dict[str, Any] = {"significance": round(sig, 2), "err_mas_per_year": round(err_mas, 1) if err_mas else None,
                           "baseline_years": round(span_yr, 2), "detected": sig >= TARGET_CONFIRM_SIGMA}
    if tgt.get("pmra") is not None and tgt.get("pmdec") is not None and err_mas:
        epmra, epmdec = float(tgt["pmra"]), float(tgt["pmdec"])
        diff = math.hypot(meas_pmra - epmra, meas_pmdec - epmdec)
        exp_pm = math.hypot(epmra, epmdec)
        out.update({
            "expected_pm_mas_per_year": round(exp_pm, 1),
            "measured_pm_mas_per_year": round(math.hypot(meas_pmra, meas_pmdec), 1),
            "expected_pa_deg": round(math.degrees(math.atan2(epmra, epmdec)) % 360.0, 1),
            "measured_pa_deg": round(math.degrees(math.atan2(meas_pmra, meas_pmdec)) % 360.0, 1),
            "difference_mas_per_year": round(diff, 1),
            "agrees": diff <= max(3.0 * err_mas, 0.15 * exp_pm),
        })
        out["confirmed"] = bool(out["detected"] and out["agrees"])
    return out


async def run_detection(
    tgt: dict[str, Any],
    search: str = "asteroids",
    fov_deg: float = 0.2,
    detectors: Optional[list[int]] = None,
    pass_index: Optional[int] = None,
    max_frames: int = 36,
    z_thresh: float = 5.0,
    vmag_lim: float = 21.0,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    if search == "asteroids":
        blink = await spherex_archive.build_blink(
            ra=tgt["ra"], dec=tgt["dec"], fov_deg=fov_deg, detectors=detectors, mode="pass",
            max_frames=max_frames, pass_index=pass_index,
            pmra=tgt.get("pmra"), pmdec=tgt.get("pmdec"), ref_epoch=tgt.get("ref_epoch") or 2000.0,
            keep_arrays=True,
        )
    else:
        blink = await spherex_archive.build_blink(
            ra=tgt["ra"], dec=tgt["dec"], fov_deg=fov_deg, detectors=detectors, mode="epoch",
            per_epoch=max(2, min(16, max_frames // 2)),  # deep stacks: faint targets need S/N
            pmra=tgt.get("pmra"), pmdec=tgt.get("pmdec"), ref_epoch=tgt.get("ref_epoch") or 2000.0,
            keep_arrays=True,
        )
    arrays = blink.pop("_arrays")
    masks = blink.pop("_masks")
    wcs = blink.pop("_wcs")
    grid = blink["grid"]
    frames = blink["frames"]
    mjds = [f["mjd"] for f in frames]
    dets = [tuple(f["detectors"]) for f in frames]
    pix = grid["pixscale_arcsec"]

    # Proper-motion search: always measure the requested target itself (mean of its predicted
    # pixel positions), even when it is too faint for the blind search.
    forced = None
    if search != "asteroids":
        tps = [f.get("target_px") for f in frames if f.get("target_px")]
        if tps:
            forced = [(float(np.mean([t[0] for t in tps])), float(np.mean([t[1] for t in tps])))]

    report("search")
    result = await asyncio.to_thread(mo.search, arrays, masks, mjds, dets, pix, search, z_thresh, forced)
    report("catalogs")

    # Reference catalogs (failures are reported, never fatal).
    notes: list[str] = []
    known_payload: dict[str, Any] = {"objects": [], "per_frame": [[] for _ in frames]}
    stars: list[dict[str, Any]] = []
    if search == "asteroids":
        try:
            known_payload = await known_objects_for_frames(grid["ra"], grid["dec"], grid["fov_deg"], mjds, vmag_lim)
            if known_payload.get("failed_queries"):
                notes.append(f"JPL SB Ident failed for {known_payload['failed_queries']} visit(s).")
        except Exception as exc:
            logger.warning(f"SB Ident failed: {exc}")
            notes.append("JPL SB Ident unavailable - known asteroids could not be checked.")
    else:
        for cat in ("gaia", "catwise"):
            try:
                c = await fetch_catalog(cat, grid["ra"], grid["dec"], grid["fov_deg"] * 0.75, limit=3000)
                for s in c["sources"]:
                    stars.append({**s, "catalog": c["label"], "ref_epoch": c["ref_epoch"]})
            except CatalogError as exc:
                notes.append(f"{cat} catalog unavailable: {exc}")

    # Known small bodies -> pixel positions per frame.
    known: dict[str, dict[str, Any]] = {}
    for fi, objs in enumerate(known_payload["per_frame"]):
        for o in objs:
            x, y = wcs.world_to_pixel_values(o["ra"], o["dec"])
            x, y = float(x), float(y)
            inside = -1 <= x <= grid["width"] and -1 <= y <= grid["height"]
            k = known.setdefault(o["name"], {"name": o["name"], "kind": o["kind"], "vmag": o["vmag"],
                                             "rate_ra": o["rate_ra"], "rate_dec": o["rate_dec"],
                                             "positions": [], "in_field": False, "recovered_by": None})
            k["positions"].append({"frame": fi, "x": round(x, 2), "y": round(y, 2), "ra": o["ra"], "dec": o["dec"]})
            k["in_field"] = k["in_field"] or inside

    candidates: list[dict[str, Any]] = []
    for tr in result["tracks"]:
        kind, score = mo.classify(tr, search, pix)
        dlist = []
        for d in tr.detections:
            ra_d, dec_d = wcs.pixel_to_world_values(d.x, d.y)
            dlist.append({"frame": d.frame, "mjd": d.mjd, "date": mjd_to_iso(d.mjd), "x": round(d.x, 2), "y": round(d.y, 2),
                          "ra": float(ra_d), "dec": float(dec_d), "z": round(d.z, 1), "flux": round(d.flux, 4),
                          "detectors": list(d.detectors), "on_star": d.on_star})
        mx, my = tr.position_at(tr.t0)
        ra_c, dec_c = wcs.pixel_to_world_values(mx, my)
        vx, vy = tr.rate_px_per_day
        speed_px_day = math.hypot(vx, vy)
        cand: dict[str, Any] = {
            "id": f"SPX-{uuid.uuid4().hex[:8].upper()}",
            "search": search,
            "class": kind,
            "score": score,
            "ra": float(ra_c), "dec": float(dec_c), "x": round(mx, 2), "y": round(my, 2),
            "t0_mjd": tr.t0, "t0_date": mjd_to_iso(tr.t0),
            "n_detections": len(tr.detections),
            "n_detectors": len({x for d in tr.detections for x in d.detectors}),
            "visits": tr.visits,
            "rms_px": round(tr.rms_px, 3),
            "rate_px_per_day": [round(vx, 4), round(vy, 4)],
            "rate_arcsec_per_hour": round(speed_px_day * pix / 24.0, 3),
            "rate_arcsec_per_year": round(speed_px_day * pix * 365.25, 3),
            "position_angle_deg": round(_pa_deg(vx, vy), 1) if speed_px_day > 0 else None,
            "mean_z": round(float(np.mean([d.z for d in tr.detections])), 1),
            "recurrence": tr.extra.get("recurrence"),
            "metrics": {k: v for k, v in tr.extra.items() if k not in ("pm_kind", "recurrence")},
            "detections": dlist,
            "match": None,
        }

        if search == "asteroids":
            best: Optional[tuple[float, dict[str, Any]]] = None
            for k in known.values():
                seps = []
                for d in tr.detections:
                    p = next((p for p in k["positions"] if p["frame"] == d.frame), None)
                    if p:
                        seps.append(math.hypot(p["x"] - d.x, p["y"] - d.y))
                if seps:
                    sep = float(np.median(seps))
                    if sep <= SSO_MATCH_PX and (best is None or sep < best[0]):
                        best = (sep, k)
            if best:
                sep, k = best
                pred_rate = math.hypot(k["rate_ra"], k["rate_dec"])
                meas_rate = cand["rate_arcsec_per_hour"]
                cand["match"] = {"type": "known_sso", "name": k["name"], "kind": k["kind"], "vmag": k["vmag"],
                                 "sep_arcsec": round(sep * pix, 1), "predicted_rate_arcsec_per_hour": round(pred_rate, 2)}
                # Position AND rate agreeing with a known object is decisive even if the track was
                # (mis)flagged as stationary: nothing static follows an asteroid's ephemeris.
                rate_ok = pred_rate > 0 and abs(meas_rate - pred_rate) <= 0.35 * pred_rate + 5.0
                strong_match = sep <= 2.0 and len(tr.detections) >= 3 and rate_ok and tr.rms_px <= MAX_MOVER_RMS
                if kind in ("moving_object", "low_confidence") or strong_match:
                    cand["class"] = "known_sso"
                    k["recovered_by"] = cand["id"]  # only genuine movers count as recovered
                else:
                    k.setdefault("coincident_with", cand["id"])
            elif kind == "moving_object":
                cand["class"] = "unknown_mover"
        else:
            year = mjd_to_year(tr.t0)
            meas_pmra = -vx * pix * 365.25 * 1000.0  # +x is west on the grid -> RA rate = -dx
            meas_pmdec = vy * pix * 365.25 * 1000.0
            meas_pm = math.hypot(meas_pmra, meas_pmdec)
            best_s: Optional[tuple[float, dict[str, Any], bool]] = None
            for s in stars:
                s_ra, s_dec = propagate(s["ra"], s["dec"], s["pmra"], s["pmdec"], s["ref_epoch"], year)
                sx, sy = wcs.world_to_pixel_values(s_ra, s_dec)
                sep = math.hypot(float(sx) - mx, float(sy) - my)
                dpm = math.hypot(s["pmra"] - meas_pmra, s["pmdec"] - meas_pmdec)
                consistent = dpm <= max(0.4 * meas_pm, 300.0)
                # Catalog positions of very fast movers are epoch-averaged (CatWISE even splits
                # them), so extrapolating a decade carries ~1.5 yr worth of motion as error.
                cat_pm_px_yr = math.hypot(s["pmra"], s["pmdec"]) / 1000.0 / pix
                radius = STAR_MATCH_PX + (1.5 * cat_pm_px_yr if consistent else 0.0)
                if sep > radius:
                    continue
                # Prefer catalog stars whose own motion agrees with the measured one.
                key = (0 if consistent else 1, sep)
                if best_s is None or key < (0 if best_s[2] else 1, best_s[0]):
                    best_s = (sep, s, consistent)
            cand["measured_pm_mas_per_year"] = [round(meas_pmra, 1), round(meas_pmdec, 1)]
            if best_s:
                sep, s, consistent = best_s
                pm = math.hypot(s["pmra"], s["pmdec"])
                cand["match"] = {"type": "star", "catalog": s["catalog"], "name": s["id"], "mag": s.get("mag"),
                                 "pm_mas_per_year": round(pm, 1), "sep_arcsec": round(sep * pix, 1),
                                 "pm_consistent": consistent}
                if kind == "proper_motion":
                    cand["class"] = "known_pm_star" if consistent and pm >= 30 else "pm_candidate"
            elif kind == "proper_motion":
                cand["class"] = "pm_candidate"
            if tr.extra.get("forced"):
                cand["is_target"] = True
                cand["target_name"] = tgt.get("name")
                cand["target_check"] = _target_check(tgt, tr, meas_pmra, meas_pmdec, pix)
                if tgt.get("pmra") is not None and tgt.get("pmdec") is not None:
                    cand["expected_pm_mas_per_year"] = [round(float(tgt["pmra"]), 1), round(float(tgt["pmdec"]), 1)]
        candidates.append(cand)

    order = {"unknown_mover": 0, "pm_candidate": 0, "target_measurement": 1, "known_sso": 1, "known_pm_star": 1, "moving_object": 1,
             "pm_unconfirmed": 2, "variable": 3, "stationary_transient": 3, "variable_or_residual": 4,
             "low_confidence": 5}
    candidates.sort(key=lambda c: (order.get(c["class"], 9), -c["score"]))

    known_list = [k for k in known.values() if k["in_field"]]
    run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
    by_class: dict[str, int] = {}
    for c in candidates:
        by_class[c["class"]] = by_class.get(c["class"], 0) + 1
    summary = {
        "search": search,
        "frames": len(frames),
        "searched_frames": result["searched_frames"],
        "n_detections": result["n_detections"],
        "n_single_frame": result["n_single_frame"],
        "noisy_frames": result.get("noisy_frames", 0),
        "sources_measured": result.get("sources_measured"),
        "astrometric_floor_px": result.get("astrometric_floor_px"),
        "n_candidates": len(candidates),
        "by_class": by_class,
        "known_in_field": len(known_list),
        "known_recovered": sum(1 for k in known_list if k["recovered_by"]),
        "known_bright_in_field": sum(1 for k in known_list if (k["vmag"] or 99) <= 18.0),
        "known_bright_recovered": sum(1 for k in known_list if k["recovered_by"] and (k["vmag"] or 99) <= 18.0),
        "pass_index": blink.get("pass_index"),
        "z_thresh": z_thresh,
        "notes": notes,
        "elapsed_s": round(time.perf_counter() - t0, 1),
    }
    params = {"target": tgt.get("name"), "ra": tgt["ra"], "dec": tgt["dec"], "search": search, "fov": fov_deg,
              "detectors": detectors, "pass_index": blink.get("pass_index"), "max_frames": max_frames,
              "z_thresh": z_thresh}
    report("save")
    try:
        await asyncio.to_thread(get_store().save_run, run_id, params, summary, candidates)
    except Exception as exc:  # storage problems must not lose the result
        logger.warning(f"Could not save detection run: {exc}")
        summary["notes"].append("Result could not be saved to the candidate database.")

    blink["target"].update({"name": tgt.get("name"), "resolver": tgt.get("source"), "note": tgt.get("note")})
    return {
        "run_id": run_id,
        "search": search,
        "params": params,
        "summary": summary,
        "candidates": candidates,
        "known_objects": known_list,
        "blink": blink,
        "is_simulated": False,
    }
