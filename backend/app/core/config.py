"""
OrbitScope Backend Configuration
================================
Loads and validates application settings using pydantic-settings BaseSettings.
Reads environment variables or .env file with production-ready defaults.
"""
from pathlib import Path
from typing import List, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    OrbitScope application settings loaded from environment variables or .env file.
    """

    # --- Application Metadata ---
    APP_NAME: str = Field(
        default="OrbitScope",
        description="Name of the application service",
    )
    APP_VERSION: str = Field(
        default="1.0.0",
        description="Application semantic version",
    )
    DEBUG: bool = Field(
        default=False,
        description="Enable debug mode (hot-reloading, verbose error traces)",
    )

    RATE_LIMIT_PER_MINUTE: int = Field(
        default=60,
        ge=0,
        description="Expensive requests (blink, photometry, detection, catalog) allowed per client per minute; 0 disables",
    )
    PREWARM_ON_STARTUP: bool = Field(
        default=False,
        description="At startup, download the challenge targets' data in the background (see app/services/prewarm.py)",
    )
    REVIEW_TOKEN: str = Field(
        default="",
        description="If set, reviewing candidates (PATCH) requires header X-Review-Token with this value",
    )
    TRUST_PROXY_HEADERS: bool = Field(
        default=False,
        description="Take the client IP from X-Real-IP (enable only behind the bundled nginx proxy)",
    )

    # --- Server Configuration ---
    HOST: str = Field(
        default="0.0.0.0",
        description="Network interface IP address to bind to",
    )
    PORT: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="TCP port to bind the FastAPI/Uvicorn server to",
    )

    # --- NASA/JPL API Endpoints ---
    JPL_SBDB_URL: str = Field(
        default="https://ssd-api.jpl.nasa.gov/sbdb.api",
        description="JPL Small-Body Database query API URL",
    )
    JPL_HORIZONS_URL: str = Field(
        default="https://ssd.jpl.nasa.gov/api/horizons.api",
        description="JPL Horizons on-line ephemeris computation API URL",
    )
    IRSA_TAP_URL: str = Field(
        default="https://irsa.ipac.caltech.edu/TAP/sync",
        description="NASA/IPAC Infrared Science Archive TAP synchronous query URL",
    )

    # --- Cache Configuration ---
    CACHE_TTL_SECONDS: int = Field(
        default=300,
        ge=1,
        description="Default time-to-live in seconds for cached catalog and ephemeris entries",
    )
    CACHE_MAX_SIZE: int = Field(
        default=1000,
        ge=10,
        description="Maximum number of items permitted in each in-memory TTLCache instance",
    )


    # --- SPHEREx archive (real data) ---
    SPHEREX_CACHE_DIR: str = Field(
        default=str(Path(__file__).resolve().parents[2] / "cache" / "spherex"),
        description="Directory for cached SPHEREx cutouts, datalink URLs and coverage queries",
    )

    SPHEREX_CACHE_MAX_MB: int = Field(
        default=2000,
        ge=50,
        description="Upper bound for the SPHEREx cutout cache; oldest cutouts are pruned beyond it",
    )
    SPHEREX_DOWNLOAD_CONCURRENCY: int = Field(
        default=10,
        ge=1,
        le=32,
        description="Parallel IRSA cutout downloads (6 is plenty on a Raspberry Pi)",
    )
    MAX_CONCURRENT_JOBS: int = Field(
        default=3,
        ge=1,
        le=16,
        description="Background jobs (blink, detection, photometry) that may run at the same time",
    )
    OFFLINE_CACHE_DIR: str = Field(
        default="",
        description="Directory for on-disk snapshots of JPL / Planet X answers used when the internet is "
                    "unreachable (default: <SPHEREX_CACHE_DIR>/../offline)",
    )
    # --- Raspberry Pi kiosk / Wi-Fi access point (written by deploy/pi/install.sh) ---
    PUBLIC_URL: str = Field(
        default="",
        description="Address visitors open on their phones (e.g. http://10.42.0.1); shown as a QR code in kiosk mode",
    )
    WIFI_AP_SSID: str = Field(default="", description="Name of the Pi's own Wi-Fi access point (kiosk QR code)")
    WIFI_AP_PASSWORD: str = Field(
        default="",
        description="Access point password; only ever sent to clients on the Pi itself (the kiosk screen)",
    )
    ORBITSCOPE_DB_PATH: str = Field(
        default=str(Path(__file__).resolve().parents[2] / "data" / "orbitscope.db"),
        description="SQLite file for detection runs and reviewed candidates",
    )

    # --- Logging Configuration ---
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR, or CRITICAL",
    )
    LOG_FORMAT: str = Field(
        default="json",
        description="Log output format: 'json' or 'text'",
    )

    # --- CORS Configuration ---
    CORS_ORIGINS: Union[str, List[str]] = Field(
        default=["http://localhost:3000", "http://localhost:5173", "http://localhost:8080"],
        description="Allowed CORS origins as a list of URI strings or comma-separated string",
    )

    # --- Localization ---
    DEFAULT_LOCALE: str = Field(
        default="en",
        description="Default fallback locale ('en' for English, 'az' for Azerbaijani)",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Union[str, List[str]]) -> List[str]:
        """
        Parse comma-separated string into a list of cleaned origin strings.
        Supports both comma-delimited strings and native Python lists/tuples.
        """
        if isinstance(value, str):
            if not value.strip():
                return []
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        if isinstance(value, (list, tuple)):
            return [str(origin).strip() for origin in value if str(origin).strip()]
        return value


# Module-level singleton instance for application-wide access
settings = Settings()
