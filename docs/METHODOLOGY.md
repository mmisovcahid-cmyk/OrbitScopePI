# OrbitScope — Scientific Methodology

OrbitScope works only on real public data. Its sources are SPHEREx Level-2 images from NASA/IPAC IRSA, reference catalogs (Gaia DR3, CatWISE2020) and NASA/JPL small-body services. No page substitutes simulated values when a service is unavailable: the user sees an explanation instead (HTTP 502). Every API endpoint and service is listed in [DATA_SOURCES.md](DATA_SOURCES.md).

Detected objects are **candidates**, not discoveries. Planet Nine is presented as an unconfirmed hypothesis.

## 1. SPHEREx data access

| Step | Method |
|---|---|
| Which exposures cover a position | IRSA TAP: `CONTAINS(POINT(ra,dec), s_region)` on `spherex.obscore`. Collections are matched by the `spherex` prefix, so new data releases appear without code changes. |
| File location | IRSA datalink gives the Level-2 FITS URL of each exposure. |
| Pixels | IBE cutout service (`?center=&size=`). Only `IMAGE`, `FLAGS`, `VARIANCE`, `ZODI` and `WCS-WAVE` are kept; the ~5 MB PSF cube is dropped. Cutouts are cached on disk with LRU pruning. |
| Wavelength | SPHEREx uses linear variable filters (LVF): the wavelength changes across each detector. The wavelength of any pixel is read from the `WCS-WAVE` (-TAB) lookup table. Detectors D1–D6 cover 0.75–5.0 µm in 102 spectral channels. |
| Withdrawn files | IRSA keeps the metadata of superseded quick releases (e.g. QR2), but most of their files are gone. A frame with no Level-2 file is remembered; a collection where ≥ 80 % of ≥ 10 looked-up files are missing is skipped, and lost frames are replaced by others in a second download round. |

## 2. Image preparation (`spherex_archive.py`)

1. **Background:**
   - Subtract the `ZODI` model (zodiacal light).
   - Subtract a robust local sky level.
2. **Masking:** pixels with problem `FLAGS` bits are masked.
3. **Reprojection:** each cutout is resampled onto a common north-up gnomonic (TAN) grid.
   - Uses the full SIP distortion WCS with `scipy.ndimage.map_coordinates`.
   - All frames of one target share the grid, so a static star stays on the same pixel.
4. **Coadd per survey pass:**
   - Frames more than 30 days apart are separate passes.
   - Within a pass, frames are combined with inverse-variance weights.
   - A pixel is masked when fewer than half of the exposures are valid there.
5. **Saturated cores:** the cores of very bright stars are saturated (OVERFLOW). They are filled from the surroundings for display only and are never used for measurements.
6. **High proper-motion targets:** the position is propagated from the catalog epoch to each SPHEREx epoch, so the target marker follows the star.
7. **Wavelength band (optional):** a band such as 3.2–3.45 µm (CH₄) is applied *per exposure*: only exposures whose LVF wavelength at the target falls inside it are stacked. Detectors whose range does not overlap the band are not downloaded.
8. **Delivery:** frames are sent to the browser as float32. Stretch, colour map, difference and motion-colour views are computed client-side.

## 3. Spectrum and light curve (`photometry`)

- **Exposure selection:** up to 96 exposures, spread over all detectors and over time.
- **Measurement:** aperture photometry with local-annulus background subtraction and an error from `VARIANCE`.
- **Wavelength per point:** the LVF wavelength at the target pixel. One measurement set therefore gives both a **spectrum** (flux vs. wavelength) and a **light curve** (flux vs. time).
- **Flagged points:** saturated or mostly masked apertures are returned with `flagged: true` instead of being dropped silently.
- **Real-data result (ε Indi B, 95 exposures):** median 9.8 mJy at 3.2–3.45 µm (2 points) against 52.7 mJy at 3.6–4.1 µm (11 points) — the CH₄ band of a T dwarf; also dips at 1.4 µm (H₂O) and 4.6 µm (CO). The CH₄ band has few points because only a few exposures place the target there; the band filter in Blink shows exactly those.

## 4. Moving-object search (`pipeline/moving_objects.py`)

### 4.1 Asteroids and comets (`search=asteroids`)

**Input:** the individual exposures of one survey pass.
- SPHEREx observes in visits of about 4 exposures within about 7 minutes; `select_sequences` keeps those visits intact.
- Paired detectors D1/D4, D2/D5 and D3/D6 expose simultaneously.

**Steps:**
1. **Static-sky template:** the median image per detector. It is subtracted from each exposure.
2. **Noise model:** `σ² + (0.15 · template)²`.
   - The second term absorbs brightness changes of stars caused by the LVF wavelength shift between exposures.
   - Residuals are smoothed with a 1-px Gaussian (matched filter); peaks above 5σ are detections.
3. **Noisy-frame rejection:** frames whose residual noise exceeds 3× the detector median are skipped.
4. **Linking within a visit:**
   - Detections within `VISIT_WINDOW_DAYS = 0.01` are linked by union-find into straight-line tracklets.
   - Each tracklet needs at least 3 detections and an RMS of at most 0.8 px.
5. **Joining across visits:** tracklets are joined when a common linear motion fits all of them (`MAX_JOIN_RMS_PX = 1.5`).
6. **Quality rules** (`track_quality`, `mover_quality_ok`). On real data the blind linking also produced straight-looking chance alignments; an `unknown_mover` must therefore also pass:
   - *steady motion:* within one visit, the net displacement is ≥ 5× the scatter around the fitted line (fixed residuals "zig-zag" around one spot);
   - *scatter* ≤ 2× the expected centroid error (max(0.15 px, 1.5/z));
   - *brightness* within one detector varies by ≤ 3× (an asteroid does not jump 10× in two minutes);
   - *completeness:* a bright detection (z ≥ 15) must appear in at least half of its visit's exposures in that detector;
   - ≥ 8 px from the cutout edge; three-point tracks need mean S/N ≥ 8 (four-point ≥ 5.5).
   Tracks that fail are kept as `low_confidence` with the reasons listed (shown in the UI); known-asteroid matching still applies to them.
7. **Stationary rejection:** detector persistence and variable stars produce residuals at a fixed position.
   - `recurrence()` checks whether the same position is significant in clearly different visits (gap > 0.05 d, threshold max(4, 0.3·mean z)).
   - A "parked" rule catches zero-motion tracks.
   - Both cases are classified `stationary_transient`, not movers.
8. **Known objects:** NASA/JPL SB Ident is queried once per visit cluster, and positions are extrapolated linearly with the returned rates.
   - A track counts as recovering a known object only if both position (≤ 5 px ≈ 30″) and rate agree.
   - Otherwise it stays an `unknown_mover` candidate.

**Validation on real data (2026-11-13):** 626 Notburga (V = 13.5) is recovered with 8 detections, 1.6″ from the JPL position and 58.5″/h. Before the quality rules the Notburga field produced 8 (pass 1) and 2 (pass 0) `unknown_mover`s that matched nothing; with them, 0 in both passes and in the ε Indi B field, while Notburga is still recovered. Dworetsky (V ≈ 17.2) in the same field is below the detection limit.

### 4.2 Proper motion (`search=proper_motion`)

**Input:** one deep stack per survey pass (up to 16 exposures), typically about 6 months apart.

**Steps:**
1. **Source selection:** isolated, unsaturated sources with S/N ≥ 10 are centroided in every epoch with a re-centred Gaussian fit (`refine_centroid`).
2. **Registration offset:** the global frame-to-frame offset is measured on all stars and removed.
3. **Noise floor:** the scatter of the static stars gives the astrometric noise floor. Each source adds an error term of 1.5/SNR px.
4. **Classification:**
   - A source is reported as moving when its shift is above 5σ and at least 0.25 px, and three or more epochs lie on a straight line (scatter ≤ 3× the centroid error; out-and-back jumps are blends or edge effects).
   - It is reported as variable when its flux ratio between epochs is at least 1.6.
5. **Catalog check:** Gaia DR3 and CatWISE2020 positions are propagated to the SPHEREx epoch.
   - A catalog match must agree in both position and proper-motion vector.
   - The match radius grows for fast catalog movers.

6. **The requested target is always measured** ("forced" astrometry). A target may be too faint for the blind search (WISE 0855 has S/N ≈ 6–8 per pass at 4.6 µm, below the blind threshold of 10). Its centroid is started from the mean of its predicted positions — never from a per-epoch catalog prediction — so the measured motion is independent of the catalog. It is then compared with the catalog proper motion: testing one source against a predicted motion needs no look-elsewhere penalty, so ≥ 3σ plus agreement within 3 errors counts as *confirmed*.

**Validation on real data (2026-11-13):**
- ε Indi B: 4.10″/yr at PA 122° (catalog 4.68″/yr at 122°), 15σ, matched to Gaia DR3.
- WISE 0855−0714: 8.2″/yr at PA 286° (catalog 8.15″/yr at 275°), 7.6σ, rms about the line 0.04 px, matched to CatWISE2020 — confirmed by the target check. With fewer exposures per pass (e.g. while IRSA still listed withdrawn QR2 frames) it falls below the blind threshold; the forced measurement then still reports it (4.5σ in that test), which is why it was added.

Saturated stars are excluded from astrometry by design: Barnard's Star, RW Aur and R Dra. They are still shown in Blink.

### 4.3 Candidate handling

- **Storage:** runs and candidates are stored in SQLite (`candidate_store.py`) with metrics, recurrence data and catalog matches.
- **Review:** a human marks each candidate *real / artifact / unsure*.
- **Export:** each candidate's astrometry can be exported as CSV, the starting point for a Minor Planet Center report (submission requires the team's own MPC registration).

## 5. Live JPL catalog (`jpl_catalog.py`)

- **SBDB:** orbit, physical parameters, discovery circumstances and close approaches. An ambiguous name returns a list of matches.
- **Horizons:** observer ephemeris.
  - Asteroids are addressed by `DES=<spkid>;`, comets by `DES=<des>;CAP;`, and planets by their major-body ID.
  - The output is CSV with angles in degrees.
- **SB Ident:** known small bodies in a field at a given time, for the Catalog field search and the detection cross-check.

## 6. Planet Nine test (`etno.py`)

- **Hypothesis being tested:** extreme TNOs (a ≥ 150 AU, q ≥ 30 AU) cluster in orbital orientation (Batygin & Brown 2016).
- **Data:** the JPL SBDB Query API returns *every* known object with a ≥ 150 AU and q ≥ 30 AU (111 today). Orbits with condition code > 5 are too uncertain and are left out, leaving 59 — an objective sample. The 20 objects usually discussed in Planet Nine papers are analysed separately.
- **Statistic:** a Rayleigh test on the longitude of perihelion ϖ = Ω + ω, and separately on Ω and ω. A small p-value means the angles are not uniformly distributed.
- **Result on live orbits:** literature sample (20): mean ϖ ≈ 68°, p ≈ 5×10⁻⁴; complete sample (59): mean ϖ ≈ 49°, p ≈ 0.02. The clustering weakens markedly when nothing is hand-picked — the selection effect the critics describe, seen directly.
- **What it does not show:** the test does not address the observational selection bias discussed in the literature (e.g. Shankman et al. 2017, Napier et al. 2021), and it is not evidence for the planet itself. Search corridors and evidence cards on the page are taken from published papers and labelled as literature.

## 7. Reproducibility

- **Self-describing results:**
  - Every blink, photometry and detection response contains the exact IRSA file URLs, observation IDs, detector, epoch and pixel scale.
  - Detection runs also store all parameters.
- **Shareable state:** the Blink page URL encodes the full query (`target, ra, dec, fov, det, mode, per, max`).
- **Tests:** the backend tests include real SPHEREx cutouts (`backend/tests/fixtures`) and synthetic moving-object scenes, and run offline.
