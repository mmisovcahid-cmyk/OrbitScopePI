"""OrbitScope - Planet X / Planet Nine Research API Endpoints
Provides scientific evidence syntheses, extreme Trans-Neptunian Object (eTNO) catalogs, and predicted search corridors based on Batygin & Brown models.
"""
from __future__ import annotations

from typing import Any, List, Optional
from fastapi import APIRouter, HTTPException, Query

from app.services.etno import etno_analysis

from app.core.logging_config import get_logger
from app.models.schemas import (
    ApiResponse,
    PlanetXData,
    PlanetXEvidence,
    PlanetXPrediction,
    TNObject,
)

logger = get_logger("routes.planetx")

router = APIRouter(prefix="/api/v1/planetx", tags=["Planet X"])

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "evidence_success": "Planet Nine scientific evidence retrieved successfully",
        "tnos_success": "Extreme Trans-Neptunian Objects catalog retrieved successfully",
        "regions_success": "Predicted Planet Nine search regions retrieved successfully",
    },
    "az": {
        "evidence_success": "Doqquzuncu Planet elmi dəlilləri uğurla əldə edildi",
        "tnos_success": "Ekstremal Trans-Neptun Cisimləri kataloqu uğurla əldə edildi",
        "regions_success": "Proqnozlaşdırılan axtarış zonaları uğurla əldə edildi",
    },
}


def _get_msg(locale: str, key: str) -> str:
    loc = locale.lower() if locale else "en"
    return MESSAGES.get(loc, MESSAGES["en"]).get(key, MESSAGES["en"].get(key, ""))


# Theoretical Evidence Base
EVIDENCE_LIST: list[PlanetXEvidence] = [
    PlanetXEvidence(
        title="Physical Orbital Anti-Alignment of Extreme TNOs",
        title_az="Ekstremal Trans-Neptun Cisimlərinin Orbitlərinin Fiziki Əks-Düzülüşü",
        description="Extreme Trans-Neptunian Objects with semi-major axes a > 250 AU and perihelia q > 30 AU exhibit physical clustering of their longitudes of perihelion (varpi ≈ 241° ± 45°), anti-aligned with the predicted eccentric orbit of Planet Nine.",
        description_az="Böyük yarımoxu a > 250 AV və perigeli q > 30 AV olan ekstremal TNO-lar öz perigeli uzunluqlarında (varpi ≈ 241° ± 45°) statistik klasterləşmə nümayiş etdirir və Doqquzuncu Planetin proqnozlaşdırılan ekssentrik orbitinə əks istiqamətlənir.",
        evidence_type="orbital",
        strength="strong",
        reference="Batygin & Brown (2016), Astronomical Journal, 151:22",
        reference_url="https://doi.org/10.3847/0004-6256/151/2/22",
        year=2016,
    ),
    PlanetXEvidence(
        title="Clustering of Orbital Inclinations and Common Invariable Plane",
        title_az="Orbital Meyilliklərin Klasterləşməsi və Ümumi Dəyişməz Müstəvi",
        description="The orbital poles of extreme TNOs are concentrated in a tight sector of the celestial sphere, indicating that their orbital planes share a common inclination of i ≈ 15°–25° to the ecliptic plane.",
        description_az="Ekstremal TNO-ların orbital qütbləri göy sferinin məhdud sektorunda cəmlənmişdir; bu, onların orbital müstəvilərinin ekliptikaya nisbətən i ≈ 15°–25° meyilliyə malik ümumi perturbasiya müstəvisini paylaşdığını göstərir.",
        evidence_type="orbital",
        strength="strong",
        reference="Batygin, Adams, Brown & Becker (2019), Physics Reports, 805:1-53",
        reference_url="https://doi.org/10.1016/j.physrep.2019.01.009",
        year=2019,
    ),
    PlanetXEvidence(
        title="Clustering of Arguments of Perihelion",
        title_az="Perigeli Arqumentlərinin Klasterləşməsi",
        description="Original discovery by Trujillo & Sheppard revealed that extreme detached TNOs possess arguments of perihelion clustered around omega ≈ 318° ± 20°, suggesting a common resonant gravitational shepherd.",
        description_az="Trujillo & Sheppard tərəfindən aşkar edilmişdir ki, təcrid olunmuş ekstremal TNO-ların perigeli arqumentləri omega ≈ 318° ± 20° ətrafında toplanır və bu, ümumi qravitasiya tənzimləyicisinin varlığına işarə edir.",
        evidence_type="statistical",
        strength="moderate",
        reference="Trujillo & Sheppard (2014), Nature, 507:471–474",
        reference_url="https://doi.org/10.1038/nature13156",
        year=2014,
    ),
    PlanetXEvidence(
        title="Generation of Highly Inclined and Retrograde Kuiper Belt Objects",
        title_az="Yüksək Meyilli və Retroqrad Koyper Qursağı Cisimlərinin Yaranması",
        description="Planet Nine's secular gravitational perturbation induces high-inclination and retrograde orbits (such as 2015 BP519 and Drac) through Kozai-Lidov resonances operating beyond Neptune.",
        description_az="Doqquzuncu Planetin uzunmüddətli qravitasiya perturbasiyası Neptundan kənarda Kozai-Lidov rezonansları vasitəsilə yüksək meyillilikli və əks istiqamətdə fırlanan (məsələn, 2015 BP519) cisimlər yaradır.",
        evidence_type="gravitational",
        strength="strong",
        reference="Batygin & Morbidelli (2017), AJ 154:229",
        reference_url="https://doi.org/10.3847/1538-3881/aa937c",
        year=2017,
    ),
    PlanetXEvidence(
        title="Solar Obliquity of 6 Degrees",
        title_az="Günəşin 6 Dərəcəlik Əyilməsi (Obliquity)",
        description="The Sun's spin axis is tilted by 6° relative to the invariable plane of the Solar System. An inclined massive distant planet naturally exerts sufficient torque over 4.5 Gyr to produce this tilt.",
        description_az="Günəşin öz oxu ətrafında fırlanma oxu Günəş sisteminin dəyişməz müstəvisinə nisbətən 6° əyilmişdir. Uzaq və meyilli kütləvi planet 4.5 milyard il ərzində bu əyilməni izah edən qravitasiya momenti yaradır.",
        evidence_type="gravitational",
        strength="suggestive",
        reference="Bailey, Batygin & Brown (2016), AJ 152:126",
        reference_url="https://doi.org/10.3847/0004-6256/152/4/126",
        year=2016,
    ),
]

PREDICTIONS_LIST: list[PlanetXPrediction] = [
    PlanetXPrediction(
        parameter="Mass",
        parameter_az="Kütlə",
        value="5 – 10",
        unit="Earth Masses (M⊕)",
        uncertainty="±2 M⊕",
        source="Batygin, Brown et al. (2021 update)",
    ),
    PlanetXPrediction(
        parameter="Semi-major Axis",
        parameter_az="Böyük Yarımox",
        value="400 – 800",
        unit="Astronomical Units (AU)",
        uncertainty="±100 AU",
        source="Batygin & Brown (2016, 2021)",
    ),
    PlanetXPrediction(
        parameter="Eccentricity",
        parameter_az="Ekssentrisitet",
        value="0.2 – 0.5",
        unit="dimensionless",
        uncertainty="±0.1",
        source="Brown & Batygin (2021)",
    ),
    PlanetXPrediction(
        parameter="Orbital Inclination",
        parameter_az="Orbital Meyillik",
        value="15 – 25",
        unit="degrees (°)",
        uncertainty="±5°",
        source="Batygin & Brown (2016)",
    ),
    PlanetXPrediction(
        parameter="Apparent V Magnitude",
        parameter_az="Görünən V Ulduz Ölçüsü",
        value="22 – 25",
        unit="mag",
        uncertainty="dependent on distance and albedo",
        source="Fortney et al. (2016)",
    ),
]

TNOS_CATALOG: list[TNObject] = [
    TNObject(
        name="Sedna (90377)",
        designation="2003 VB12",
        semi_major_axis_au=506.8,
        eccentricity=0.855,
        inclination_deg=11.9,
        perihelion_au=76.3,
        aphelion_au=937.3,
        longitude_perihelion_deg=76.1,
        argument_perihelion_deg=311.4,
        orbital_period_years=11400.0,
        abs_magnitude=1.5,
        is_detached=True,
        is_clustered=True,
    ),
    TNObject(
        name="2012 VP113 ('Biden')",
        designation="2012 VP113",
        semi_major_axis_au=261.0,
        eccentricity=0.691,
        inclination_deg=24.0,
        perihelion_au=80.5,
        aphelion_au=441.5,
        longitude_perihelion_deg=293.7,
        argument_perihelion_deg=293.7,
        orbital_period_years=4220.0,
        abs_magnitude=4.0,
        is_detached=True,
        is_clustered=True,
    ),
    TNObject(
        name="Leleakuhonua (541132)",
        designation="2015 TG387",
        semi_major_axis_au=1010.0,
        eccentricity=0.936,
        inclination_deg=11.7,
        perihelion_au=65.0,
        aphelion_au=1955.0,
        longitude_perihelion_deg=227.0,
        argument_perihelion_deg=118.0,
        orbital_period_years=32000.0,
        abs_magnitude=5.3,
        is_detached=True,
        is_clustered=True,
    ),
    TNObject(
        name="2013 FT28",
        designation="2013 FT28",
        semi_major_axis_au=312.0,
        eccentricity=0.860,
        inclination_deg=17.3,
        perihelion_au=43.6,
        aphelion_au=580.4,
        longitude_perihelion_deg=40.2,
        argument_perihelion_deg=343.1,
        orbital_period_years=5510.0,
        abs_magnitude=6.7,
        is_detached=False,
        is_clustered=True,
    ),
    TNObject(
        name="2014 SR349",
        designation="2014 SR349",
        semi_major_axis_au=300.0,
        eccentricity=0.841,
        inclination_deg=18.0,
        perihelion_au=47.7,
        aphelion_au=552.3,
        longitude_perihelion_deg=341.5,
        argument_perihelion_deg=341.2,
        orbital_period_years=5200.0,
        abs_magnitude=6.6,
        is_detached=False,
        is_clustered=True,
    ),
    TNObject(
        name="2010 GB174",
        designation="2010 GB174",
        semi_major_axis_au=371.0,
        eccentricity=0.869,
        inclination_deg=21.5,
        perihelion_au=48.7,
        aphelion_au=693.3,
        longitude_perihelion_deg=347.8,
        argument_perihelion_deg=347.8,
        orbital_period_years=7140.0,
        abs_magnitude=6.5,
        is_detached=False,
        is_clustered=True,
    ),
    TNObject(
        name="2015 BP519 ('Caju')",
        designation="2015 BP519",
        semi_major_axis_au=433.0,
        eccentricity=0.919,
        inclination_deg=54.1,
        perihelion_au=35.1,
        aphelion_au=830.9,
        longitude_perihelion_deg=338.0,
        argument_perihelion_deg=338.0,
        orbital_period_years=9000.0,
        abs_magnitude=4.3,
        is_detached=False,
        is_clustered=True,
    ),
]

SEARCH_REGIONS: list[dict[str, Any]] = [
    {
        "id": "p9-aphelion-primary",
        "name": "Batygin & Brown Primary Aphelion Corridor",
        "name_az": "Batygin və Brown Əsas Afeli Dəhlizi",
        "ra_min": 40.0,
        "ra_max": 100.0,
        "dec_min": -20.0,
        "dec_max": 20.0,
        "ra_center": 70.0,
        "dec_center": 0.0,
        "probability_score": 0.65,
        "constellations": ["Cetus", "Taurus", "Eridanus", "Orion"],
        "description": "Highest probability aphelion sector where Planet Nine would move most slowly (~1 km/s) and exhibit the longest observational persistence.",
        "description_az": "Ən yüksək ehtimallı afeli sektoru; burada Doqquzuncu Planet ən yavaş sürətlə (~1 km/san) hərəkət edir və ən uzun müşahidə qalıcılığına malikdir.",
        "is_simulated": False,
        "data_source": "published literature",
    },
    {
        "id": "p9-southern-flank",
        "name": "Southern Invariable Plane Corridor",
        "name_az": "Cənub Dəyişməz Müstəvi Dəhlizi",
        "ra_min": 20.0,
        "ra_max": 45.0,
        "dec_min": -30.0,
        "dec_max": -10.0,
        "ra_center": 32.5,
        "dec_center": -20.0,
        "probability_score": 0.20,
        "constellations": ["Sculptor", "Cetus", "Fornax"],
        "description": "Secondary corridor corresponding to southern ecliptic excursions in an inclined orbit.",
        "description_az": "Meyilli orbitdə cənub ekliptika meyllərinə uyğun gələn ikinci dərəcəli axtarış dəhlizi.",
        "is_simulated": False,
        "data_source": "published literature",
    },
    {
        "id": "p9-northern-node",
        "name": "Northern Ascending Node Crossing",
        "name_az": "Şimal Qalxan Düyün Kəsişməsi",
        "ra_min": 85.0,
        "ra_max": 115.0,
        "dec_min": 15.0,
        "dec_max": 35.0,
        "ra_center": 100.0,
        "dec_center": 25.0,
        "probability_score": 0.15,
        "constellations": ["Gemini", "Auriga", "Taurus"],
        "description": "Ascending node region where the orbit crosses into northern galactic latitudes.",
        "description_az": "Orbitin şimal qalaktik enliklərinə keçdiyi qalxan düyün zonası.",
        "is_simulated": False,
        "data_source": "published literature",
    },
]


@router.get(
    "/evidence",
    response_model=ApiResponse,
    summary="Get Planet Nine scientific evidence",
    description="Returns scientific syntheses of dynamical evidence for the Planet Nine hypothesis (Batygin & Brown 2016-2021).",
)
async def get_planetx_evidence(
    locale: str = Query("en", description="Preferred response locale (en or az)"),
) -> ApiResponse:
    """Return theoretical and observational evidence for Planet Nine."""
    payload = {
        "hypothesis": "Planet Nine / Planet X Hypothesis",
        "summary": "Dynamical clustering of distant Kuiper Belt orbits driven by an unseen super-Earth in an eccentric, inclined outer orbit.",
        "summary_az": "Görünməyən super-Yerin ekssentrik və meyilli orbiti tərəfindən idarə olunan uzaq Koyper Qursağı orbitlərinin dinamik klasterləşməsi.",
        "disclaimer": "Scientific hypothesis under active investigation. Planet Nine has not been directly imaged or confirmed.",
        "disclaimer_az": "Aktiv tədqiqat mərhələsində olan elmi hipotezdir. Doqquzuncu Planet hələ birbaşa təsvir edilməyib və ya təsdiqlənməyib.",
        "evidence": EVIDENCE_LIST,
        "predictions": PREDICTIONS_LIST,
        "is_simulated": False,
        "data_source": "published literature",
    }

    return ApiResponse(
        success=True,
        data=payload,
        message=_get_msg(locale, "evidence_success"),
        locale=locale,
        is_simulated=False,
    )


@router.get(
    "/tnos",
    response_model=ApiResponse,
    summary="Get extreme Trans-Neptunian Objects (eTNOs)",
    description="Returns high-precision orbital elements for extreme TNOs providing the empirical basis for the Planet Nine hypothesis.",
)
async def get_planetx_tnos(
    locale: str = Query("en", description="Preferred response locale (en or az)"),
) -> ApiResponse:
    """Orbits of distant detached TNOs, fetched live from JPL SBDB (literature table as offline fallback)."""
    try:
        live = await etno_analysis()
        data = [{**o, "source": live["source"]} for o in live["objects"]]
        return ApiResponse(success=True, data=data, message=_get_msg(locale, "tnos_success"), locale=locale,
                           is_simulated=False)
    except Exception as exc:
        logger.warning(f"Live eTNO orbits unavailable, returning literature table: {exc}")
        return ApiResponse(success=True, data=TNOS_CATALOG, message=_get_msg(locale, "tnos_success"), locale=locale,
                           is_simulated=False)


@router.get(
    "/clustering",
    summary="Planet Nine clustering test on live JPL orbits",
    description="Rayleigh test for clustering of the longitude of perihelion (and node / argument of perihelion) "
                "of distant detached TNOs, computed from orbits fetched live from JPL SBDB.",
)
async def get_clustering(locale: str = Query("en")) -> dict[str, Any]:
    try:
        data = await etno_analysis()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NASA/JPL unavailable: {exc}")
    return {"success": True, "data": data, "is_simulated": False}


@router.get(
    "/regions",
    response_model=ApiResponse,
    summary="Get predicted Planet Nine search regions",
    description="Returns predicted celestial search corridors based on Batygin & Brown (2016-2021) numerical simulations.",
)
async def get_planetx_regions(
    locale: str = Query("en", description="Preferred response locale (en or az)"),
) -> ApiResponse:
    """Return predicted search corridors for Planet Nine."""
    return ApiResponse(
        success=True,
        data=SEARCH_REGIONS,
        message=_get_msg(locale, "regions_success"),
        locale=locale,
        is_simulated=False,
    )
