# OrbitScope — Known Limitations and Future Work

## Scientific limitations

1. **Bright, saturated stars and astrometry.** Barnard's Star, RW Aurigae and R Draconis saturate the SPHEREx detectors in most bands.
   - They are shown in Blink, with the cores filled for display.
   - They are excluded from the proper-motion measurement, because a saturated centroid is not reliable.
   - Their photometry points are returned with `flagged: true`.
2. **Faint asteroids.** The single-exposure search reliably recovers objects to roughly V ≈ 15–16 in the near-infrared bands.
   - 626 Notburga (V = 13.5) is recovered.
   - Dworetsky (V ≈ 17.2) in the same field is not.
3. **Very slow movers (Planet Nine class).** Asteroid linking works within one ~7-minute visit plus joins inside one survey pass.
   - An object moving a few arcseconds per day is not linked.
   - Proper-motion search across passes only follows sources detected in every pass.
   - A distant planet would need a dedicated multi-pass "shift-and-stack" search.
4. **Pixel scale.** SPHEREx pixels are 6.2″. Astrometric precision comes from centroiding many photons (a noise floor of a few tenths of a pixel), not from resolution. Crowded fields blend sources.
5. **Wavelength-dependent appearance.** The wavelength of a source changes between exposures, because each exposure puts it on a different part of the LVF filter.
   - The detection noise model absorbs this.
   - Strongly variable spectra (e.g. emission-line objects) can still leave residuals.
6. **Planet Nine clustering test.** The Rayleigh test does not model survey selection bias. On the complete JPL sample the clustering is much weaker (p ≈ 0.02) than on the 20-object literature sample (p ≈ 5×10⁻⁴). Neither is evidence of the planet itself.
7. **Faint targets.** Below S/N ≈ 10 in the mean image a source is only measured when it is the requested target (forced astrometry); the blind search cannot find such objects. WISE 0855 is just above that limit with the full DR1 coverage (7.6σ motion) and below it with fewer exposures.

## Data and service limitations

- **SPHEREx coverage.** Coverage grows with each survey pass. Some fields have only one pass; a proper-motion search there returns no candidates, because it needs at least two epochs.
- **External services.** IRSA, JPL, ESA and CDS occasionally return 5xx or time out.
  - OrbitScope retries, shows an explanation and never substitutes invented data.
  - The five challenge targets resolve offline.
  - `scripts/prewarm.py` caches their images in advance.
- **First view of a new field** takes 30–90 s while cutouts download. Background jobs show progress and can be cancelled. The five challenge targets are downloaded in advance (`scripts/prewarm.py`, or automatically at startup in Docker).
- **Offline (Raspberry Pi without internet).** Only fields, objects and orbit samples fetched before are available, as labelled copies of the real answers. A coverage list reused offline may miss frames released since. Ephemerides, "known objects in field" and the Aladin sky view need internet. See [RASPBERRY_PI.md](RASPBERRY_PI.md).
- **Withdrawn archive files.** IRSA lists frames of superseded quick releases (QR2) whose files no longer exist. OrbitScope learns this on the first request and replaces those frames; until then a new field may briefly have fewer frames.

## Infrastructure limitations

- **Raspberry Pi hardware.** The Pi scripts (`deploy/pi/`) have only been checked for syntax so far, not run on a real Pi 5. The SD card holds at most about 6 GB of cutouts (`SPHEREX_CACHE_MAX_MB`).
- **Single process.** Jobs and rate-limit counters are in memory, which is correct for one backend process. Running several replicas would need Redis or similar.
- **No user accounts.** Candidate reviews are shared by everyone using the instance. On a public deployment set `REVIEW_TOKEN`: then only people who know the team's token can save reviews; everyone else can still browse.
- **Minor Planet Center.** Candidates export as CSV, but reporting requires the team's own MPC observatory code and follow-up observations.

## Future work

- [ ] Shift-and-stack search across passes, for slow outer-Solar-System objects.
- [ ] Forced photometry for saturated stars, using the PSF wings.
- [x] Aladin Lite panel with the SPHEREx footprint next to the cutout viewer.
- [x] Wavelength band filter in Blink (e.g. 3.2–3.45 µm for CH₄).
- [x] Forced astrometry of the requested target (faint targets such as WISE 0855).
- [ ] Automatic re-check of saved candidates when a new SPHEREx release appears.
- [ ] Frontend unit and end-to-end tests (Vitest / Playwright).
