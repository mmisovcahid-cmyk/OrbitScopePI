# OrbitScope — System Architecture

```
 Browser (React + TypeScript + Vite)
 ├─ Blink /, Embed /embed       canvas viewer: stretch, colour maps, difference, motion colour, overlays
 ├─ Detection /detection        moving-object search, candidate review, CSV export
 ├─ Sky Explorer /dashboard     all-sky map of saved runs and candidates, live service status
 ├─ Comparison /comparison      two real survey passes side by side
 ├─ Analysis /analysis/:id      one saved candidate: metrics, matches, link to Blink
 ├─ Catalog /catalog            live JPL object lookup, ephemeris, field search
 └─ Planet X /planetx           live eTNO clustering test + literature
        │  axios (VITE_API_BASE; empty = same origin)
        ▼
 nginx (Docker only): static files, /api → backend
        ▼
 FastAPI backend (Python 3.10+)
 ├─ middleware: JSON 500s · rate limit on expensive endpoints · CORS
 ├─ routes/spherex.py   targets, resolve, coverage, blink, blink.gif, photometry, overlay, detect, candidates, overview, status
 ├─ routes/jobs.py      POST/GET/DELETE /api/v1/jobs (background blink, detect, photometry)
 ├─ routes/catalog.py   object, search, ephemeris, nearby
 ├─ routes/planetx.py   clustering (live), tnos (live), evidence + regions (literature)
 └─ routes/system.py    health, status, datasources
        │
 services/
 ├─ spherex_archive.py  IRSA TAP + datalink + cutouts, reprojection, coadd, photometry, disk cache
 ├─ target_resolver.py  coordinates, 5 built-in targets, CDS Sesame (+ CfA mirror), NED
 ├─ catalog_overlay.py  Gaia DR3 (ESA TAP), CatWISE2020 (IRSA TAP)
 ├─ small_bodies.py     JPL SB Ident (known asteroids/comets in a field)
 ├─ jpl_catalog.py      JPL SBDB, Horizons
 ├─ etno.py             Rayleigh clustering of extreme TNO orbits
 ├─ detection_service   runs pipeline/moving_objects.py, catalog matching, classification
 ├─ candidate_store.py  SQLite (runs, candidates, reviews)
 └─ jobs.py             in-process asyncio job manager (max 3 concurrent, deduplicated)
        │
 External (all public, no API keys): NASA/IPAC IRSA · ESA Gaia · NASA/JPL SSD · CDS · NED
```

## Request flow: Blink on a new field

1. The browser submits `POST /api/v1/jobs {kind: "blink", params}` and polls `GET /api/v1/jobs/{id}`. The job reports stage and done/total.
2. `target_resolver` turns the name into a position and proper motion.
3. `spherex_archive.query_frames` runs the IRSA TAP query, which is cached.
4. `select` picks the frames: epochs or one pass, per detector.
5. The cutouts are downloaded in parallel (cached on disk; retried on 5xx).
6. Each cutout is reprojected onto a common TAN grid; the frames of each pass are coadded.
7. The result is base64 float32 frames plus metadata and file URLs. The browser renders them, and Gaia/CatWISE overlays are fetched separately.

Repeated requests reuse the cached cutouts and return in about 1 s. Before a demo, `python -m scripts.prewarm` fills the cache for the five challenge targets.

## State and persistence

| What | Where | Lifetime |
|---|---|---|
| SPHEREx cutouts, datalink URLs, coverage queries | `backend/cache/spherex/` (Docker: `/data/cache`) | Disk; LRU-pruned to `SPHEREX_CACHE_MAX_MB` |
| Detection runs, candidates, reviews | SQLite `backend/data/orbitscope.db` (Docker: `/data/db`) | Permanent |
| Catalog / JPL / overlay responses | In-memory TTL caches | Process lifetime |
| Background jobs | In memory | 30 min after completion |

## Deployment

- `docker compose up --build` serves the whole app on port 8080. Runtime data lives in the `orbitscope-data` volume.
- Docker defaults: `DEBUG=false`, rate limit 60 expensive requests per client per minute, client IP taken from nginx (`TRUST_PROXY_HEADERS=true`).
- **Scaling:** a single backend process is assumed, because jobs and rate-limit counters are in memory. For several replicas they would move to Redis; that is not needed for a demo deployment.

## Technology

| Layer | Tools |
|---|---|
| Backend | FastAPI, uvicorn, httpx, pydantic-settings |
| Science | astropy (FITS, WCS, coordinates), numpy, scipy (`ndimage`) |
| Storage | SQLite, cachetools |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, react-router, i18next (EN/AZ), Recharts, Canvas 2D |
| Quality | pytest (offline, with real FITS fixtures), ESLint 9, `tsc` |
| Deployment | Docker, nginx |
