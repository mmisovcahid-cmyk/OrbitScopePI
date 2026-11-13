# OrbitScope — Data sources and external APIs

All services below are **public and need no API key, account or registration**.
OrbitScope calls them directly from the backend. Results are cached on disk or in memory, so repeated views are fast and the services are not overloaded.

| Service | Endpoint | Used for | Pages | Key? |
|---|---|---|---|---|
| NASA/IPAC IRSA TAP | `irsa.ipac.caltech.edu/TAP/sync` (`spherex.obscore`) | Which SPHEREx exposures cover a position | Blink, Detection, Comparison, Sky Explorer | No |
| NASA/IPAC IRSA datalink | `irsa.ipac.caltech.edu/datalink/links/spherex` | Level-2 FITS URL of each exposure | (same) | No |
| NASA/IPAC IRSA IBE cutouts | `irsa.ipac.caltech.edu/ibe/data/spherex/...?center=&size=` | Real SPHEREx image cutouts (IMAGE, FLAGS, VARIANCE, ZODI, WCS-WAVE) | (same) + photometry | No |
| NASA/IPAC IRSA TAP | `catwise_2020` | Infrared reference stars and proper motions | Blink overlay, Detection (PM) | No |
| ESA Gaia archive TAP | `gea.esac.esa.int/tap-server/tap/sync` (`gaiadr3.gaia_source`) | Reference stars, proper motions | Blink overlay, Detection (PM) | No |
| NASA/JPL SBDB | `ssd-api.jpl.nasa.gov/sbdb.api` | Orbits, physical data, discovery, close approaches | Catalog, Planet X | No |
| NASA/JPL Horizons | `ssd.jpl.nasa.gov/api/horizons.api` | Current position / ephemeris | Catalog | No |
| NASA/JPL SBDB Query API | `ssd-api.jpl.nasa.gov/sbdb_query.api` | Every extreme TNO (a ≥ 150 AU, q ≥ 30 AU) for the clustering test | Planet X | No |
| CDS Aladin Lite + HiPS | `aladin.cds.unistra.fr` (script loaded on demand in the browser) | Sky context: DSS2, 2MASS, AllWISE around the target | Blink | No |
| NASA/JPL SB Ident | `ssd-api.jpl.nasa.gov/sb_ident.api` | Known asteroids/comets in a field at a time | Detection, Catalog field search | No |
| CDS Sesame (+ CfA mirror) | `cds.unistra.fr/cgi-bin/nph-sesame`, `vizier.cfa.harvard.edu/viz-bin/nph-sesame` | Object name to coordinates and proper motion | Name search everywhere | No |
| NED name resolver | `ned.ipac.caltech.edu/srs/ObjectLookup` | Fallback name resolver | Name search | No |

## Behaviour when a service is down

- **Real-data pages never substitute invented values.** If IRSA or JPL fails, the page shows an explanation (backend HTTP 502). Earlier versions silently fell back to simulated objects; that behaviour was removed.
- **Retries:**
  - IRSA cutouts: up to 3 attempts with backoff, on HTTP 5xx.
  - JPL requests: at most 4 at a time, retried on 429/503.
- **CatWISE / Gaia overlay:** failures only hide the overlay; the images still load.
- **Name search:** if CDS Sesame is down, the CfA mirror is tried, then NED. The five challenge targets are built in with Gaia DR3 / SIMBAD positions and proper motions, so they always resolve.

## No simulated data

The original prototype had `/api/v1/sky`, `/api/v1/observations` and `/api/v1/detection` endpoints that generated simulated data. They and their generators were removed, so every endpoint now serves real data or an error.

## Rate limit (public deployments)

Requests that make the backend download from these services (blink, photometry, detection, overlay, catalog, clustering) are limited per client: `RATE_LIMIT_PER_MINUTE`, default 60. This protects both the OrbitScope server and the public archives. Status, job polling and saved candidates are not limited.

## What would need the team's own action (not automatable here)

- **Reporting a confirmed new object to the Minor Planet Center:** this requires an MPC observatory/submitter registration and follow-up astrometry. OrbitScope exports candidate astrometry as CSV for that purpose.
- **Deployment to a public URL:** `docker compose up --build` is ready. A host (VM / cloud) and a domain have to be chosen by the team. After deploying, run `docker compose exec backend python -m scripts.prewarm` once. The Docker images have not been built on this development machine because Docker is not installed here.
