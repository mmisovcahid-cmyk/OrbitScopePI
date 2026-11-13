# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

OrbitScope is a SPHEREx time-domain sky monitoring / moving-object detection platform: a Python FastAPI backend (`backend/`) running an astronomical image-processing pipeline, plus a React + TypeScript + Vite + Tailwind frontend (`frontend/`). The UI is bilingual (English / Azerbaijani). See `docs/DATA_SOURCES.md` for every external API (all keyless) and `docs/AUDIT_AND_ROADMAP.md` for status and validation results. `docs/METHODOLOGY.md` explains the algorithms, `docs/LIMITATIONS.md` the known limits, and `docs/ARCHITECTURE.md` the system layout.

**Main target: Raspberry Pi 5 (8 GB)**, running as server + kiosk + its own Wi-Fi access point, with an offline demo mode. See `docs/RASPBERRY_PI.md`; the deployment files are in `deploy/pi/` and `docker-compose.pi.yml`. Windows (`start.bat`/`start.ps1`) is only for development on a PC.

Git workflow (from the user):
- This repository is `OrbitScopePI` (github.com/mmisovcahid-cmyk/OrbitScopePI), separate from the older OrbitScope repo. The `.claude/worktrees/full-system` folder inside it is a stale copy of that old repo and is gitignored.
- Do Pi work on the `dev/pi` branch.
- Merge into `main` only after the user approves, and never commit or push without explicit approval.
- The user writes in Turkish and wants answers in Turkish.

## Commands

Backend (run from `backend/`, Python 3.10+):
```bash
pip install -r requirements.txt
python run.py                         # uvicorn app.main:app on :8000 (reload when DEBUG=true); docs at /docs
pytest tests/ -v                      # all tests
pytest tests/test_moving_objects.py -v   # one file
pytest tests/test_api_and_ml.py::test_root_endpoint -v   # one test
python -m scripts.prewarm             # fill the IRSA cutout cache for the five challenge targets
python -m scripts.prewarm --targets barnard,wise-0855 --quick
```
Config comes from `backend/.env` (template: `.env.example`), loaded by `app/core/config.py` (pydantic-settings, `settings` singleton).

Frontend (run from `frontend/`):
```bash
npm install
npm run dev       # Vite dev server
npm run build     # tsc type-check + vite build — the main correctness check for frontend changes
```
`npm run lint` runs ESLint 9 with a flat config (`eslint.config.js`, typescript-eslint + react-hooks). Errors fail; `any` is only a warning, because the older demo pages still use it. `npm run typecheck` runs `tsc --noEmit`.

Raspberry Pi (on the Pi, from the repo root):
```bash
sudo deploy/pi/install.sh [--docker] [--prewarm] [--no-ap] [--no-kiosk]
orbitscope-check                     # diagnostics (deploy/pi/pi_check.sh)
sudo orbitscope-net ap|client|status # Wi-Fi access point (deploy/pi/orbitscope-net.sh)
```
None of the `deploy/pi` scripts can run on Windows. Check them with `bash -n deploy/pi/*.sh` and keep LF line endings.

Docker: `docker compose up --build` serves the app on :8080. Images: `backend/Dockerfile` (uvicorn, data in the `/data` volume) and `frontend/Dockerfile` (Vite build with an empty `VITE_API_BASE`, served by nginx, which proxies `/api` to `backend:8000`). In `services/api.ts`, `VITE_API_BASE` wins when set (`''` = same origin). When it is unset, dev mode uses `http://localhost:8000` and production builds use their own origin (so phones on the Pi's Wi-Fi work).

`start.bat` / `start.ps1` at the root launch backend and frontend in separate windows. `.claude/launch.json` defines `backend` (:8000) and `frontend` (:5173) preview configurations.

The Vite dev server runs on 5173 and calls the backend on :8000 directly; the Vite `/api` proxy exists but the axios client does not use it.

## Real SPHEREx data path (the main feature)

Every page in the UI uses real data:

- Blink, Detection, Comparison and Analysis use SPHEREx data via IRSA.
- Sky Explorer uses the saved runs and candidates plus live status.
- Catalog uses live JPL data (`app/services/jpl_catalog.py`: SBDB, Horizons, SB Ident).
- Planet X runs a live Rayleigh clustering test on JPL orbits (`app/services/etno.py`): the complete SBDB Query API sample (a ≥ 150 AU, q ≥ 30 AU, condition code ≤ 5) next to the 20-object literature sample; its evidence cards are labelled literature.

Real-data paths must never fall back to invented values: return a 502 with an explanation instead. The test suite blocks network access to SB Ident in `tests/conftest.py` and redirects the catalog-overlay disk cache to a temp dir (so fake rows never reach the real cache); it runs offline in about 10 s. Tests that need a stub use `monkeypatch.setattr`, which overrides these fixtures.

- `app/services/spherex_archive.py`:
  1. Queries IRSA TAP `spherex.obscore` with `CONTAINS(POINT(ra,dec), s_region)`. Collections are matched by the `spherex` prefix, so new releases are picked up without code changes.
  2. Resolves each frame's Level-2 FITS URL through IRSA datalink.
  3. Downloads IBE cutouts (`?center=&size=`), stores them compactly, and drops the ~5 MB PSF cube.
  4. Subtracts ZODI and the local sky, masks FLAGS bits, reprojects onto a north-up TAN grid with SIP-aware `map_coordinates`, and does an inverse-variance coadd per survey pass (frames >30 days apart are separate passes). It also fills saturated star cores.
  5. Returns float32 frames as base64; the browser does stretching, colour maps, difference and motion modes.
- Everything is cached under `backend/cache/spherex/` (gitignored). The first request for a new field takes 30–90 s; repeats are instant.
- `app/services/target_resolver.py` accepts decimal or sexagesimal coordinates, the five challenge targets (Gaia DR3/SIMBAD positions + proper motion), CDS Sesame (with a CfA mirror) and NED. High-PM targets are propagated to the SPHEREx epoch.
- Routes are in `app/api/routes/spherex.py`: `/api/v1/spherex/{targets,resolve,coverage,blink,blink.gif}`.
- Frontend: `pages/BlinkPage.tsx` (`/`), `pages/EmbedPage.tsx` (`/embed`, iframe-friendly), `components/blink/BlinkViewer.tsx`, `lib/spherex.ts`. The URL query (`target, ra, dec, fov, det, mode, per, max`) is the source of truth, so links are shareable.
- The IRSA cutout service sometimes returns 503; `fetch_cutout` retries with backoff.
- `/api/v1/spherex/photometry` measures one position in up to 96 exposures, spread over detectors and time (`select_for_photometry`). Each point's wavelength comes from that pixel's LVF wavelength via the `WCS-WAVE` table (`Cutout.wavelength_at`), so the same result gives both a spectrum and a light curve. Saturated (OVERFLOW) or mostly masked apertures are returned with `flagged: true` rather than dropped.
- `/api/v1/spherex/overlay` (`app/services/catalog_overlay.py`) serves Gaia DR3 (ESA TAP, epoch 2016.0) and CatWISE2020 (IRSA TAP, epoch 2015.4, pm converted to mas/yr). CatWISE rows with D/P/H/O artifact flags are dropped, and motions of blended (nb>1) or low-S/N detections are zeroed. The browser propagates each marker to the date of the frame being shown.
## Offline mode and kiosk (Raspberry Pi)

- **`app/core/offline.py`:** every real JPL SBDB, Planet X (`etno`) and Sesame/NED answer is saved to disk.
  - When the service is unreachable, the last copy is returned with `offline_snapshot: {saved_at}`.
  - Without a copy, the original 502 stands.
  - Time-dependent answers (Horizons, SB Ident) are deliberately not snapshotted.
- **`app/core/connectivity.py` (`is_online`):** a TCP probe to IRSA/JPL, cached 30 s.
  - `spherex_archive.query_frames` reuses a stale coverage list when IRSA is unreachable and flags it as `coverage.offline_cached_at`; it is never kept in the memory cache.
  - `catalog_overlay` serves old disk copies when offline.
  - `/system/status` exposes `components.network.online`.
- **Tests:** `tests/conftest.py` redirects snapshots to a temp dir and makes `is_online` return True. Offline tests are in `tests/test_offline.py`.
- **Kiosk endpoint:** `/api/v1/system/kiosk` returns the Wi-Fi SSID and `PUBLIC_URL` for the kiosk QR codes. The password goes only to loopback clients (`_is_local_client`, which fails closed on any non-loopback proxy header).
- **Frontend:**
  - `lib/network.ts` (`useNetwork`) drives `OfflineBanner`, `SnapshotNote` and the Aladin offline note.
  - `lib/kiosk.ts` adds the `kiosk`/`touch` classes on `/?kiosk=1`; the CSS is at the end of `styles/globals.css`.
  - `KioskConnectCard` (lazy-loaded) draws the QR codes.
  - Fonts are bundled via `@fontsource/*`; no Google Fonts.
- **Settings:** `MAX_CONCURRENT_JOBS` and `SPHEREX_DOWNLOAD_CONCURRENCY` are env settings (Pi profile: 2 / 6). SQLite runs in WAL mode.

## Background jobs and progress

- `app/services/jobs.py` (`JobManager`) runs long work as in-process asyncio tasks, at most `MAX_CONCURRENT_JOBS` at a time (default 3). Identical requests (same kind, locale and params) share one job, and finished jobs are kept for 30 minutes.
- Routes are in `app/api/routes/jobs.py`. `POST /api/v1/jobs {kind: blink|detect|photometry, params, locale}` validates the params with the same limits as the direct endpoints and calls the same internals (`spherex._build`, `run_detection`, `spherex_archive.photometry`).
- Progress: library code calls `app.core.progress.report(stage, done, total)`, or `gather_with_progress` for parallel downloads. The job installs a ContextVar callback, so this works through `asyncio.gather` and `to_thread` without any signature changes. Stage names are the keys under `jobs.stage.*` in i18n.
- Frontend: `lib/jobs.ts` `runJob()` submits a job, polls it, cancels it when the AbortSignal fires, and throws `JobError` with the server's localized message. `components/common/JobProgressBar.tsx` shows the progress. Blink, Detection, Photometry and Embed all use jobs; the direct GET endpoints stay for scripts and GIF export.
- `spherex_archive.prune_cache()` keeps the cutout cache under `SPHEREX_CACHE_MAX_MB`. It runs at startup and after every 50 new downloads. `GET /api/v1/spherex/status` is the health endpoint.

## Real-data moving-object search (`/detection`)

- `app/services/detection_service.py`: `run_detection()` gets frames from `build_blink(..., keep_arrays=True)` and runs `app/pipeline/moving_objects.py`. It then matches the results against reference catalogs and saves them through `candidate_store.py` (SQLite at `backend/data/orbitscope.db`, gitignored). Endpoints: `/api/v1/spherex/detect`, `/candidates` (GET), `/candidates/{id}` (PATCH review: unreviewed/real/artifact/unsure), `/candidates/{id}/export` (CSV).
- **Asteroids** (`search=asteroids`, `mode="pass"`):
  - Input: individual exposures of one survey pass. `select_sequences` (in `spherex_archive.py`) keeps SPHEREx's ~4-exposure / ~7-minute visits intact. Paired detectors D1/D4, D2/D5 and D3/D6 expose simultaneously.
  - Detection: median template per detector, then residual detection with the noise model `sigma^2 + (0.15*template)^2` (LVF brightness changes).
  - Linking: within a visit only (`VISIT_WINDOW_DAYS`), then cross-visit joining guarded by `MAX_JOIN_RMS_PX`.
  - Rejection: noisy frames are skipped (`NOISY_FRAME_FACTOR`). `recurrence()` and the "parked" rule turn fixed-position residuals (persistence, variables) into `stationary_transient`.
  - Known objects come from JPL SB Ident (`app/services/small_bodies.py`): one query per visit cluster, linear extrapolation with the returned rates, cached on disk. A known object only counts as recovered if the track is a genuine mover, or position plus rate agree.
- **Proper motion** (`search=proper_motion`, per-pass stacks):
  - Astrometric, not difference-based: `search_proper_motion` centroids isolated, unsaturated sources in every epoch (`refine_centroid`), removes the frame-wide registration offset, and derives the noise floor from the static stars. Reports shifts above 5σ, or brightness ratios ≥1.6 as variables.
  - Catalog matching (Gaia/CatWISE) requires the proper-motion vectors to agree, and widens the radius for fast catalog movers.
  - Saturated stars (Barnard's Star, RW Aur, R Dra) are excluded by design.
- Validated on real data:
  - 626 Notburga (V=13.5) recovered: 8 detections, 1.6″ from JPL, 58″/h.
  - ε Indi B: 4.1″/yr at PA 123°, Gaia match.
  - WISE 0855−0714: 8.2″/yr at PA 286°, 7.6σ, CatWISE match (the requested target is also measured by forced astrometry, `forced=` in `search_proper_motion`, and compared with its catalog PM in `target_check`).
  - Notburga field, both passes, and the ε Indi B field: 0 `unknown_mover` (quality rules in `track_quality` / `mover_quality_ok`; rejected tracks list `rejected_because`).
  - Synthetic tests are in `tests/test_moving_objects.py`.
- The uvicorn `--reload` watcher restarts the backend on any change under `backend/` (tests included), which drops in-flight long requests. Expect this while editing during a long blink or photometry call.

## Backend architecture

- **`app/main.py`** — FastAPI app.
  - Middleware: `json_errors` (JSON 500s), then `RateLimitMiddleware` (`app/core/rate_limit.py`), then CORS outermost, so 429s and 500s keep CORS headers.
  - The `lifespan` hook records the startup time and prunes the SPHEREx cache.
  - There are no service singletons on `app.state`: modules import their own singletons (`spherex_archive`, `job_manager`, `get_store()`).
- **`app/api/routes/`** — `spherex`, `jobs`, `catalog`, `planetx`, `system`, each with prefix `/api/v1/<area>`. Routes take a `locale` param and return localized messages from a per-module `MESSAGES = {"en": ..., "az": ...}` dict; add both languages when adding messages.
- **`app/services/`** — real-data services only (see the sections above). The old simulated prototype was removed: the `sky`/`observations`/`detection` routers, `demo_data`, `jpl_client`, `irsa_client`, `spherex_data`, the photutils pipeline and `app/ml`.
- **`app/pipeline/moving_objects.py`** — the only pipeline module.
- **`app/models/schemas.py`** — Pydantic models. Only `ApiResponse`, `SystemStatus` and the Planet X models are still used; the rest are prototype leftovers.
- **`app/core/`** — `config.py` (pydantic-settings `settings`), `progress.py`, `rate_limit.py`, `cache.py` (TTL caches), `logging_config.py`.
- **`app/services/prewarm.py`** (+ `scripts/prewarm.py` CLI) — downloads all six detectors, the Comparison stacks and the spectra of the five challenge targets and saves the three Detection examples once. Runs in the background at startup when `PREWARM_ON_STARTUP=true` (Docker).
- **Archive hygiene** (`spherex_archive.py`): frames without a Level-2 file are remembered (`""` in `datalink_urls.json`), collections with ≥80 % missing files are treated as withdrawn (QR2), stale coverage lists naming them are re-queried, and lost frames are replaced in a second download round. Coverage is cached 6 h.
- **Blink band filter**: `wl_min`/`wl_max` (µm) on `/blink`, `/blink.gif` and blink jobs, applied per exposure via the LVF wavelength at the target.
- **`app/core/validation_i18n.py`** — 422 responses carry one localized sentence in `detail` (raw list in `errors`).

### Data transparency (project invariant)

Every endpoint serves real data from IRSA, JPL, ESA, CDS or NED. On failure it returns an HTTP 502 with a localized explanation; it never falls back to invented values. Literature content (Planet X evidence and corridors) is labelled `data_source: "published literature"`. Detected objects are "candidates", never discoveries; Planet Nine is presented as an unconfirmed hypothesis. Preserve these distinctions in any new data path or UI copy.

### Public deployment

- `DEBUG` defaults to false; `.env.example` sets it to true for local reload.
- `RATE_LIMIT_PER_MINUTE` (default 60) limits expensive requests per client IP.
- `REVIEW_TOKEN`: when set, `PATCH /candidates/{id}` needs header `X-Review-Token` (the UI asks once and remembers it).
- `PREWARM_ON_STARTUP`: background prewarm (true in docker-compose).
- `TRUST_PROXY_HEADERS=true` (set in docker-compose) takes the IP from nginx's `X-Real-IP`.
- Jobs and rate-limit counters are in-process, so run a single backend process.

## Frontend architecture

- `src/App.tsx` sets up react-router routes (lazy-loaded), all inside a shared `Layout` except `/embed`. Pages live in `src/pages/`:
  - `/` SPHEREx Blink (with `components/blink/AladinPanel.tsx`: CDS Aladin Lite, loaded on demand)
  - `/dashboard` Sky Explorer (`components/skymap/AllSkyMap.tsx`)
  - `/detection`
  - `/analysis/:id` (saved candidate)
  - `/comparison` (two real passes)
  - `/planetx`
  - `/catalog` (live JPL; `?q=` deep link)
  - `/about`
  - `/embed` (outside the Layout)
- `src/services/api.ts` (axios instance) + `src/services/index.ts` (`spherexService`, `catalogService`, `planetxService`, `systemService`). Backend responses are wrapped in a `data` envelope.
- API types live next to their users: `src/lib/spherex.ts` (SPHEREx, detection, candidates) and inside the page files.
- `src/i18n/en.json` and `az.json` — every UI string needs a key in both files.
- Charts use Recharts; `@` alias maps to `src/`.
