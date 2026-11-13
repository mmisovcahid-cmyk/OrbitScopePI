# 🔭 OrbitScope

## SPHEREx Time-Domain Sky Monitoring & Moving Object Detection

<div align="center">

**Göyü kəşf edin. Dəyişiklikləri aşkar edin. Göy cisimlərini izləyin. Naməlumu araşdırın.**

*Explore the sky. Detect changes. Track celestial objects. Investigate the unknown.*

</div>

---

OrbitScope is a public web tool for the NASA Space Apps challenge *"Planet X and SPHEREx"*. You enter a sky position or an object name, and it shows the **real SPHEREx images** of that place as a short time series ("blink"), so that moving and changing objects stand out. It also searches the same images for asteroids and high-proper-motion stars and checks every result against NASA/JPL, Gaia and CatWISE.

Every page uses **real public data**: NASA/IPAC IRSA, NASA/JPL and ESA. No API keys are needed, and no simulated fallbacks exist. If a service is down, the page explains that instead of inventing values.

## 🚀 Pages

| Page | What it does |
|---|---|
| **Blink** (`/`) | SPHEREx image time series of any position.<br>Views: blink, difference, motion colour and stack.<br>Choice of detector (D1–D6, 0.75–5 µm), **wavelength band** (e.g. CH₄ 3.2–3.45 µm, applied per exposure) and field of view.<br>Gaia DR3 / CatWISE2020 overlays moved to each frame's date.<br>Quality flags, proper-motion marker, GIF export and links to the source FITS files.<br>Spectrum + light curve from up to 96 exposures.<br>**Sky context** panel (CDS Aladin Lite: DSS2 / 2MASS / AllWISE) with the SPHEREx footprint. |
| **Detection** (`/detection`) | Moving-object search on real exposures: asteroids/comets, or proper motion.<br>Checks against JPL SB Ident, Gaia and CatWISE; the requested target is always measured and its motion compared with the catalog.<br>Every rejected track says why (zig-zag, brightness jump, …).<br>Candidate review (real / artifact / unsure, optional team token) and CSV export. |
| **Sky Explorer** (`/dashboard`) | All-sky map of every saved run and candidate, review counts, live service status. |
| **Comparison** (`/comparison`) | Two real SPHEREx survey passes of one field side by side, with a difference image. |
| **Analysis** (`/analysis/:id`) | One saved candidate: track, metrics and catalog matches, with links to the same field in Blink and to JPL. |
| **Catalog** (`/catalog`) | Live JPL SBDB lookup (orbit, physical data, close approaches), Horizons ephemeris, known objects in a field (SB Ident). |
| **Planet X** (`/planetx`) | Live Rayleigh test for orbital clustering of extreme TNOs, on **every** qualifying object in JPL SBDB (59) and on the 20-object literature sample, side by side. Published evidence and search corridors are labelled as literature. |
| **Embed** (`/embed?...`) | iframe-friendly Blink for other websites. |

The interface is bilingual (English / Azərbaycan dili). The URL holds the full query, so every view can be shared or embedded:

- `http://localhost:5173/?target=Barnard%27s+Star&fov=0.1&det=3`
- `http://localhost:5173/embed?target=WISE+0855-0714&det=6`

## ✅ Validated on real SPHEREx data

| Test | Result |
|---|---|
| 626 Notburga (asteroid, V = 13.5) | 8 detections, 1.6″ from the JPL position, 58.5″/h (Detection preset, pass 0) |
| False movers | 0 `unknown_mover` in both survey passes of the Notburga field and in the ε Indi B field (before the quality rules: 8 + 2) |
| ε Indi B (brown dwarf) | proper motion 4.10″/yr at PA 122° (catalog 4.68″/yr, 122°), 15σ, matched to Gaia DR3 |
| WISE 0855−0714 (coldest known brown dwarf) | 8.2″/yr at PA 286° (catalog 8.15″/yr, 275°), 7.6σ, matched to CatWISE2020; the target check confirms it |
| ε Indi B spectrum (95 exposures) | 3.2–3.45 µm 5× fainter than 3.6–4.1 µm (CH₄); dips at 1.4 µm (H₂O) and 4.6 µm (CO) |
| Planet X test (live JPL orbits) | literature sample (20): ϖ ≈ 68°, p ≈ 5×10⁻⁴; complete sample (59): p ≈ 0.02 — selection matters |

All numbers were re-measured on 2026-11-13 with the code in this repository; `scripts/prewarm.py` reproduces the three Detection examples.

Method details: [docs/METHODOLOGY.md](docs/METHODOLOGY.md). Honest limitations: [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## 🍓 Raspberry Pi 5 (main target)

OrbitScope is built to run on a single **Raspberry Pi 5 (8 GB)**. One Pi runs:

- the backend and the web site;
- a full-screen **kiosk** on its own screen, which scales to any size and supports touch;
- its own **Wi-Fi network**: visitors scan a QR code on the screen to join and open the site on their phones.

With the demo data downloaded once, it also works **without internet**. It then shows only real data saved earlier, labelled with its date.

```bash
git clone https://github.com/mmisovcahid-cmyk/OrbitScopePI.git && cd OrbitScopePI
sudo deploy/pi/install.sh --prewarm      # or: --docker, --no-ap, --no-kiosk
sudo reboot
```

Everything about the Pi (hardware, access point, offline mode, kiosk, settings, troubleshooting) is in [docs/RASPBERRY_PI.md](docs/RASPBERRY_PI.md).

## 🔧 Running locally (PC development)

Requirements: **Python 3.10+**, **Node.js 18+**.

**Windows, one click:** run `start.bat` (or `start.ps1`). It opens the backend on :8000 and the frontend on :5173 in two windows.

**Manually:**

```bash
cd backend
pip install -r requirements.txt
copy .env.example .env      # Linux/macOS: cp .env.example .env
python run.py               # http://localhost:8000, API docs at /docs
```

```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

### Before a demo: fill the cache

The first view of a new field downloads 16–96 image cutouts from IRSA (30–90 s). Run this once before presenting (about 8–10 minutes): all six detectors of the five challenge targets, their spectra and the three Detection examples are then served instantly from disk.

```bash
cd backend
python -m scripts.prewarm
```

Options: `--targets barnard,wise-0855`, `--quick` (default detector only), `--no-photometry`, `--no-demo-runs`. In Docker this runs by itself at startup (`PREWARM_ON_STARTUP=true`).

## 🐳 Docker (public deployment)

```bash
docker compose up --build
```

- **Serving:** open **http://localhost:8080**. nginx serves the built frontend and proxies `/api` to the backend.
- **Data:** the SPHEREx cache and the candidate database live in the `orbitscope-data` volume.
- **Production defaults:**
  - `DEBUG=false`.
  - The five challenge targets are downloaded in the background right after startup (`PREWARM_ON_STARTUP`).
  - Set `REVIEW_TOKEN` (e.g. in a `.env` file next to `docker-compose.yml`) so only the team can mark candidates real/artifact.
  - Expensive requests (blink, photometry, detection, catalog) are limited to 60 per client per minute (`RATE_LIMIT_PER_MINUTE`).
  - The client IP is taken from nginx.
- **Cache warm-up by hand** (already done at startup):

  ```bash
  docker compose exec backend python -m scripts.prewarm
  ```

## 🏗️ Structure

```
backend/
  app/api/routes/   spherex, jobs, catalog, planetx, system
  app/services/     spherex_archive, target_resolver, catalog_overlay, small_bodies,
                    jpl_catalog, etno, detection_service, candidate_store, jobs
  app/pipeline/     moving_objects (asteroid + proper-motion search)
  app/core/         config, progress, rate limit, cache, logging
  scripts/          prewarm
  app/core/offline.py, connectivity.py   offline snapshots + internet probe (Raspberry Pi demo)
deploy/pi/          install.sh, Wi-Fi access point (orbitscope-net), kiosk, systemd, nginx, orbitscope-check
  tests/            offline tests incl. real SPHEREx FITS fixtures
frontend/src/
  pages/            Blink, Embed, Detection, Dashboard, Comparison, Analysis, Catalog, PlanetX, About
  components/       blink viewer, photometry panel, all-sky map, job progress, layout
  lib/              SPHEREx decoding/stretch/WCS, background jobs
  i18n/             en.json, az.json
docs/               RASPBERRY_PI, METHODOLOGY, ARCHITECTURE, DATA_SOURCES, LIMITATIONS, REFERENCES
```

Architecture and request flow: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Every external service: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## 🧪 Quality checks

```bash
cd backend && pytest tests/ -q
```

```bash
cd frontend && npm run lint && npm run build
```

The backend tests run offline. They include real SPHEREx cutouts (`backend/tests/fixtures`) and synthetic moving-object scenes.

## ⚠️ Data transparency

- **Real data only:** every number on screen comes from IRSA, JPL, ESA, CDS or NED, with the source named.
- **Candidates are not discoveries:** a candidate needs independent confirmation and an MPC report by a registered observer.
- **Planet Nine is a hypothesis:** the Planet X page tests orbital clustering. It does not claim to find the planet.

## 📚 References

- [NASA SPHEREx](https://spherex.caltech.edu/) · [IRSA SPHEREx data](https://irsa.ipac.caltech.edu/Missions/spherex.html)
- [JPL Small-Body Database](https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html) · [JPL Horizons](https://ssd.jpl.nasa.gov/horizons/)
- [Gaia DR3](https://www.cosmos.esa.int/web/gaia/dr3) · [CatWISE2020](https://irsa.ipac.caltech.edu/data/WISE/CatWISE/)
- Batygin & Brown (2016), [AJ 151, 22](https://doi.org/10.3847/0004-6256/151/2/22)
- Full list: [docs/REFERENCES.md](docs/REFERENCES.md)

## 📄 License

MIT for the OrbitScope code (see [LICENSE](LICENSE)). NASA, JPL and ESA data are used under their open-data policies.
