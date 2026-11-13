# OrbitScope - Data Sources & References

## Primary Data Sources

### NASA SPHEREx Mission
- **Mission Page:** https://spherex.caltech.edu/
- **Data Archive:** NASA/IPAC Infrared Science Archive (IRSA) - https://irsa.ipac.caltech.edu/
- **Spectral Range:** 0.75 – 5.0 μm (near-infrared)
- **Spectral Bands:** 102
- **Angular Resolution:** ~6.2 arcseconds
- **Sky Coverage:** Full sky, multiple epochs over 2-year nominal mission
- **Data Access:** IRSA TAP service

### JPL Small-Body Database (SBDB)
- **Web Interface:** https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html
- **API Documentation:** https://ssd-api.jpl.nasa.gov/doc/sbdb.html
- **API Endpoint:** https://ssd-api.jpl.nasa.gov/sbdb.api
- **Content:** Orbital elements, physical parameters, discovery info for asteroids and comets

### JPL Horizons System
- **Web Interface:** https://ssd.jpl.nasa.gov/horizons/
- **API Documentation:** https://ssd-api.jpl.nasa.gov/doc/horizons.html
- **API Endpoint:** https://ssd.jpl.nasa.gov/api/horizons.api
- **Content:** Precision ephemerides for solar system bodies

## Scientific References

### Planet Nine Hypothesis

1. Batygin, K. & Brown, M. E. (2016). "Evidence for a Distant Giant Planet in the Solar System." *The Astronomical Journal*, 151(2), 22.
   DOI: [10.3847/0004-6256/151/2/22](https://doi.org/10.3847/0004-6256/151/2/22)

2. Brown, M. E. & Batygin, K. (2021). "The Orbit of Planet Nine." *The Astronomical Journal*, 162(5), 219.
   DOI: [10.3847/1538-3881/ac2056](https://doi.org/10.3847/1538-3881/ac2056)

3. Trujillo, C. A. & Sheppard, S. S. (2014). "A Sedna-like body with a perihelion of 80 astronomical units." *Nature*, 507, 471–474.
   DOI: [10.1038/nature13156](https://doi.org/10.1038/nature13156)

4. Batygin, K., Adams, F. C., Brown, M. E., & Becker, J. C. (2019). "The planet nine hypothesis." *Physics Reports*, 805, 1–53.
   DOI: [10.1016/j.physrep.2019.01.009](https://doi.org/10.1016/j.physrep.2019.01.009)

### Planet Nine: selection-bias critiques

5. Shankman, C. et al. (2017). "OSSOS. VI. Striking Biases in the Detection of Large Semimajor Axis Trans-Neptunian Objects." *AJ*, 154, 50.
   DOI: [10.3847/1538-3881/aa7aed](https://doi.org/10.3847/1538-3881/aa7aed)

6. Napier, K. J. et al. (2021). "No Evidence for Orbital Clustering in the Extreme Trans-Neptunian Objects." *PSJ*, 2, 59.
   DOI: [10.3847/PSJ/abe53e](https://doi.org/10.3847/PSJ/abe53e)

### SPHEREx and reference catalogs

7. Doré, O. et al. (2014). "Cosmology with the SPHEREX All-Sky Spectral Survey." arXiv:[1412.4872](https://arxiv.org/abs/1412.4872)

8. Gaia Collaboration, Vallenari, A. et al. (2023). "Gaia Data Release 3: Summary of the content and survey properties." *A&A*, 674, A1.
   DOI: [10.1051/0004-6361/202243940](https://doi.org/10.1051/0004-6361/202243940)

9. Marocco, F. et al. (2021). "The CatWISE2020 Catalog." *ApJS*, 253, 8.
   DOI: [10.3847/1538-4365/abd805](https://doi.org/10.3847/1538-4365/abd805)

### Challenge test targets

10. Luhman, K. L. (2014). "Discovery of a ~250 K Brown Dwarf at 2 pc from the Sun." *ApJL*, 786, L18.
    DOI: [10.1088/2041-8205/786/2/L18](https://doi.org/10.1088/2041-8205/786/2/L18)

11. Scholz, R.-D. et al. (2003). "ε Indi B: A new benchmark T dwarf." *A&A*, 398, L29.
    DOI: [10.1051/0004-6361:20021847](https://doi.org/10.1051/0004-6361:20021847)

### Methods and software

12. Mardia, K. V. & Jupp, P. E. (2000). *Directional Statistics.* Wiley. (Rayleigh test for circular clustering)

13. Astropy Collaboration (2022). "The Astropy Project: Sustaining and Growing a Community-driven Open-source Project and the Latest Major Release (v5.0) of the Core Package." *ApJ*, 935, 167.

14. Virtanen, P. et al. (2020). "SciPy 1.0: fundamental algorithms for scientific computing in Python." *Nature Methods*, 17, 261–272.

## Data Licensing

- NASA SPHEREx, IRSA and JPL data are used under NASA's open data policy; ESA Gaia data under the Gaia data licence (CC BY-SA 3.0 IGO), with acknowledgement.
- The OrbitScope code is MIT-licensed (see `LICENSE`).
