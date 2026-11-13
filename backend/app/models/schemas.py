"""
OrbitScope Astronomical Data Models & API Schemas
=================================================
Pydantic v2 models still used by the API: the generic response envelope, system status,
the Planet X literature models, and i18n messaging (English / Azerbaijani). The SPHEREx,
detection and catalog endpoints return plain dicts built by their services.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


# ============================================================================
# Enums
# ============================================================================

class Locale(str, enum.Enum):
    """Supported localization languages across API endpoints."""
    EN = "en"
    AZ = "az"


# ============================================================================
# i18n Messaging System
# ============================================================================

I18N_MESSAGES: Dict[str, Dict[Locale, str]] = {
    "detection_success": {
        Locale.EN: "Detection pipeline executed successfully.",
        Locale.AZ: "Aşkarlama boru kəməri uğurla icra edildi.",
    },
    "detection_started": {
        Locale.EN: "Detection pipeline process initiated.",
        Locale.AZ: "Aşkarlama prosesi başladıldı.",
    },
    "comparison_success": {
        Locale.EN: "Observation comparison completed successfully.",
        Locale.AZ: "Müşahidələrin müqayisəsi uğurla tamamlandı.",
    },
    "catalog_search_success": {
        Locale.EN: "Catalog query returned matching celestial objects.",
        Locale.AZ: "Kataloq sorğusu uyğun səma cisimlərini qaytardı.",
    },
    "catalog_not_found": {
        Locale.EN: "No astronomical catalog objects matched the query.",
        Locale.AZ: "Sorğuya uyğun heç bir astronomik kataloq obyekti tapılmadı.",
    },
    "ephemeris_success": {
        Locale.EN: "JPL Horizons ephemeris generated successfully.",
        Locale.AZ: "JPL Horizons efemeridi uğurla tərtib edildi.",
    },
    "planet_x_success": {
        Locale.EN: "Theoretical Planet X orbital evidence and sky regions retrieved.",
        Locale.AZ: "Nəzəri Planet X orbital sübutları və səma bölgələri əldə edildi.",
    },
    "observation_retrieved": {
        Locale.EN: "Observation frame retrieved successfully.",
        Locale.AZ: "Müşahidə kadrı uğurla əldə edildi.",
    },
    "observation_not_found": {
        Locale.EN: "Specified observation frame was not found.",
        Locale.AZ: "Göstərilən müşahidə kadrı tapılmadı.",
    },
    "cache_cleared": {
        Locale.EN: "Internal cache was cleared successfully.",
        Locale.AZ: "Daxili keş uğurla təmizləndi.",
    },
    "invalid_request": {
        Locale.EN: "Invalid request parameters provided.",
        Locale.AZ: "Yanlış daxiletmə parametrləri təqdim edildi.",
    },
    "service_healthy": {
        Locale.EN: "OrbitScope backend service is operational and healthy.",
        Locale.AZ: "OrbitScope arxa sistemi tam işlək və saz vəziyyətdədir.",
    },
    "internal_error": {
        Locale.EN: "An internal server error occurred while processing the request.",
        Locale.AZ: "Sorğunun icrası zamanı daxili server xətası baş verdi.",
    },
}


def get_i18n_message(key: str, locale: Locale = Locale.EN, default: Optional[str] = None) -> str:
    """
    Retrieve a localized message for the given key and locale.
    Falls back to English if the localized translation is not found.

    Args:
        key: The message identifier key.
        locale: Target locale (Locale.EN or Locale.AZ).
        default: Fallback string if key is unregistered.

    Returns:
        str: Localized string message.
    """
    translations = I18N_MESSAGES.get(key)
    if translations:
        if locale in translations:
            return translations[locale]
        if Locale.EN in translations:
            return translations[Locale.EN]
    return default or key


# ============================================================================
# Coordinate & Sky Models
# ============================================================================


class SkyRegion(BaseModel):
    """
    Spherical celestial coordinates defining a region of interest on the celestial sphere.
    """
    ra: float = Field(
        ...,
        ge=0.0,
        lt=360.0,
        description="Right Ascension of center point in degrees (J2000)",
        examples=[45.5],
    )
    dec: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Declination of center point in degrees (J2000)",
        examples=[-12.3],
    )
    radius: float = Field(
        ...,
        gt=0.0,
        description="Search or coverage radius in degrees",
        examples=[2.5],
    )
    id: Optional[str] = Field(
        default=None,
        description="Unique identifier for the sky region",
        examples=["region_taurus_auriga_p9"],
    )
    is_simulated: bool = Field(
        default=False,
        description="Flag indicating whether this region is simulated",
    )
    name: Optional[str] = Field(
        default=None,
        description="Descriptive name or survey identifier for this region",
        examples=["Planet X Predicted Aphelion Sector A"],
    )
    description: Optional[str] = Field(
        default=None,
        description="Standard description of the region",
        examples=["Theoretical high-probability search region in Taurus-Auriga"],
    )
    descriptions: Dict[str, str] = Field(
        default_factory=dict,
        description="Localized descriptions mapping locale codes ('en', 'az') to text",
        examples=[{
            "en": "Theoretical high-probability search region in Taurus-Auriga",
            "az": "Buğa-Ərabaçı bürcündə yüksək ehtimallı nəzəri axtarış bölgəsi",
        }],
    )

    def get_description(self, locale: Locale = Locale.EN) -> Optional[str]:
        """Retrieve description in the requested locale if available."""
        if self.descriptions and locale.value in self.descriptions:
            return self.descriptions[locale.value]
        return self.description

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ra": 45.5,
                "dec": -12.3,
                "radius": 2.5,
                "name": "Planet X Predicted Aphelion Sector A",
                "description": "Theoretical high-probability search region in Taurus-Auriga",
                "descriptions": {
                    "en": "Theoretical high-probability search region in Taurus-Auriga",
                    "az": "Buğa-Ərabaçı bürcündə yüksək ehtimallı nəzəri axtarış bölgəsi",
                },
            }
        }
    )


# ============================================================================
# Observation & Imaging Models
# ============================================================================


# ============================================================================
# Photometry, Astrometry & Detection Candidates
# ============================================================================


# ============================================================================
# Orbital & Physical Characteristics
# ============================================================================


# ============================================================================
# Pipeline Results & Comparison Models
# ============================================================================


# ============================================================================
# Planet X / Trans-Neptunian Object Models
# ============================================================================

class TNObject(BaseModel):
    """Extreme Trans-Neptunian Object (eTNO) supporting dynamical clustering hypotheses."""
    designation: str = Field(..., description="Provisional or official designation")
    name: Optional[str] = Field(default=None, description="Proper name if assigned")
    semi_major_axis_au: Optional[float] = Field(default=None, ge=0.0, description="Semi-major axis in AU")
    perihelion_au: Optional[float] = Field(default=None, ge=0.0, description="Perihelion distance in AU")
    eccentricity: Optional[float] = Field(default=None, ge=0.0, description="Orbital eccentricity")
    inclination_deg: Optional[float] = Field(default=None, ge=0.0, le=180.0, description="Inclination in degrees")
    argument_perihelion_deg: Optional[float] = Field(default=None, description="Argument of perihelion in degrees")
    longitude_node_deg: Optional[float] = Field(default=None, description="Longitude of ascending node in degrees")
    is_extreme_tno: bool = Field(default=True, description="Whether object meets extreme TNO criteria (a > 150 AU, q > 30 AU)")
    notes: Optional[str] = Field(default=None, description="Physical or dynamical notes")


class PlanetXPrediction(BaseModel):
    """Orbital parameter estimates for the hypothetical Planet Nine / Planet X."""
    mass_earth_masses: Optional[float] = Field(default=5.0, description="Predicted mass in Earth masses (5-10 M_Earth)")
    semi_major_axis_au: Optional[float] = Field(default=380.0, description="Predicted semi-major axis in AU (300-500 AU)")
    perihelion_au: Optional[float] = Field(default=300.0, description="Predicted perihelion distance in AU")
    aphelion_au: Optional[float] = Field(default=460.0, description="Predicted aphelion distance in AU")
    inclination_deg: Optional[float] = Field(default=16.0, description="Predicted orbital inclination in degrees (15-25 deg)")
    longitude_perihelion_deg: Optional[float] = Field(default=248.0, description="Predicted longitude of perihelion in degrees")
    current_predicted_ra: Optional[float] = Field(default=45.0, description="Current estimated sky Right Ascension near aphelion")
    current_predicted_dec: Optional[float] = Field(default=-10.0, description="Current estimated sky Declination near aphelion")
    current_predicted_dist_au: Optional[float] = Field(default=380.0, description="Current estimated heliocentric distance in AU")
    apparent_magnitude_v: Optional[float] = Field(default=22.5, description="Expected apparent visual magnitude (V ~ 22-24)")
    is_simulated: bool = Field(default=False, description="Literature values, not invented data")
    data_source: str = Field(default="published literature", description="Origin of the values")


class PlanetXEvidence(BaseModel):
    """
    Theoretical astrophysical constraints, orbital clustering statistics,
    and predicted celestial search zones for the hypothetical Planet Nine / Planet X.
    Summaries of published papers, labelled `data_source="published literature"`.
    """
    clustering_sigma: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Statistical significance of orbital clustering in sigmas (e.g. Batygin & Brown 2016/2021)",
        examples=[3.8],
    )
    anti_aligned_fraction: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fraction of extreme TNOs exhibiting clustered perihelion anti-alignment",
        examples=[0.82],
    )
    perihelion_clustering: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Clustering parameters for longitude of perihelion and orbital pole alignment",
        examples=[{"mean_varpi_deg": 240.0, "dispersion_deg": 35.0}],
    )
    predicted_regions: List[SkyRegion] = Field(
        default_factory=list,
        description="Target sky regions where Planet X is predicted to be located near aphelion",
    )
    relevant_tnos: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Extreme Trans-Neptunian Objects supporting the dynamical clustering hypothesis",
        examples=[[{"designation": "90377 Sedna", "a_au": 506.0, "e": 0.855, "i_deg": 11.93}]],
    )
    notes: str = Field(
        default="",
        description="Scientific commentary, model assumptions, and astrophysical references",
        examples=["Based on extreme TNO orbital clustering with semi-major axis > 150 AU and perihelion > 30 AU."],
    )
    is_simulated: bool = Field(
        default=False,
        description="Literature summary (published papers), not invented data",
    )
    data_source: str = Field(default="published literature", description="Origin of the values")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "clustering_sigma": 3.8,
                "anti_aligned_fraction": 0.82,
                "perihelion_clustering": {"mean_varpi_deg": 240.0, "dispersion_deg": 35.0},
                "predicted_regions": [],
                "relevant_tnos": [{"designation": "90377 Sedna", "a_au": 506.0}],
                "notes": "Theoretical prediction from dynamical clustering of extreme TNOs.",
                "is_simulated": False,
            }
        }
    )


class PlanetXData(BaseModel):
    """Aggregate bundle of Planet X hypothesis data, predictions, and supporting eTNOs."""
    evidence: PlanetXEvidence = Field(..., description="Clustering evidence and predicted regions")
    prediction: Optional[PlanetXPrediction] = Field(default=None, description="Physical and orbital parameters prediction")
    predicted_regions: List[SkyRegion] = Field(default_factory=list, description="Target search regions")
    extreme_tnos: List[Dict[str, Any]] = Field(default_factory=list, description="List of extreme TNOs")
    is_simulated: bool = Field(default=False, description="Literature values, not invented data")
    data_source: str = Field(default="published literature", description="Origin of the values")


# ============================================================================
# API Request Models
# ============================================================================


# Alias for backward compatibility


# ============================================================================
# System Diagnostic Models
# ============================================================================

class SystemStatus(BaseModel):
    """Health check and runtime diagnostics for OrbitScope backend service."""
    status: str = Field(default="healthy", description="Service health: 'healthy', 'degraded', 'error'")
    service: str = Field(default="OrbitScope", description="Service name")
    version: str = Field(default="1.0.0", description="Backend version")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Current UTC timestamp")
    uptime_seconds: Optional[float] = Field(default=None, description="System uptime in seconds")
    components: Dict[str, Any] = Field(default_factory=dict, description="Status of internal services and cache")


# ============================================================================
# Generic API Response Wrapper
# ============================================================================

class APIResponse(BaseModel, Generic[T]):
    """
    Standard envelope returned across all OrbitScope backend REST endpoints.
    Provides typed payload encapsulation, localized status messaging,
    UTC timestamping, and explicit data provenance labeling.
    """
    success: bool = Field(
        default=True,
        description="Flag indicating whether the requested operation succeeded",
    )
    data: Optional[T] = Field(
        default=None,
        description="Typed payload data on success, or None on failure/empty results",
    )
    message: str = Field(
        ...,
        description="Human-readable status or explanatory message",
        examples=["Operation completed successfully."],
    )
    locale: Locale = Field(
        default=Locale.EN,
        description="Language code of the response message ('en' or 'az')",
        examples=[Locale.EN],
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the response was constructed",
    )
    is_simulated: bool = Field(
        default=False,
        description="Explicit flag denoting whether the returned data is synthetic or simulated",
    )

    @classmethod
    def build(
        cls,
        data: Optional[T] = None,
        message_key: Optional[str] = None,
        custom_message: Optional[str] = None,
        locale: Locale = Locale.EN,
        success: bool = True,
        is_simulated: bool = False,
    ) -> "APIResponse[T]":
        """
        Convenience factory to construct an APIResponse with localized message resolution.

        Args:
            data: Payload data.
            message_key: Key in the I18N_MESSAGES dictionary.
            custom_message: Specific custom text overriding i18n lookup.
            locale: Language locale for message formatting.
            success: Boolean success flag.
            is_simulated: Explicit synthetic data indicator.

        Returns:
            APIResponse[T]: Initialized response object.
        """
        if custom_message is not None:
            resolved_message = custom_message
        elif message_key is not None:
            resolved_message = get_i18n_message(message_key, locale=locale)
        else:
            default_en = "Operation completed successfully." if success else "Operation failed."
            default_az = "Əməliyyat uğurla tamamlandı." if success else "Əməliyyat uğursuz oldu."
            resolved_message = default_az if locale == Locale.AZ else default_en

        return cls(
            success=success,
            data=data,
            message=resolved_message,
            locale=locale,
            is_simulated=is_simulated,
        )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "data": None,
                "message": "Detection pipeline executed successfully.",
                "locale": "en",
                "timestamp": "2026-03-15T15:00:00Z",
                "is_simulated": False,
            }
        }
    )


# Alias for backward-compatibility with alternative casing
ApiResponse = APIResponse
