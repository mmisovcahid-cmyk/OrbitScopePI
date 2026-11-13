"""Tests on REAL SPHEREx Level-2 cutouts (offline fixtures).

The fixtures are compact cutouts of Epsilon Indi B (a T-dwarf binary) from detector D4,
exactly as the archive service stores them (IMAGE, FLAGS, VARIANCE, ZODI, WCS-WAVE; PSF cube
dropped):

* ``*_ch4``    2026-04, wavelength at the source 3.28 um - inside the methane band
* ``*_cont``   2026-04, 3.74 um - next to the band
* ``*_nowave`` 2025-04, an exposure whose wavelength table cannot be evaluated at the source
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.services import spherex_archive as sa
from app.services.target_resolver import find_builtin

FIX = Path(__file__).parent / "fixtures"


def _load(name: str, obs: str) -> sa.Cutout:
    rec = sa.FrameRecord(obs, "spherex_qr2", 4, 0.0, 2.42, 3.82)
    return sa.SpherexArchive._read_cutout(FIX / f"spherex_epsindib_D4_{name}.fits", rec)


def _target_at(c: sa.Cutout) -> tuple[float, float]:
    t = find_builtin("eps indi b")
    return sa.propagate(t["ra"], t["dec"], t["pmra"], t["pmdec"], t["ref_epoch"], sa.mjd_to_year(c.mjd))


@pytest.fixture(scope="module")
def ch4() -> sa.Cutout:
    return _load("ch4", "2026W17_1B_0337_3")


@pytest.fixture(scope="module")
def cont() -> sa.Cutout:
    return _load("cont", "2026W16_2A_0434_2")


def test_cutout_structure(ch4: sa.Cutout) -> None:
    assert ch4.image.ndim == 2 and ch4.image.shape == ch4.flags.shape == ch4.variance.shape
    assert ch4.url.startswith("https://irsa.ipac.caltech.edu/ibe/data/spherex/")
    assert 61100 < ch4.mjd < 61200  # April 2026
    assert np.isfinite(ch4.image).mean() > 0.9
    # header bit definitions were read from the FLAGS extension
    assert ch4.flag_bits["OVERFLOW"] == 1 and ch4.flag_bits["SOURCE"] == 21


def test_lvf_wavelength_is_inside_detector_band(ch4: sa.Cutout, cont: sa.Cutout) -> None:
    for c in (ch4, cont):
        x, y = c.wcs.world_to_pixel_values(*_target_at(c))
        lam = c.wavelength_at(float(x), float(y))
        assert lam is not None and 2.42 <= lam <= 3.82
    assert ch4.wavelength_at(*map(float, ch4.wcs.world_to_pixel_values(*_target_at(ch4)))) == pytest.approx(3.28, abs=0.02)


def test_target_is_a_strong_source_at_predicted_position(cont: sa.Cutout) -> None:
    """WCS + proper motion put the T dwarf on a >20-sigma source whose centroid agrees within 1 px."""
    from app.pipeline.moving_objects import refine_centroid, robust_sigma

    x, y = (float(v) for v in cont.wcs.world_to_pixel_values(*_target_at(cont)))
    img = np.nan_to_num(cont.image - np.nanmedian(cont.image))
    xi, yi = int(round(x)), int(round(y))
    peak = img[yi - 1:yi + 2, xi - 1:xi + 2].max()
    assert peak > 20 * robust_sigma(img)
    cx, cy = refine_centroid(img, x, y)
    assert abs(cx - x) < 1.0 and abs(cy - y) < 1.0


def test_photometry_shows_methane_absorption(ch4: sa.Cutout, cont: sa.Cutout) -> None:
    p_band = sa.aperture_photometry(ch4, *_target_at(ch4))
    p_cont = sa.aperture_photometry(cont, *_target_at(cont))
    assert not p_band["flagged"] and not p_cont["flagged"]
    assert p_band["flux_mjy"] > 10 * p_band["err_mjy"]
    # T dwarf: strong CH4 absorption at 3.3 um, bright around 3.7-4 um
    assert p_cont["flux_mjy"] / p_band["flux_mjy"] > 2.5


def test_missing_wavelength_is_flagged_not_dropped() -> None:
    c = _load("nowave", "2025W17_4B_0077_2")
    p = sa.aperture_photometry(c, *_target_at(c))
    assert p is not None
    assert p["wavelength_um"] is None and p["flagged"] is True
    assert p["flux_mjy"] is not None


def test_reprojection_of_real_cutout_puts_target_at_grid_position(cont: sa.Cutout) -> None:
    ra, dec = _target_at(cont)
    out_wcs = sa.make_target_wcs(ra, dec, 15, sa.NATIVE_PIXSCALE_ARCSEC)
    yy, xx = np.mgrid[0:15, 0:15]
    wr, wd = out_wcs.pixel_to_world_values(xx, yy)
    img, var, mask, _ = sa.reproject_cutout(cont, wr, wd)
    y, x = np.unravel_index(np.nanargmax(img), img.shape)
    assert abs(x - 7) <= 1 and abs(y - 7) <= 1
    assert np.isfinite(img).mean() > 0.8
