"""
OrbitScope - SPHEREx Archive Service (real data)
=================================================
Retrieves real NASA SPHEREx Level-2 spectral images from NASA/IPAC IRSA and turns
them into a time series ("blink" frames) centred on a sky position:

1. ``spherex.obscore`` TAP query -> every SPHEREx frame whose footprint covers the point.
   Collections are matched with ``LIKE 'spherex%'`` so new data releases appear automatically.
2. IRSA datalink -> direct Level-2 FITS URL for each selected frame (cached on disk).
3. IBE cutout service -> small FITS cutout (IMAGE, FLAGS, VARIANCE, ZODI, WCS-WAVE),
   stored on disk without the large PSF cube.
4. Frames are zodi- and sky-subtracted, flag-masked, reprojected onto a common
   north-up TAN grid centred on the target, and inverse-variance co-added per epoch.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx
import numpy as np
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS, FITSFixedWarning
from cachetools import TTLCache
from scipy import ndimage
from scipy.ndimage import map_coordinates

from app.core.config import settings
from app.core.logging_config import get_logger
from app.core.progress import gather_with_progress, report

import warnings
from astropy import log as astropy_log

warnings.filterwarnings("ignore", category=FITSFixedWarning)
astropy_log.setLevel("ERROR")

logger = get_logger(__name__)

IRSA_ROOT = "https://irsa.ipac.caltech.edu"
DATALINK_URL = f"{IRSA_ROOT}/datalink/links/spherex"

# Approximate wavelength coverage of the six SPHEREx detector arrays (micron).
DETECTOR_BANDS: dict[int, tuple[float, float]] = {
    1: (0.75, 1.11),
    2: (1.10, 1.65),
    3: (1.63, 2.42),
    4: (2.42, 3.82),
    5: (3.82, 4.42),
    6: (4.41, 5.01),
}

# FLAGS bits masked before co-adding (bit numbers are read from the FITS header when present).
MASKED_FLAG_NAMES = ("TRANSIENT", "NONFUNC", "MISSING_DATA", "HOT", "COLD", "OUTLIER")
DEFAULT_FLAG_BITS: dict[str, int] = {
    "TRANSIENT": 0, "OVERFLOW": 1, "SUR_ERROR": 2, "PHANTOM": 4, "REFERENCE": 5,
    "NONFUNC": 6, "DICHROIC": 7, "MISSING_DATA": 9, "HOT": 10, "COLD": 11,
    "FULLSAMPLE": 12, "PHANMISS": 14, "NONLINEAR": 15, "PERSIST": 17, "OUTLIER": 19, "SOURCE": 21,
}
REPORTED_FLAGS = ("OVERFLOW", "SUR_ERROR", "NONLINEAR", "PERSIST", "OUTLIER", "TRANSIENT", "HOT", "NONFUNC", "DICHROIC")

NATIVE_PIXSCALE_ARCSEC = 6.15
EPOCH_GAP_DAYS = 30.0
MAX_DOWNLOADS = 48
DOWNLOAD_CONCURRENCY = 10   # parallel IRSA cutout downloads (IRSA copes well; 503s are retried)
WITHDRAWN_MIN_MISSES = 10   # a collection counts as withdrawn after >= 10 missing files ...
WITHDRAWN_FRACTION = 0.8    # ... that are >= 80 % of all files looked up in it
COVERAGE_TTL_S = 6 * 3600   # re-ask IRSA which frames cover a position at least every 6 h (new releases)


class SpherexError(Exception):
    """Raised for user-facing archive errors (no coverage, upstream failure)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class FrameRecord:
    obs_id: str
    collection: str
    detector: int
    mjd: float
    em_min_um: float
    em_max_um: float

    @property
    def key(self) -> str:
        return f"{self.collection}:{self.obs_id}:D{self.detector}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "obs_id": self.obs_id,
            "collection": self.collection,
            "detector": self.detector,
            "mjd": self.mjd,
            "date": mjd_to_iso(self.mjd),
            "wavelength_um": [round(self.em_min_um, 3), round(self.em_max_um, 3)],
        }


@dataclass
class Cutout:
    record: FrameRecord
    url: str
    image: np.ndarray
    flags: np.ndarray
    variance: np.ndarray
    wcs: WCS
    mjd: float
    wavelength_um: Optional[float]
    flag_bits: dict[str, int] = field(default_factory=dict)
    wave_wcs: Optional[WCS] = None  # per-pixel wavelength (LVF), from the WCS-WAVE lookup table

    def wavelength_at(self, x: float, y: float) -> Optional[float]:
        if self.wave_wcs is None:
            return self.wavelength_um
        try:
            lam, _ = self.wave_wcs.pixel_to_world_values(x, y)
            return float(lam) if np.isfinite(lam) else None
        except Exception:
            return self.wavelength_um


def mjd_to_iso(mjd: float) -> str:
    return Time(mjd, format="mjd").to_datetime().strftime("%Y-%m-%dT%H:%M:%SZ")


def mjd_to_year(mjd: float) -> float:
    return float(Time(mjd, format="mjd").jyear)


def propagate(ra: float, dec: float, pmra: float, pmdec: float, ref_epoch: float, epoch: float) -> tuple[float, float]:
    """Linear proper-motion propagation (pm in mas/yr, pmra includes cos(dec))."""
    dt = epoch - ref_epoch
    dec_new = dec + pmdec * dt / 3.6e6
    cosd = max(math.cos(math.radians(dec)), 1e-6)
    ra_new = (ra + pmra * dt / 3.6e6 / cosd) % 360.0
    return ra_new, dec_new


def make_target_wcs(ra: float, dec: float, size_px: int, pixscale_arcsec: float) -> WCS:
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(size_px + 1) / 2.0, (size_px + 1) / 2.0]
    w.wcs.cdelt = [-pixscale_arcsec / 3600.0, pixscale_arcsec / 3600.0]
    return w


class SpherexArchive:
    """Real SPHEREx data access + blink-frame construction."""

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.tap_url = settings.IRSA_TAP_URL
        self.cache_dir = Path(cache_dir or settings.SPHEREX_CACHE_DIR)
        (self.cache_dir / "cutouts").mkdir(parents=True, exist_ok=True)
        self._urls_path = self.cache_dir / "datalink_urls.json"
        self._urls: dict[str, str] = self._load_json(self._urls_path)
        self._coverage_cache: TTLCache = TTLCache(maxsize=256, ttl=6 * 3600)
        self._sem = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)
        self._locks: dict[str, asyncio.Lock] = {}
        self._new_downloads = 0
        self._withdrawn_cache: Optional[tuple[int, set[str]]] = None

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _load_json(path: Path) -> dict[str, str]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_urls(self) -> None:
        try:
            self._urls_path.write_text(json.dumps(self._urls), encoding="utf-8")
        except Exception as exc:  # cache write failures are non-fatal
            logger.warning(f"Could not persist datalink cache: {exc}")

    def available(self, rec: "FrameRecord") -> bool:
        """False for frames whose Level-2 file is known to be missing from the archive, and for
        collections where most looked-up files are missing (e.g. a quick release superseded by a
        data release: IRSA keeps the metadata but withdraws the files)."""
        if self._urls.get(rec.key, None) == "":
            return False
        return rec.collection not in self._withdrawn_collections()

    def _withdrawn_collections(self) -> set[str]:
        if self._withdrawn_cache is not None and self._withdrawn_cache[0] == len(self._urls):
            return self._withdrawn_cache[1]
        seen: dict[str, list[int]] = {}
        for k, v in self._urls.items():
            col = k.split(":", 1)[0]
            c = seen.setdefault(col, [0, 0])
            c[0 if v else 1] += 1
        out = {col for col, (ok, miss) in seen.items() if miss >= WITHDRAWN_MIN_MISSES and miss >= WITHDRAWN_FRACTION * (ok + miss)}
        self._withdrawn_cache = (len(self._urls), out)
        return out

    # ------------------------------------------------------------ cache upkeep
    def cache_stats(self) -> dict[str, Any]:
        files = list((self.cache_dir / "cutouts").glob("*.fits"))
        size = sum(f.stat().st_size for f in files)
        return {"cutouts": len(files), "size_mb": round(size / 1e6, 1), "limit_mb": settings.SPHEREX_CACHE_MAX_MB,
                "path": str(self.cache_dir)}

    def prune_cache(self, max_mb: Optional[float] = None) -> dict[str, Any]:
        """Delete the least recently used cutouts until the cache fits in ``max_mb``."""
        limit = (max_mb if max_mb is not None else settings.SPHEREX_CACHE_MAX_MB) * 1e6
        files = []
        for f in (self.cache_dir / "cutouts").glob("*.fits"):
            try:
                st = f.stat()
                files.append((max(st.st_atime, st.st_mtime), st.st_size, f))
            except OSError:
                continue
        total = sum(s for _, s, _ in files)
        removed = 0
        for _, size, f in sorted(files):
            if total <= limit:
                break
            try:
                f.unlink()
                f.with_suffix(".url").unlink(missing_ok=True)
                total -= size
                removed += 1
            except OSError:
                continue
        if removed:
            logger.info(f"Pruned {removed} cached cutouts; cache now {total / 1e6:.0f} MB")
        return {"removed": removed, "size_mb": round(total / 1e6, 1)}

    def _maybe_prune(self) -> None:
        self._new_downloads += 1
        if self._new_downloads % 50 == 0:
            asyncio.get_running_loop().run_in_executor(None, self.prune_cache)

    # --------------------------------------------------------------- coverage
    async def query_frames(self, ra: float, dec: float) -> list[FrameRecord]:
        """All SPHEREx L2 frames whose footprint contains (ra, dec), sorted by time."""
        key = f"{ra:.3f}:{dec:.3f}"
        if key in self._coverage_cache:
            return self._coverage_cache[key]
        report("coverage")

        disk = self.cache_dir / f"coverage_{hashlib.md5(key.encode()).hexdigest()[:16]}.json"
        rows = None
        if disk.exists() and time.time() - disk.stat().st_mtime < COVERAGE_TTL_S:
            rows = json.loads(disk.read_text(encoding="utf-8"))
            # A cached list that still names a withdrawn release predates IRSA's reprocessing
            # (e.g. QR2 -> DR1): ask again, the current archive lists the new frames.
            withdrawn = self._withdrawn_collections()
            if withdrawn and any(r.get("obs_collection") in withdrawn for r in rows):
                rows = None
        if rows is None:
            adql = (
                "SELECT obs_collection, obs_id, t_min, t_max, em_min, em_max, energy_bandpassname "
                "FROM spherex.obscore "
                f"WHERE CONTAINS(POINT('ICRS', {ra:.6f}, {dec:.6f}), s_region) = 1"
            )
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    resp = await client.post(
                        self.tap_url, data={"LANG": "ADQL", "FORMAT": "csv", "QUERY": adql}
                    )
            except httpx.HTTPError as exc:
                raise SpherexError("upstream", f"IRSA TAP request failed: {exc}") from exc
            if resp.status_code != 200 or "QUERY_STATUS" in resp.text[:2000]:
                raise SpherexError("upstream", f"IRSA TAP error (HTTP {resp.status_code})")
            rows = self._parse_csv(resp.text)
            try:
                disk.write_text(json.dumps(rows), encoding="utf-8")
            except Exception:
                pass

        frames: list[FrameRecord] = []
        for r in rows:
            collection = r.get("obs_collection", "")
            if not collection.startswith("spherex"):
                continue
            m = re.search(r"D(\d)", r.get("energy_bandpassname", ""))
            if not m:
                continue
            try:
                t_min = float(r["t_min"])
                t_max = float(r.get("t_max") or t_min)
                frames.append(
                    FrameRecord(
                        obs_id=r["obs_id"],
                        collection=collection,
                        detector=int(m.group(1)),
                        mjd=(t_min + t_max) / 2.0,
                        em_min_um=float(r["em_min"]) * 1e6,
                        em_max_um=float(r["em_max"]) * 1e6,
                    )
                )
            except (KeyError, ValueError):
                continue
        frames.sort(key=lambda f: f.mjd)
        self._coverage_cache[key] = frames
        return frames

    @staticmethod
    def _parse_csv(text: str) -> list[dict[str, str]]:
        lines = [ln for ln in text.strip().splitlines() if ln.strip()]
        if not lines:
            return []
        header = [h.strip() for h in lines[0].split(",")]
        out = []
        for ln in lines[1:]:
            parts = ln.split(",")
            if len(parts) == len(header):
                out.append(dict(zip(header, (p.strip() for p in parts))))
        return out

    @staticmethod
    def summarize(frames: list[FrameRecord]) -> dict[str, Any]:
        by_det: dict[str, int] = {}
        for f in frames:
            by_det[str(f.detector)] = by_det.get(str(f.detector), 0) + 1
        collections = sorted({f.collection for f in frames})
        epochs = group_epochs(frames)
        return {
            "total_frames": len(frames),
            "by_detector": by_det,
            "collections": collections,
            "n_epochs": len(epochs),
            "epochs": [
                {"start": mjd_to_iso(g[0].mjd), "end": mjd_to_iso(g[-1].mjd), "n_frames": len(g)} for g in epochs
            ],
            "mjd_min": frames[0].mjd if frames else None,
            "mjd_max": frames[-1].mjd if frames else None,
            "date_min": mjd_to_iso(frames[0].mjd) if frames else None,
            "date_max": mjd_to_iso(frames[-1].mjd) if frames else None,
        }

    # -------------------------------------------------------------- download
    async def _resolve_file_url(self, client: httpx.AsyncClient, rec: FrameRecord) -> str:
        if rec.key in self._urls:
            if not self._urls[rec.key]:  # known to have no Level-2 file (e.g. withdrawn quick release)
                raise SpherexError("upstream", f"No Level-2 file found for {rec.key}")
            return self._urls[rec.key]
        params = {"ID": f"ivo://irsa.ipac/{rec.collection}?{rec.obs_id}/D{rec.detector}"}
        resp = await client.get(DATALINK_URL, params=params)
        resp.raise_for_status()
        for cand in re.findall(r"<TD>(https://[^<]+?level2_[^<]+?\.fits)</TD>", resp.text):
            self._urls[rec.key] = cand
            self._save_urls()
            return cand
        self._urls[rec.key] = ""  # remember, so later requests do not ask datalink again
        self._save_urls()
        raise SpherexError("upstream", f"No Level-2 file found for {rec.key}")

    async def fetch_cutout(
        self, client: httpx.AsyncClient, rec: FrameRecord, ra: float, dec: float, size_deg: float
    ) -> Optional[Cutout]:
        tag = hashlib.md5(f"{rec.key}:{ra:.4f}:{dec:.4f}:{size_deg:.4f}".encode()).hexdigest()[:20]
        path = self.cache_dir / "cutouts" / f"{rec.obs_id}_D{rec.detector}_{tag}.fits"
        lock = self._locks.setdefault(str(path), asyncio.Lock())
        async with lock:
            if not path.exists():
                async with self._sem:
                    last_exc: Optional[Exception] = None
                    for attempt in range(3):
                        try:
                            url = await self._resolve_file_url(client, rec)
                            resp = await client.get(
                                url, params={"center": f"{ra:.6f},{dec:.6f}", "size": f"{size_deg:.5f}"}
                            )
                            resp.raise_for_status()
                            await asyncio.to_thread(self._store_compact, resp.content, path, url)
                            self._maybe_prune()
                            last_exc = None
                            break
                        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                            last_exc = exc
                            status = getattr(getattr(exc, "response", None), "status_code", 0)
                            if isinstance(exc, httpx.HTTPStatusError) and status < 500:
                                break  # 4xx will not get better
                            await asyncio.sleep(2.0 * (attempt + 1))
                        except Exception as exc:
                            last_exc = exc
                            break
                    if last_exc is not None:
                        logger.warning(f"SPHEREx cutout failed for {rec.key}: {last_exc}")
                        return None
        try:
            return await asyncio.to_thread(self._read_cutout, path, rec)
        except Exception as exc:
            logger.warning(f"Unreadable cached cutout {path.name}: {exc}")
            path.unlink(missing_ok=True)
            return None

    @staticmethod
    def _store_compact(content: bytes, path: Path, url: str) -> None:
        """Keep only the extensions we need (drops the ~5 MB PSF cube)."""
        with fits.open(io.BytesIO(content)) as hdul:
            keep = [fits.PrimaryHDU(header=hdul[0].header)]
            for name in ("IMAGE", "FLAGS", "VARIANCE", "ZODI", "WCS-WAVE"):
                if name in hdul:
                    keep.append(hdul[name].copy())
            keep[0].header["SRCURL"] = url[:68]
            tmp = path.with_suffix(".tmp")
            fits.HDUList(keep).writeto(tmp, overwrite=True)
            tmp.replace(path)
            path.with_suffix(".url").write_text(url, encoding="utf-8")

    @staticmethod
    def _read_cutout(path: Path, rec: FrameRecord) -> Cutout:
        with fits.open(path) as hdul:
            hdr = hdul["IMAGE"].header
            image = hdul["IMAGE"].data.astype(np.float32)
            if "ZODI" in hdul:
                image = image - hdul["ZODI"].data.astype(np.float32)
            flags = hdul["FLAGS"].data.astype(np.int64) if "FLAGS" in hdul else np.zeros(image.shape, np.int64)
            variance = (
                hdul["VARIANCE"].data.astype(np.float32) if "VARIANCE" in hdul else np.ones(image.shape, np.float32)
            )
            if "A_ORDER" in hdr:
                for k in ("CTYPE1", "CTYPE2"):
                    if not str(hdr.get(k, "")).endswith("-SIP"):
                        hdr[k] = f"{hdr[k]}-SIP"
            wcs = WCS(hdr)
            wavelength = None
            ww = None
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    ww = WCS(hdr, fobj=hdul, key="W")
                ny, nx = image.shape
                lam, _ = ww.pixel_to_world_values((nx - 1) / 2.0, (ny - 1) / 2.0)
                wavelength = float(lam) if np.isfinite(lam) else None
            except Exception:
                wavelength = None
                ww = None
            bits = dict(DEFAULT_FLAG_BITS)
            if "FLAGS" in hdul:
                for k, v in hdul["FLAGS"].header.items():
                    if k.startswith("MP_"):
                        bits[k[3:]] = int(v)
            mjd = float(hdr.get("MJD-AVG", rec.mjd))
        url_file = path.with_suffix(".url")
        url = url_file.read_text(encoding="utf-8") if url_file.exists() else ""
        return Cutout(rec, url, image, flags, variance, wcs, mjd, wavelength, bits, ww)

    # -------------------------------------------------------------- building
    async def build_blink(
        self,
        ra: float,
        dec: float,
        fov_deg: float = 0.1,
        detectors: Optional[list[int]] = None,
        mode: str = "epoch",
        per_epoch: int = 4,
        max_frames: int = 16,
        pmra: Optional[float] = None,
        pmdec: Optional[float] = None,
        ref_epoch: float = 2000.0,
        pass_index: Optional[int] = None,
        keep_arrays: bool = False,
        wl_min: Optional[float] = None,
        wl_max: Optional[float] = None,
    ) -> dict[str, Any]:
        """Build co-registered frames.

        mode="epoch":  one inverse-variance stack per survey pass (per_epoch exposures each)
        mode="frames": individual exposures spread over the whole time range
        mode="pass":   individual exposures from ONE survey pass (pass_index), keeping whole
                       short exposure sequences together - the right input for asteroid searches
        keep_arrays:   also return raw float arrays / masks under "_arrays" / "_masks" (internal use)
        wl_min/wl_max: wavelength band in um. SPHEREx's linear variable filters put a source at a
                       different wavelength in every exposure, so the band is applied per exposure
                       (the wavelength at the target pixel) after download; detectors whose range
                       does not overlap the band are skipped before download.
        """
        per_epoch_req = per_epoch
        t0 = time.perf_counter()
        has_pm = pmra is not None and pmdec is not None and (abs(pmra) > 0 or abs(pmdec) > 0)

        # Centre on where the target is during the SPHEREx survey (matters for fast movers).
        q_ra, q_dec = (ra, dec)
        if has_pm:
            q_ra, q_dec = propagate(ra, dec, pmra or 0.0, pmdec or 0.0, ref_epoch, mjd_to_year(61000.0))

        all_frames = await self.query_frames(q_ra, q_dec)
        if not all_frames:
            raise SpherexError("no_coverage", "No SPHEREx frames cover this position yet.")
        coverage = self.summarize(all_frames)

        if has_pm:
            mid = (all_frames[0].mjd + all_frames[-1].mjd) / 2.0
            c_ra, c_dec = propagate(ra, dec, pmra or 0.0, pmdec or 0.0, ref_epoch, mjd_to_year(mid))
        else:
            c_ra, c_dec = ra, dec

        band = wl_min is not None or wl_max is not None
        lo = wl_min if wl_min is not None else 0.0
        hi = wl_max if wl_max is not None else 99.0
        frames = [f for f in all_frames if (not detectors or f.detector in detectors) and self.available(f)
                  and (not band or (f.em_max_um >= lo and f.em_min_um <= hi))]
        if not frames:
            raise SpherexError("no_band_coverage" if band else "no_detector_coverage",
                               "No frames for the selected detector(s) / band.")
        if band and mode == "epoch":
            # only a fraction of the exposures fall in a narrow band: download a full budget
            per_epoch = MAX_DOWNLOADS

        requested_pass = pass_index

        def choose(pool: list[FrameRecord]) -> tuple[list[list[FrameRecord]], Optional[int]]:
            if mode == "pass":
                passes = group_epochs(pool)
                pi = requested_pass
                if pi is None:
                    pi = max(range(len(passes)), key=lambda i: len(passes[i]))
                if not 0 <= pi < len(passes):
                    raise SpherexError("bad_pass", f"Pass index must be 0..{len(passes) - 1}.")
                return [[f] for f in select_sequences(passes[pi], min(max_frames, MAX_DOWNLOADS))], pi
            return select_groups(pool, mode, per_epoch, max_frames), None

        groups, pass_index = choose(frames)
        size_px = int(round(fov_deg * 3600.0 / NATIVE_PIXSCALE_ARCSEC))
        size_px = max(15, size_px + (1 - size_px % 2))
        out_wcs = make_target_wcs(c_ra, c_dec, size_px, NATIVE_PIXSCALE_ARCSEC)
        cut_size = fov_deg * 1.5 + 0.01  # margin so reprojection never runs off the cutout

        cutouts: dict[str, Cutout] = {}
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0), follow_redirects=True) as client:
            # Some archive frames turn out to have no Level-2 file (withdrawn quick releases). They
            # are remembered, so a second round picks replacements from the remaining frames.
            for _round in range(2):
                needed = {r.key: r for g in groups for r in g if r.key not in cutouts}
                if not needed:
                    break
                results = await gather_with_progress(
                    "download", (self.fetch_cutout(client, r, c_ra, c_dec, cut_size) for r in needed.values())
                )
                cutouts.update({c.record.key: c for c in results if c is not None})
                lost = [k for k in needed if k not in cutouts and not self.available(needed[k])]
                if not lost:
                    break
                frames = [f for f in frames if self.available(f)]
                if not frames:
                    break
                groups, pass_index = choose(frames)
        if not cutouts:
            raise SpherexError("upstream", "Could not download any SPHEREx cutouts from IRSA.")
        if band:
            cutouts = {k: c for k, c in cutouts.items() if c.wavelength_um is not None and lo <= c.wavelength_um <= hi}
            if not cutouts:
                raise SpherexError("no_band_coverage", "No exposure sees this position inside the band.")
            if mode == "epoch":
                groups = [[r for r in g if r.key in cutouts][:max(1, per_epoch_req)] for g in groups]
            groups = [g for g in groups if any(r.key in cutouts for r in g)]

        report("assemble")
        out_frames = await asyncio.to_thread(
            self._assemble, groups, cutouts, out_wcs, size_px, ra, dec, pmra, pmdec, ref_epoch, has_pm
        )
        if not out_frames:
            raise SpherexError("no_data", "Frames were found but contained no valid pixels at this position.")

        arrays = [f.pop("_arr") for f in out_frames]
        masks = [f.pop("_mask") for f in out_frames]
        finite = np.concatenate([a[np.isfinite(a)] for a in arrays])
        vmin, vmax = (float(np.percentile(finite, 1.0)), float(np.percentile(finite, 99.7))) if finite.size else (0.0, 1.0)

        out: dict[str, Any] = {
            "target": {
                "ra": ra, "dec": dec, "pmra": pmra, "pmdec": pmdec, "ref_epoch": ref_epoch,
                "center_ra": c_ra, "center_dec": c_dec,
            },
            "grid": {
                "width": size_px, "height": size_px, "pixscale_arcsec": NATIVE_PIXSCALE_ARCSEC,
                "fov_deg": size_px * NATIVE_PIXSCALE_ARCSEC / 3600.0, "crpix": [(size_px - 1) / 2.0] * 2,
                "ra": c_ra, "dec": c_dec, "projection": "TAN", "orientation": "north-up, east-left",
            },
            "coverage": coverage,
            "mode": mode,
            "detectors": detectors or [1, 2, 3, 4, 5, 6],
            "frames": out_frames,
            "stretch_hint": {"vmin": vmin, "vmax": vmax},
            "units": "MJy/sr (zodiacal light and local sky subtracted)",
            "source": "NASA/IPAC IRSA - SPHEREx Level-2 spectral images (" + ", ".join(coverage["collections"]) + ")",
            "is_simulated": False,
            "pass_index": pass_index if mode == "pass" else None,
            "band_um": [wl_min, wl_max] if band else None,
            "elapsed_s": round(time.perf_counter() - t0, 2),
        }
        if keep_arrays:
            out["_arrays"] = arrays
            out["_masks"] = masks
            out["_wcs"] = out_wcs
        return out

    async def photometry(
        self,
        ra: float,
        dec: float,
        detectors: Optional[list[int]] = None,
        max_frames: int = 60,
        pmra: Optional[float] = None,
        pmdec: Optional[float] = None,
        ref_epoch: float = 2000.0,
        aperture_px: float = 2.0,
    ) -> dict[str, Any]:
        """Aperture photometry of one sky position in many SPHEREx exposures.

        Because SPHEREx uses linear variable filters, each exposure samples a different
        wavelength at the source, so the result is both a spectrum (flux vs wavelength,
        0.75-5 um) and a light curve (flux vs time, per detector).
        """
        t0 = time.perf_counter()
        has_pm = pmra is not None and pmdec is not None and (abs(pmra) > 0 or abs(pmdec) > 0)
        q_ra, q_dec = (ra, dec)
        if has_pm:
            q_ra, q_dec = propagate(ra, dec, pmra or 0.0, pmdec or 0.0, ref_epoch, mjd_to_year(61000.0))
        frames = [f for f in await self.query_frames(q_ra, q_dec) if self.available(f)]
        if detectors:
            frames = [f for f in frames if f.detector in detectors]
        if not frames:
            raise SpherexError("no_coverage", "No SPHEREx frames cover this position yet.")

        mid = (frames[0].mjd + frames[-1].mjd) / 2.0
        c_ra, c_dec = propagate(ra, dec, pmra or 0.0, pmdec or 0.0, ref_epoch, mjd_to_year(mid)) if has_pm else (ra, dec)
        picked = select_for_photometry(frames, min(max_frames, MAX_DOWNLOADS * 2))

        # A small cutout is enough; widen it for fast movers so the source stays inside.
        span_yr = (frames[-1].mjd - frames[0].mjd) / 365.25
        motion_deg = (math.hypot(pmra or 0.0, pmdec or 0.0) / 3.6e6) * span_yr if has_pm else 0.0
        cut_size = 0.03 + 2 * motion_deg
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0), follow_redirects=True) as client:
            cutouts = list(await gather_with_progress(
                "download", (self.fetch_cutout(client, r, c_ra, c_dec, cut_size) for r in picked)
            ))
            # replace frames whose files turned out to be withdrawn (see build_blink)
            lost = sum(1 for r, c in zip(picked, cutouts) if c is None and not self.available(r))
            if lost:
                used = {r.key for r in picked}
                spare = [f for f in frames if f.key not in used and self.available(f)]
                extra = select_for_photometry(spare, lost) if spare else []
                cutouts += await gather_with_progress(
                    "download", (self.fetch_cutout(client, r, c_ra, c_dec, cut_size) for r in extra)
                )
        report("measure")

        points = []
        for c in cutouts:
            if c is None:
                continue
            t_ra, t_dec = (
                propagate(ra, dec, pmra or 0.0, pmdec or 0.0, ref_epoch, mjd_to_year(c.mjd)) if has_pm else (ra, dec)
            )
            p = aperture_photometry(c, t_ra, t_dec, aperture_px)
            if p is not None:
                points.append(p)
        if not points:
            raise SpherexError("no_data", "Frames were found but photometry failed at this position.")
        points.sort(key=lambda p: p["mjd"])
        good = [p for p in points if not p["flagged"]]
        return {
            "position": {"ra": ra, "dec": dec, "pmra": pmra, "pmdec": pmdec, "ref_epoch": ref_epoch},
            "aperture_arcsec": round(aperture_px * NATIVE_PIXSCALE_ARCSEC, 2),
            "n_points": len(points),
            "n_good": len(good),
            "points": points,
            "units": "mJy (aperture flux, local background subtracted, no aperture correction)",
            "source": "NASA/IPAC IRSA - SPHEREx Level-2 spectral images",
            "is_simulated": False,
            "elapsed_s": round(time.perf_counter() - t0, 2),
        }

    def _assemble(
        self, groups, cutouts, out_wcs, size_px, ra, dec, pmra, pmdec, ref_epoch, has_pm
    ) -> list[dict[str, Any]]:
        yy, xx = np.mgrid[0:size_px, 0:size_px]
        world_ra, world_dec = out_wcs.pixel_to_world_values(xx, yy)
        out: list[dict[str, Any]] = []
        for gi, group in enumerate(groups):
            members = [cutouts[r.key] for r in group if r.key in cutouts]
            if not members:
                continue
            num = np.zeros((size_px, size_px), np.float64)
            den = np.zeros((size_px, size_px), np.float64)
            flag_hits = {name: 0 for name in REPORTED_FLAGS}
            n_valid = np.zeros((size_px, size_px), np.int32)
            used = []
            for c in members:
                img, var, msk, flag_stats = reproject_cutout(c, world_ra, world_dec)
                if img is None:
                    continue
                valid = ~msk & np.isfinite(img) & np.isfinite(var) & (var > 0)
                if valid.sum() < 0.25 * valid.size:
                    continue
                sky = np.nanmedian(img[valid])
                w = np.where(valid, 1.0 / np.where(var > 0, var, np.inf), 0.0)
                num += np.where(valid, (img - sky) * w, 0.0)
                den += w
                n_valid += valid
                for name, frac in flag_stats.items():
                    flag_hits[name] = flag_hits.get(name, 0) + frac
                used.append(c)
            if not used:
                continue
            with np.errstate(invalid="ignore", divide="ignore"):
                data = np.where(den > 0, num / den, np.nan).astype(np.float32)
            data, filled = fill_saturated_holes(data)
            # A stacked pixel is unreliable when fewer than half of the exposures had valid data
            # there (for single exposures: whenever it was flagged), or when it was filled.
            masked_any = filled | (n_valid * 2 < len(used))
            mjd = float(np.mean([c.mjd for c in used]))
            waves = [c.wavelength_um for c in used if c.wavelength_um]
            target_px = None
            if has_pm:
                t_ra, t_dec = propagate(ra, dec, pmra or 0.0, pmdec or 0.0, ref_epoch, mjd_to_year(mjd))
            else:
                t_ra, t_dec = ra, dec
            px, py = out_wcs.world_to_pixel_values(t_ra, t_dec)
            if np.isfinite(px) and np.isfinite(py):
                target_px = [round(float(px), 2), round(float(py), 2)]
            out.append(
                {
                    "index": len(out),
                    "group": gi,
                    "mjd": mjd,
                    "date": mjd_to_iso(mjd),
                    "date_start": mjd_to_iso(min(c.mjd for c in used)),
                    "date_end": mjd_to_iso(max(c.mjd for c in used)),
                    "n_frames": len(used),
                    "detectors": sorted({c.record.detector for c in used}),
                    "wavelength_um": [round(min(waves), 3), round(max(waves), 3)] if waves else None,
                    "members": [
                        {**c.record.to_dict(), "wavelength_center_um": round(c.wavelength_um, 4) if c.wavelength_um else None, "url": c.url}
                        for c in used
                    ],
                    "flags": {k: round(v / len(used), 4) for k, v in flag_hits.items() if v > 0},
                    "masked_fraction": round(float(masked_any.mean()), 4),
                    "target_px": target_px,
                    "data": base64.b64encode(np.ascontiguousarray(data, dtype="<f4").tobytes()).decode("ascii"),
                    "mask": base64.b64encode(np.packbits(masked_any.astype(np.uint8)).tobytes()).decode("ascii"),
                    "_arr": data,
                    "_mask": masked_any,
                }
            )
        return out


def reproject_cutout(c: Cutout, world_ra: np.ndarray, world_dec: np.ndarray):
    """Bilinear reprojection of one cutout onto the output grid (SIP-aware)."""
    try:
        px, py = c.wcs.world_to_pixel_values(world_ra, world_dec)
    except Exception:
        return None, None, None, {}
    ny, nx = c.image.shape
    inside = (px >= 0) & (px <= nx - 1) & (py >= 0) & (py <= ny - 1)
    if not inside.any():
        return None, None, None, {}

    bad_bits = 0
    for name in MASKED_FLAG_NAMES:
        bit = c.flag_bits.get(name)
        if bit is not None:
            bad_bits |= 1 << bit
    bad = ((c.flags & bad_bits) != 0) | ~np.isfinite(c.image)
    img = np.where(bad, 0.0, c.image)
    var = np.where(bad | ~np.isfinite(c.variance), 0.0, c.variance)
    coords = [py, px]
    r_img = map_coordinates(img, coords, order=1, mode="constant", cval=0.0)
    r_var = map_coordinates(var, coords, order=1, mode="constant", cval=0.0)
    r_bad = map_coordinates(bad.astype(np.float32), coords, order=1, mode="constant", cval=1.0)
    mask = (r_bad > 0.01) | ~inside
    r_img = np.where(mask, np.nan, r_img)

    stats: dict[str, float] = {}
    region = c.flags[
        max(0, int(np.nanmin(py[inside]))): int(np.nanmax(py[inside])) + 1,
        max(0, int(np.nanmin(px[inside]))): int(np.nanmax(px[inside])) + 1,
    ]
    if region.size:
        for name in REPORTED_FLAGS:
            bit = c.flag_bits.get(name)
            if bit is not None:
                frac = float(((region >> bit) & 1).mean())
                if frac > 0:
                    stats[name] = frac
    return r_img, r_var, mask, stats


def aperture_photometry(c: Cutout, ra: float, dec: float, r_ap: float = 2.0) -> Optional[dict[str, Any]]:
    """Circular-aperture flux at (ra, dec) with an annulus background (r_ap+2 .. r_ap+5 px)."""
    try:
        x, y = c.wcs.world_to_pixel_values(ra, dec)
    except Exception:
        return None
    x, y = float(x), float(y)
    ny, nx = c.image.shape
    r_out = r_ap + 5.0
    if not (r_ap <= x <= nx - 1 - r_ap and r_ap <= y <= ny - 1 - r_ap):
        return None
    yy, xx = np.mgrid[0:ny, 0:nx]
    rr = np.hypot(xx - x, yy - y)
    ap = rr <= r_ap
    ann = (rr >= r_ap + 2.0) & (rr <= r_out)

    bad_bits = 0
    for name in MASKED_FLAG_NAMES:
        bit = c.flag_bits.get(name)
        if bit is not None:
            bad_bits |= 1 << bit
    bad = ((c.flags & bad_bits) != 0) | ~np.isfinite(c.image) | ~np.isfinite(c.variance)
    sat_bit = c.flag_bits.get("OVERFLOW")
    saturated = bool(sat_bit is not None and ((c.flags[ap] >> sat_bit) & 1).any())

    ann_ok = ann & ~bad
    if ann_ok.sum() < 5:
        return None
    bkg = float(np.median(c.image[ann_ok]))
    ap_ok = ap & ~bad
    bad_frac = float(1.0 - ap_ok.sum() / max(ap.sum(), 1))

    # Pixel solid angle from the local WCS (deg^2 -> sr); MJy/sr * sr -> MJy -> mJy.
    try:
        scales = c.wcs.proj_plane_pixel_scales()
        omega_sr = float(scales[0].to_value("deg") * scales[1].to_value("deg")) * (math.pi / 180.0) ** 2
    except Exception:
        omega_sr = (NATIVE_PIXSCALE_ARCSEC / 206264.806) ** 2
    to_mjy = omega_sr * 1e9
    if ap_ok.any():
        flux = float((c.image[ap_ok] - bkg).sum()) * to_mjy * (ap.sum() / ap_ok.sum())
        err = float(math.sqrt(max(float(c.variance[ap_ok].sum()), 0.0))) * to_mjy * (ap.sum() / ap_ok.sum())
    else:
        flux, err = float("nan"), float("nan")

    lam = c.wavelength_at(x, y)
    flagged = bool(bad_frac > 0.3 or saturated or not math.isfinite(flux) or lam is None)
    return {
        "mjd": c.mjd,
        "date": mjd_to_iso(c.mjd),
        "detector": c.record.detector,
        "obs_id": c.record.obs_id,
        "wavelength_um": round(lam, 4) if lam else None,
        "flux_mjy": round(float(flux), 4) if math.isfinite(flux) else None,
        "err_mjy": round(float(err), 4) if math.isfinite(err) else None,
        "saturated": saturated,
        "masked_fraction": round(bad_frac, 3),
        "flagged": flagged,
    }


def select_for_photometry(frames: list[FrameRecord], n: int) -> list[FrameRecord]:
    """Spread the download budget evenly over detectors (wavelength) and time."""
    by_det: dict[int, list[FrameRecord]] = {}
    for f in frames:
        by_det.setdefault(f.detector, []).append(f)
    per = max(1, n // max(1, len(by_det)))
    out: list[FrameRecord] = []
    for det in sorted(by_det):
        out.extend(_spread(sorted(by_det[det], key=lambda r: r.mjd), per))
    return out


def fill_saturated_holes(data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fill interior NaN islands (saturated / flagged star cores) with the bright rim value.

    Bright stars such as Barnard's Star have flagged cores in every exposure; without this
    they render as black holes. Returns the filled image and a mask of filled pixels.
    """
    holes = ~np.isfinite(data)
    if not holes.any():
        return data, np.zeros(data.shape, bool)
    labels, n = ndimage.label(holes)
    border = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    out = data.copy()
    filled = np.zeros(data.shape, bool)
    for lab in range(1, n + 1):
        if lab in border:
            continue
        region = labels == lab
        if region.sum() > 0.05 * data.size:
            continue
        rim = ndimage.binary_dilation(region, iterations=1) & ~holes
        if rim.any():
            out[region] = np.percentile(data[rim], 90)
            filled |= region
    return out, filled


def group_epochs(frames: list[FrameRecord]) -> list[list[FrameRecord]]:
    groups: list[list[FrameRecord]] = []
    for f in sorted(frames, key=lambda r: r.mjd):
        if groups and f.mjd - groups[-1][-1].mjd <= EPOCH_GAP_DAYS:
            groups[-1].append(f)
        else:
            groups.append([f])
    return groups


def _spread(items: list, n: int) -> list:
    if n <= 0 or len(items) <= n:
        return list(items)
    idx = np.linspace(0, len(items) - 1, n).round().astype(int)
    return [items[i] for i in sorted(set(idx.tolist()))]


SEQUENCE_GAP_DAYS = 0.05  # SPHEREx takes ~4 exposures ~2 min apart at each visit


def group_sequences(frames: list[FrameRecord]) -> list[list[FrameRecord]]:
    """Split frames into short exposure sequences (consecutive exposures < ~1 h apart)."""
    seqs: list[list[FrameRecord]] = []
    for f in sorted(frames, key=lambda r: r.mjd):
        if seqs and f.mjd - seqs[-1][-1].mjd <= SEQUENCE_GAP_DAYS:
            seqs[-1].append(f)
        else:
            seqs.append([f])
    return seqs


def select_sequences(frames: list[FrameRecord], budget: int) -> list[FrameRecord]:
    """Pick whole exposure sequences, spread over the pass, until the download budget is used.

    Keeping sequences intact matters for asteroid searches: a moving object shows up in the
    2-4 exposures of one visit, while the other visits provide the static-sky template.
    """
    seqs = group_sequences(frames)
    if sum(len(s) for s in seqs) <= budget:
        return sorted(frames, key=lambda r: r.mjd)
    order = seqs
    # Interleave from both ends towards the middle so the time span stays wide.
    picked_idx: list[int] = []
    lo, hi = 0, len(order) - 1
    while lo <= hi:
        picked_idx.append(lo)
        if hi != lo:
            picked_idx.append(hi)
        lo, hi = lo + 1, hi - 1
    out: list[FrameRecord] = []
    for i in picked_idx:
        if len(out) + len(order[i]) > budget:
            continue
        out.extend(order[i])
    return sorted(out, key=lambda r: r.mjd)


def select_groups(frames: list[FrameRecord], mode: str, per_epoch: int, max_frames: int) -> list[list[FrameRecord]]:
    """Choose which frames to download and how to group them into blink frames."""
    if mode == "frames":
        picked = _spread(sorted(frames, key=lambda r: r.mjd), min(max_frames, MAX_DOWNLOADS))
        return [[f] for f in picked]
    epochs = group_epochs(frames)
    budget = max(1, min(per_epoch, MAX_DOWNLOADS // max(1, len(epochs))))
    return [_spread(g, budget) for g in epochs]


spherex_archive = SpherexArchive()
