"""
OrbitScope - Moving-object search on real, co-registered SPHEREx frames
======================================================================
Works on frames that are already reprojected onto one common north-up TAN grid
(see ``SpherexArchive.build_blink``). Two search types:

``asteroids`` (individual exposures from ONE survey pass)
    A static-sky template is built per detector as the median of all exposures of that
    detector; a solar-system object is present in only the 2-4 exposures of a single visit,
    so it survives in ``frame - template`` while stars cancel. Positive residual peaks are
    linked into *tracklets* (same visit, consistent positions; the paired detectors
    D1/D4, D2/D5, D3/D6 expose simultaneously and confirm each other).
    Tracklets from different visits are then joined into longer tracks when their implied
    rate agrees with their own measured rates.

``proper_motion`` (one stack per survey pass, months apart)
    Each epoch is compared with the mean of the *other* epochs (leave-one-out). A star or
    brown dwarf with significant proper motion leaves a positive residual displaced along
    its motion; residuals at a fixed position across epochs indicate variability instead.

The noise model includes a term proportional to the template brightness: SPHEREx's linear
variable filters make every star's brightness differ slightly between exposures (each one
samples another wavelength), so residuals around bright stars are larger than pure noise.
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from scipy import ndimage

SMOOTH_SIGMA_PX = 1.0
# A Gaussian filter with sigma s shrinks white-noise std by 1 / (2 sqrt(pi) s).
SMOOTH_NOISE_FACTOR = 1.0 / (2.0 * math.sqrt(math.pi) * SMOOTH_SIGMA_PX)
TEMPLATE_NOISE_FRACTION = 0.15
EDGE_PX = 3
MAX_JOIN_RMS_PX = 1.5
# Asteroid search: SPHEREx visits are ~4 exposures within ~7 minutes; link only inside a visit
# (14 min window) so the search radius base + rate*dt stays small and chance pairs are rare.
VISIT_WINDOW_DAYS = 0.01
NOISY_FRAME_FACTOR = 3.0  # skip frames whose residual noise is > 3x the detector's median
MIN_MOVER_DETECTIONS = 3
MAX_MOVER_RMS_PX = 0.8
# Quality rules for an `unknown_mover` (validated on real SPHEREx fields, see docs/METHODOLOGY.md):
MIN_MOTION_SIGNIFICANCE = 5.0   # single visit: net displacement >= 5x the scatter around the line
CENTROID_ERR_FLOOR_PX = 0.15    # systematic centroid floor (PSF undersampling, reprojection)
CENTROID_ERR_COEFF = 1.5        # statistical centroid error ~ 1.5 / z px (same as the PM search)
MAX_RMS_OVER_ERR = 2.0          # scatter around the line <= 2x the expected centroid error
MAX_FLUX_RATIO = 3.0            # same detector, same visit: brightness may vary by <= 3x
BRIGHT_Z = 15.0                 # a source this bright must appear in most exposures of its visit
MIN_BRIGHT_COMPLETENESS = 0.5
EDGE_MOVER_PX = 8               # template is built from fewer exposures near the cutout edge


@dataclass
class Detection:
    frame: int
    mjd: float
    detectors: tuple[int, ...]
    x: float
    y: float
    z: float
    flux: float
    on_star: bool
    id: int = -1


@dataclass
class Track:
    detections: list[Detection]
    kind: str = "moving"
    rate_px_per_day: tuple[float, float] = (0.0, 0.0)
    rms_px: float = 0.0
    x0: float = 0.0
    y0: float = 0.0
    t0: float = 0.0
    visits: int = 1
    extra: dict[str, Any] = field(default_factory=dict)

    def position_at(self, mjd: float) -> tuple[float, float]:
        dt = mjd - self.t0
        return self.x0 + self.rate_px_per_day[0] * dt, self.y0 + self.rate_px_per_day[1] * dt


# --------------------------------------------------------------------------- detection
def robust_sigma(a: np.ndarray) -> float:
    v = a[np.isfinite(a)]
    if v.size < 10:
        return float("nan")
    med = np.median(v)
    return float(1.4826 * np.median(np.abs(v - med)))


def build_templates(
    arrays: list[np.ndarray], groups: list[Any], leave_one_out: bool = False
) -> list[Optional[np.ndarray]]:
    """Static-sky template for every frame.

    Frames sharing the same ``groups`` key (e.g. detector) are combined. With
    ``leave_one_out`` the template for frame i is the mean of the other frames of its
    group (used for few, deep epoch stacks); otherwise it is the median of the group.
    """
    out: list[Optional[np.ndarray]] = [None] * len(arrays)
    by_group: dict[Any, list[int]] = {}
    for i, g in enumerate(groups):
        by_group.setdefault(g, []).append(i)
    for idx in by_group.values():
        stack = np.stack([arrays[i] for i in idx]).astype(np.float64)
        if leave_one_out:
            if len(idx) < 2:
                continue
            with np.errstate(invalid="ignore"):
                total = np.nansum(stack, axis=0)
                count = np.sum(np.isfinite(stack), axis=0)
            for k, i in enumerate(idx):
                own = np.nan_to_num(stack[k])
                own_n = np.isfinite(stack[k]).astype(int)
                n = count - own_n
                with np.errstate(invalid="ignore", divide="ignore"):
                    out[i] = np.where(n > 0, (total - own) / n, np.nan)
        else:
            if len(idx) < 3:
                continue  # a median of < 3 frames would keep half of the moving object
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN columns
                med = np.nanmedian(stack, axis=0)
            for i in idx:
                out[i] = med
    return out


def detect_in_frame(
    frame_index: int,
    data: np.ndarray,
    template: np.ndarray,
    mask: Optional[np.ndarray],
    mjd: float,
    detectors: tuple[int, ...],
    z_thresh: float = 5.0,
    zmap_out: Optional[list[np.ndarray]] = None,
) -> tuple[list[Detection], dict[str, float]]:
    """Positive residual peaks of ``data - template`` above ``z_thresh`` (matched-filter S/N)."""
    resid = data.astype(np.float64) - template
    sigma = robust_sigma(resid)
    if not math.isfinite(sigma) or sigma <= 0:
        return [], {"sigma": float("nan")}
    tmpl_pos = np.clip(np.nan_to_num(template), 0.0, None)
    sigma_map = np.sqrt(sigma**2 + (TEMPLATE_NOISE_FRACTION * tmpl_pos) ** 2)
    bad = ~np.isfinite(resid)
    if mask is not None:
        bad |= mask.astype(bool)
    z = np.where(bad, 0.0, resid / sigma_map)
    zs = ndimage.gaussian_filter(z, SMOOTH_SIGMA_PX) / SMOOTH_NOISE_FACTOR

    h, w = data.shape
    peaks = (zs == ndimage.maximum_filter(zs, size=5)) & (zs > z_thresh)
    peaks[:EDGE_PX, :] = peaks[-EDGE_PX:, :] = False
    peaks[:, :EDGE_PX] = peaks[:, -EDGE_PX:] = False
    near_bad = ndimage.binary_dilation(bad, iterations=1)
    peaks &= ~near_bad

    if zmap_out is not None:
        zmap_out.append(zs)
    dets: list[Detection] = []
    r0 = np.nan_to_num(resid)
    for y, x in zip(*np.nonzero(peaks)):
        ys, xs = slice(y - 1, y + 2), slice(x - 1, x + 2)
        patch = np.clip(r0[ys, xs], 0.0, None)
        tot = patch.sum()
        if tot <= 0:
            continue
        yy, xx = np.mgrid[y - 1:y + 2, x - 1:x + 2]
        cx = float((patch * xx).sum() / tot)
        cy = float((patch * yy).sum() / tot)
        on_star = bool(tmpl_pos[y, x] > 10.0 * sigma)
        dets.append(Detection(frame_index, mjd, detectors, cx, cy, float(zs[y, x]), float(r0[ys, xs].sum()), on_star))
    return dets, {"sigma": sigma, "n_peaks": float(len(dets))}


# --------------------------------------------------------------------------- linking
class _UnionFind:
    def __init__(self, n: int) -> None:
        self.p = list(range(n))

    def find(self, a: int) -> int:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def fit_track(dets: list[Detection]) -> Track:
    """Weighted least-squares linear motion x(t), y(t)."""
    t = np.array([d.mjd for d in dets])
    x = np.array([d.x for d in dets])
    y = np.array([d.y for d in dets])
    wts = np.array([max(d.z, 1.0) for d in dets])
    t0 = float(np.average(t, weights=wts))
    if np.ptp(t) * 86400.0 < 1.0:  # simultaneous detections only (paired detectors)
        x0, y0 = float(np.average(x, weights=wts)), float(np.average(y, weights=wts))
        rms = float(np.sqrt(np.average((x - x0) ** 2 + (y - y0) ** 2, weights=wts)))
        return Track(dets, rate_px_per_day=(0.0, 0.0), rms_px=rms, x0=x0, y0=y0, t0=t0)
    a = np.vstack([np.ones_like(t), t - t0]).T
    sw = np.sqrt(wts)[:, None]
    cx, *_ = np.linalg.lstsq(a * sw, x * sw[:, 0], rcond=None)
    cy, *_ = np.linalg.lstsq(a * sw, y * sw[:, 0], rcond=None)
    rx = x - (cx[0] + cx[1] * (t - t0))
    ry = y - (cy[0] + cy[1] * (t - t0))
    rms = float(np.sqrt(np.average(rx**2 + ry**2, weights=wts)))
    return Track(dets, rate_px_per_day=(float(cx[1]), float(cy[1])), rms_px=rms, x0=float(cx[0]), y0=float(cy[0]), t0=t0)


def link_detections(
    dets: list[Detection], base_tol_px: float, max_rate_px_per_day: float, max_dt_days: float
) -> list[list[Detection]]:
    """Group detections in different frames whose separation is reachable at <= max_rate."""
    uf = _UnionFind(len(dets))
    order = sorted(range(len(dets)), key=lambda i: dets[i].mjd)
    for a_pos, i in enumerate(order):
        di = dets[i]
        for j in order[a_pos + 1:]:
            dj = dets[j]
            dt = dj.mjd - di.mjd
            if dt > max_dt_days:
                break
            if dj.frame == di.frame:
                continue
            if math.hypot(dj.x - di.x, dj.y - di.y) <= base_tol_px + max_rate_px_per_day * dt:
                uf.union(i, j)
    groups: dict[int, list[Detection]] = {}
    for i, d in enumerate(dets):
        groups.setdefault(uf.find(i), []).append(d)
    out = []
    for g in groups.values():
        best: dict[int, Detection] = {}
        for d in g:  # one detection per frame: keep the strongest
            if d.frame not in best or d.z > best[d.frame].z:
                best[d.frame] = d
        out.append(sorted(best.values(), key=lambda d: d.mjd))
    return out


def join_tracklets(tracks: list[Track], max_rate_px_per_day: float, max_gap_days: float = 3.0) -> list[Track]:
    """Join tracklets from different visits when their implied rate matches their own rates."""
    tracks = sorted(tracks, key=lambda t: t.t0)
    used = [False] * len(tracks)
    out: list[Track] = []
    for i, a in enumerate(tracks):
        if used[i]:
            continue
        chain = [a]
        used[i] = True
        cur = a
        for j in range(i + 1, len(tracks)):
            b = tracks[j]
            if used[j]:
                continue
            dt = b.t0 - cur.t0
            if dt <= 0.06 or dt > max_gap_days:
                continue
            vx, vy = (b.x0 - cur.x0) / dt, (b.y0 - cur.y0) / dt
            if math.hypot(vx, vy) > max_rate_px_per_day:
                continue
            ok = True
            for t in (cur, b):
                span = max(d.mjd for d in t.detections) - min(d.mjd for d in t.detections)
                if span * 24 * 60 < 3:  # rate of this tracklet not measurable
                    continue
                tol = 3.0 * (0.5 / span) + 0.15 * math.hypot(vx, vy)  # ~0.35 px centroid noise
                if math.hypot(t.rate_px_per_day[0] - vx, t.rate_px_per_day[1] - vy) > tol:
                    ok = False
            if not ok:
                continue
            trial = fit_track([d for tr in chain + [b] for d in tr.detections])
            if trial.rms_px <= MAX_JOIN_RMS_PX:  # never accept a merge that breaks straight-line motion
                chain.append(b)
                used[j] = True
                cur = b
        if len(chain) == 1:
            out.append(a)
        else:
            merged = fit_track([d for t in chain for d in t.detections])
            merged.visits = len(chain)
            out.append(merged)
    return out


# --------------------------------------------------------------------------- proper motion
PM_MIN_SNR = 10.0
FORCED_MIN_Z = 3.0        # forced (target) measurement: mean-image peak needed near the target
FORCED_SEARCH_PX = 3.0    # how far from the expected target position that peak may be
PM_SIGNIFICANCE = 5.0
PM_MIN_SHIFT_PX = 0.25
PM_MAX_RMS_FACTOR = 3.0   # epochs may scatter around the linear fit by at most 3x the centroid error
PM_MIN_RMS_PX = 0.3
VAR_MIN_RATIO = 1.6


def refine_centroid(img: np.ndarray, x0: float, y0: float, iters: int = 4, sigma: float = 1.5) -> Optional[tuple[float, float]]:
    """Gaussian-weighted centroid, re-centred each iteration (removes the pull towards the
    initial integer pixel that a fixed window has)."""
    h, w = img.shape
    x, y = float(x0), float(y0)
    for _ in range(iters):
        xi, yi = int(round(x)), int(round(y))
        if xi < 3 or yi < 3 or xi > w - 4 or yi > h - 4:
            return None
        yy, xx = np.mgrid[yi - 3:yi + 4, xi - 3:xi + 4]
        patch = np.clip(img[yi - 3:yi + 4, xi - 3:xi + 4], 0.0, None)
        wgt = patch * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma**2))
        tot = wgt.sum()
        if tot <= 0:
            return None
        nx, ny = float((wgt * xx).sum() / tot), float((wgt * yy).sum() / tot)
        if abs(nx - x) < 1e-3 and abs(ny - y) < 1e-3:
            x, y = nx, ny
            break
        x, y = nx, ny
    return x, y


def _background(img: np.ndarray) -> np.ndarray:
    filled = np.where(np.isfinite(img), img, np.nanmedian(img))
    return ndimage.median_filter(filled, size=9)


def search_proper_motion(
    arrays: list[np.ndarray],
    masks: list[Optional[np.ndarray]],
    mjds: list[float],
    detectors: list[tuple[int, ...]],
    forced: Optional[list[tuple[float, float]]] = None,
) -> dict[str, Any]:
    """Astrometric proper-motion and variability search on a few deep epoch stacks.

    Instead of image differences (which confuse brightness changes with motion), every
    well-detected, isolated, unsaturated source is centroided in every epoch. Frame-wide
    registration offsets are removed using all sources, the per-source positional noise
    is estimated from the (mostly static) star population, and sources whose displacement
    is significant are reported. Brightness changes are reported separately as variables.

    ``forced`` lists pixel positions (mean over the epochs) of requested targets. They are
    measured even when fainter than ``PM_MIN_SNR`` (e.g. WISE 0855 at 4.6 um), and always
    reported, with their significance, so a non-detection is visible instead of silent. The
    centroid starts from the target's *mean* position, never from a catalog prediction per
    epoch, so the measured motion does not inherit the catalog's proper motion.
    """
    n_ep = len(arrays)
    if n_ep < 2:
        return {"tracks": [], "n_detections": 0, "n_single_frame": 0, "frame_stats": [], "searched_frames": 0}
    stack = np.stack([a.astype(np.float64) for a in arrays])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean_img = np.nanmean(stack, axis=0)
    bad = ~np.isfinite(mean_img)
    for m in masks:
        if m is not None:
            bad |= m.astype(bool)
    sub = mean_img - _background(mean_img)
    sigma = robust_sigma(sub)
    if not math.isfinite(sigma) or sigma <= 0:
        return {"tracks": [], "n_detections": 0, "n_single_frame": 0, "frame_stats": [], "searched_frames": 0}
    zs = ndimage.gaussian_filter(np.where(bad, 0.0, sub / sigma), SMOOTH_SIGMA_PX) / SMOOTH_NOISE_FACTOR
    h, w = mean_img.shape
    peaks = (zs == ndimage.maximum_filter(zs, size=5)) & (zs > PM_MIN_SNR)
    margin = 4
    peaks[:margin, :] = peaks[-margin:, :] = False
    peaks[:, :margin] = peaks[:, -margin:] = False
    peaks &= ~ndimage.binary_dilation(bad, iterations=2)
    ys, xs = np.nonzero(peaks)
    pts = np.stack([xs, ys], axis=1) if len(xs) else np.zeros((0, 2))
    # isolation: drop sources with a neighbour within 4 px (blends bias centroids)
    keep = []
    for i, (x, y) in enumerate(pts):
        d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
        if np.sum(d < 4.0) == 1:
            keep.append(i)
    pts = pts[keep]

    forced_idx: set[int] = set()
    for fx, fy in forced or []:
        if not (margin <= fx < w - margin and margin <= fy < h - margin):
            continue
        r = int(math.ceil(FORCED_SEARCH_PX))
        x0, x1 = max(0, int(fx) - r), min(w, int(fx) + r + 2)
        y0, y1 = max(0, int(fy) - r), min(h, int(fy) + r + 2)
        win = zs[y0:y1, x0:x1]
        yy, xx = np.mgrid[y0:y1, x0:x1]
        win = np.where(np.hypot(xx - fx, yy - fy) <= FORCED_SEARCH_PX, win, -np.inf)
        iy, ix = np.unravel_index(int(np.argmax(win)), win.shape)
        if not np.isfinite(win[iy, ix]) or win[iy, ix] < FORCED_MIN_Z:
            continue
        px, py = x0 + ix, y0 + iy
        near = np.hypot(pts[:, 0] - px, pts[:, 1] - py) if len(pts) else np.zeros(0)
        if len(near) and near.min() <= 2.0:
            forced_idx.add(int(np.argmin(near)))
        else:
            pts = np.vstack([pts, [px, py]]) if len(pts) else np.array([[px, py]], dtype=float)
            forced_idx.add(len(pts) - 1)

    subs = []
    ep_sigma = []
    for a in arrays:
        s_ = a.astype(np.float64) - _background(a.astype(np.float64))
        subs.append(np.nan_to_num(s_))
        ep_sigma.append(robust_sigma(s_))

    cx = np.full((len(pts), n_ep), np.nan)
    cy = np.full((len(pts), n_ep), np.nan)
    fl = np.full((len(pts), n_ep), np.nan)
    sn = np.full((len(pts), n_ep), np.nan)
    for k, (x, y) in enumerate(pts):
        x, y = int(x), int(y)
        for e in range(n_ep):
            c = refine_centroid(subs[e], x, y)
            if c is None:
                continue
            cx[k, e], cy[k, e] = c
            f3 = float(subs[e][y - 1:y + 2, x - 1:x + 2].sum())
            fl[k, e] = f3
            sn[k, e] = f3 / (ep_sigma[e] * 3.0) if ep_sigma[e] > 0 else np.nan

    # Remove frame-wide registration offsets (median over all sources, per epoch).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mx = np.nanmean(cx, axis=1, keepdims=True)
        my = np.nanmean(cy, axis=1, keepdims=True)
        offx = np.nanmedian(cx - mx, axis=0, keepdims=True)
        offy = np.nanmedian(cy - my, axis=0, keepdims=True)
    cx = cx - np.nan_to_num(offx)
    cy = cy - np.nan_to_num(offy)

    # Positional noise floor from bright sources (most stars do not move measurably).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        snr_mean = np.nanmean(sn, axis=1)
        dev = np.concatenate([(cx - np.nanmean(cx, 1, keepdims=True))[snr_mean > 30].ravel(),
                              (cy - np.nanmean(cy, 1, keepdims=True))[snr_mean > 30].ravel()])
    dev = dev[np.isfinite(dev)]
    floor = float(1.4826 * np.median(np.abs(dev))) if dev.size >= 10 else 0.05
    floor = max(floor, 0.03)

    tracks: list[Track] = []
    t_yr = (np.array(mjds) - mjds[0]) / 365.25
    for k in range(len(pts)):
        ok = np.isfinite(cx[k]) & np.isfinite(sn[k]) & (sn[k] > 3)
        if ok.sum() < 2:
            continue
        snr_k = float(np.nanmean(sn[k][ok]))
        # Centroid error: astrometric floor (from the static stars) plus an S/N term. The 1.5/SNR
        # coefficient is empirical: SPHEREx's PSF is undersampled and changes with wavelength,
        # so faint centroids scatter ~3x more than the ideal FWHM/(2.35 SNR).
        err = math.hypot(floor, 1.5 / max(snr_k, 1.0))
        dets = [Detection(e, mjds[e], detectors[e], float(cx[k, e]), float(cy[k, e]), float(sn[k, e]),
                          float(fl[k, e]), False) for e in range(n_ep) if ok[e]]
        tr = fit_track(dets)
        span_days = (max(d.mjd for d in dets) - min(d.mjd for d in dets))
        shift = math.hypot(*tr.rate_px_per_day) * span_days
        sig = shift / (err * math.sqrt(2.0))
        fpos = fl[k][ok]
        ratio = float(np.nanmax(fpos) / np.nanmin(fpos)) if np.nanmin(fpos) > 0 else float("inf")
        tr.extra.update({"pm_sigma": round(sig, 2), "shift_px": round(shift, 3), "pos_err_px": round(err, 3),
                         "flux_ratio": round(ratio, 2) if math.isfinite(ratio) else None, "snr": round(snr_k, 1)})
        if k in forced_idx:
            tr.extra["forced"] = True
        # Real proper motion is linear over a few years. Three or more epochs that scatter far
        # more than their centroid error around the fitted line are a blend, a PSF/edge effect
        # or a variable neighbour, not a moving star.
        linear = len(dets) < 3 or tr.rms_px <= max(PM_MAX_RMS_FACTOR * err, PM_MIN_RMS_PX)
        tr.extra["linear"] = linear
        if sig >= PM_SIGNIFICANCE and shift >= PM_MIN_SHIFT_PX and linear:
            tr.extra["pm_kind"] = "pm"
            tracks.append(tr)
        elif ratio >= VAR_MIN_RATIO and float(np.nanmin(sn[k][ok])) >= 8.0 and k not in forced_idx:
            tr.extra["pm_kind"] = "var"
            tracks.append(tr)
        elif k in forced_idx:
            tr.extra["pm_kind"] = "target"  # measured, but the shift is not significant
            tracks.append(tr)
    return {
        "tracks": tracks,
        "n_detections": int(len(pts)),
        "n_single_frame": 0,
        "frame_stats": [{"frame": e, "searched": True, "sigma": ep_sigma[e]} for e in range(n_ep)],
        "searched_frames": n_ep,
        "astrometric_floor_px": round(floor, 3),
        "sources_measured": int(len(pts)),
    }


# --------------------------------------------------------------------------- search
def search(
    arrays: list[np.ndarray],
    masks: list[Optional[np.ndarray]],
    mjds: list[float],
    detectors: list[tuple[int, ...]],
    pixscale_arcsec: float,
    mode: str = "asteroids",
    z_thresh: float = 5.0,
    forced: Optional[list[tuple[float, float]]] = None,
) -> dict[str, Any]:
    """Run the full search. Returns tracks (unclassified) plus per-frame statistics."""
    if mode != "asteroids":
        return search_proper_motion(arrays, masks, mjds, detectors, forced=forced)
    if mode == "asteroids":
        templates = build_templates(arrays, [d for d in detectors])
        max_rate = 300.0 * 24.0 / pixscale_arcsec  # 300"/h
        base_tol, max_dt = 1.5, VISIT_WINDOW_DAYS
    else:
        templates = build_templates(arrays, [0] * len(arrays), leave_one_out=True)
        base_tol, max_rate, max_dt = 1.5, (15.0 / pixscale_arcsec) / 365.25, 2000.0  # up to 15"/yr
    min_frames = 2

    # Residual noise per frame first, so unusually noisy exposures can be skipped.
    sigmas: list[float] = []
    for a, tmpl in zip(arrays, templates):
        sigmas.append(robust_sigma(a - tmpl) if tmpl is not None else float("nan"))
    median_sigma: dict[Any, float] = {}
    for key in set(detectors):
        vals = [s for s, d in zip(sigmas, detectors) if d == key and math.isfinite(s)]
        if vals:
            median_sigma[key] = float(np.median(vals))

    all_dets: list[Detection] = []
    frame_stats = []
    zmaps: dict[int, np.ndarray] = {}
    for i, (a, m, t, dets_i) in enumerate(zip(arrays, masks, mjds, detectors)):
        tmpl = templates[i]
        if tmpl is None:
            frame_stats.append({"frame": i, "searched": False, "reason": "too_few_frames"})
            continue
        ref = median_sigma.get(dets_i)
        if ref and math.isfinite(sigmas[i]) and sigmas[i] > NOISY_FRAME_FACTOR * ref:
            frame_stats.append({"frame": i, "searched": False, "reason": "noisy", "sigma": sigmas[i]})
            continue
        zbuf: list[np.ndarray] = []
        found, st = detect_in_frame(i, a, tmpl, m, t, dets_i, z_thresh=z_thresh, zmap_out=zbuf)
        if zbuf:
            zmaps[i] = zbuf[0]
        all_dets.extend(found)
        frame_stats.append({"frame": i, "searched": True, **st})
    for k, d in enumerate(all_dets):
        d.id = k

    groups = link_detections(all_dets, base_tol, max_rate, max_dt)
    tracks = []
    singles = 0
    for g in groups:
        if len(g) < min_frames:
            singles += 1
            continue
        tr = fit_track(g)
        # Asteroids: a fitted rate above the limit means a chance pairing. (Not applied to proper
        # motion, where the positive lobe of a residual dipole exaggerates the shift.)
        if mode == "asteroids" and math.hypot(*tr.rate_px_per_day) > max_rate * 1.2:
            singles += len(g)
            continue
        tracks.append(tr)
    if mode == "asteroids":
        tracks = join_tracklets(tracks, max_rate)
        searched = {s_["frame"] for s_ in frame_stats if s_.get("searched")}
        shape = arrays[0].shape if arrays else (0, 0)
        for tr in tracks:
            tr.extra["recurrence"] = recurrence(tr, zmaps, mjds)
            tr.extra.update(track_quality(tr, mjds, detectors, searched, shape))
    return {
        "tracks": tracks,
        "n_detections": len(all_dets),
        "n_single_frame": singles,
        "frame_stats": frame_stats,
        "searched_frames": sum(1 for s in frame_stats if s.get("searched")),
        "noisy_frames": sum(1 for s in frame_stats if s.get("reason") == "noisy"),
    }


def track_quality(
    track: Track, mjds: list[float], detectors: list[tuple[int, ...]], searched: set[int], shape: tuple[int, ...]
) -> dict[str, Any]:
    """Consistency checks that separate real movers from residual noise (see MIN_MOTION_SIGNIFICANCE).

    - motion significance: displacement within one visit compared with the scatter of the points;
      residuals at a fixed spot "zig-zag" around it instead of moving steadily;
    - line scatter vs. the expected centroid error for the track's S/N;
    - brightness consistency within a detector (an asteroid does not jump 10x in two minutes);
    - completeness: a bright source must show up in most exposures of its visit in that detector;
    - distance from the cutout edge.
    """
    dets = track.detections
    zs = np.array([d.z for d in dets])
    exp_err = max(CENTROID_ERR_FLOOR_PX, float(np.median(CENTROID_ERR_COEFF / np.maximum(zs, 1.0))))
    first, last = min(dets, key=lambda d: d.mjd), max(dets, key=lambda d: d.mjd)
    disp = math.hypot(last.x - first.x, last.y - first.y)
    motion_sig = disp / max(track.rms_px, 0.1)
    flux_ratio = 1.0
    by_det: dict[int, list[Detection]] = {}
    for d in dets:
        for k in d.detectors:
            by_det.setdefault(k, []).append(d)
    completeness = 1.0
    for k, lst in by_det.items():
        z_k = [d.z for d in lst]
        if len(z_k) >= 2:
            flux_ratio = max(flux_ratio, max(z_k) / max(min(z_k), 1e-3))
        if max(z_k) >= BRIGHT_Z:
            # exposures of this detector in the same visit(s) as the track's detections
            visits = {round(d.mjd / VISIT_WINDOW_DAYS) for d in lst}
            avail = [i for i in searched if k in detectors[i]
                     and any(abs(mjds[i] - d.mjd) <= VISIT_WINDOW_DAYS for d in lst)]
            seen = {d.frame for d in lst}
            if avail and visits:
                completeness = min(completeness, len(seen & set(avail)) / len(avail))
    h, w = shape[:2] if len(shape) >= 2 else (0, 0)
    edge = min(min(d.x, d.y, w - 1 - d.x, h - 1 - d.y) for d in dets) if w and h else 99.0
    return {
        "motion_sigma": round(motion_sig, 2),
        "expected_centroid_err_px": round(exp_err, 3),
        "flux_ratio": round(flux_ratio, 2),
        "bright_completeness": round(completeness, 2),
        "edge_px": round(float(edge), 1),
    }


def mover_quality_ok(track: Track) -> tuple[bool, list[str]]:
    """Apply the track_quality() rules. Returns (ok, reasons for rejection)."""
    ex = track.extra
    why = []
    if track.visits <= 1 and ex.get("motion_sigma", 99) < MIN_MOTION_SIGNIFICANCE:
        why.append("no_steady_motion")
    if track.rms_px > MAX_RMS_OVER_ERR * ex.get("expected_centroid_err_px", 1.0):
        why.append("scatter")
    if ex.get("flux_ratio", 1.0) > MAX_FLUX_RATIO:
        why.append("flux_jump")
    if ex.get("bright_completeness", 1.0) < MIN_BRIGHT_COMPLETENESS:
        why.append("missing_in_visit")
    if ex.get("edge_px", 99) < EDGE_MOVER_PX:
        why.append("edge")
    return (not why), why


RECURRENCE_Z = 4.0
RECURRENCE_GAP_DAYS = 0.05  # only exposures from clearly different visits count


def recurrence(track: Track, zmaps: dict[int, np.ndarray], mjds: list[float]) -> int:
    """How many exposures from OTHER visits show a residual at this track's positions.

    A solar-system object is gone hours later; a source that keeps reappearing at the same
    spot is a variable star, detector persistence or another stationary artifact.
    """
    own_frames = {d.frame for d in track.detections}
    t_lo = min(d.mjd for d in track.detections) - RECURRENCE_GAP_DAYS
    t_hi = max(d.mjd for d in track.detections) + RECURRENCE_GAP_DAYS
    spots = {(int(round(d.y)), int(round(d.x))) for d in track.detections}
    # The recurring residual must be comparable to the track itself: a 300-sigma asteroid is not
    # "recurring" because of a 4-sigma noise bump at the same spot hours later.
    level = max(RECURRENCE_Z, 0.3 * float(np.mean([d.z for d in track.detections])))
    hits = 0
    for fi, z in zmaps.items():
        if fi in own_frames or t_lo <= mjds[fi] <= t_hi:
            continue
        h, w = z.shape
        for y, x in spots:
            if 1 <= y < h - 1 and 1 <= x < w - 1 and float(z[y - 1:y + 2, x - 1:x + 2].max()) > level:
                hits += 1
                break
    return hits


def z_floor(n: int) -> float:
    """Required mean S/N for an unknown mover.

    With ~500-800 single detections per pass, chance alignments of three faint (z~6) residuals
    into a straight line are common; real faint movers show up in all four exposures of a visit.
    So three-point tracks must be clearly detected, four-point tracks can be fainter.
    """
    if n <= 3:
        return 8.0
    return 5.5 if n == 4 else 5.0


def classify(
    track: Track,
    mode: str,
    pixscale_arcsec: float,
) -> tuple[str, float]:
    """Return (class, score 0..1). Matching to catalogs is done by the caller."""
    n = len(track.detections)
    frames_dets = {d for det in track.detections for d in det.detectors}
    on_star = sum(d.on_star for d in track.detections) / n
    mean_z = float(np.mean([d.z for d in track.detections]))
    speed = math.hypot(*track.rate_px_per_day)
    span = max(d.mjd for d in track.detections) - min(d.mjd for d in track.detections)
    motion = speed * span

    if mode == "asteroids":
        times = {round(d.mjd * 86400.0 / 10.0) for d in track.detections}  # distinct epochs (10 s bins)
        quality_ok, reasons = mover_quality_ok(track)
        if reasons:
            track.extra["rejected_because"] = reasons
        strong = (
            n >= MIN_MOVER_DETECTIONS
            and len(times) >= 2
            and track.rms_px <= MAX_MOVER_RMS_PX
            and mean_z >= z_floor(n)
            and quality_ok
        )
        # Spread over > 0.1 day but moved < 2 px: nothing in the solar system is that slow
        # (even a 3"/h TNO moves ~5 px in 0.4 day) -> fixed-position source.
        parked = span > 0.1 and motion < 2.0
        if on_star >= 0.5:
            kind = "variable_or_residual"
        elif track.extra.get("recurrence", 0) >= 2 or parked:
            kind = "stationary_transient"
        elif strong:
            kind = "moving_object"
        else:
            kind = "low_confidence"
        score = min(1.0, 0.15 * n + 0.04 * mean_z + 0.1 * (len(frames_dets) - 1) + 0.15 * (track.visits - 1))
        if kind != "moving_object":
            score *= 0.4
    else:
        pk = track.extra.get("pm_kind")
        if pk == "pm":
            kind = "proper_motion"
            score = min(1.0, 0.1 * float(track.extra.get("pm_sigma", 0)) + 0.1 * n)
        elif pk == "target":
            kind = "target_measurement"
            score = 0.5
        elif pk == "var":
            kind = "variable"
            score = min(1.0, 0.2 * float(track.extra.get("flux_ratio") or 1.0))
        else:
            kind = "low_confidence"
            score = 0.1
    return kind, round(score, 3)
