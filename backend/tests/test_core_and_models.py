"""
Unit tests for OrbitScope core modules and schemas.
"""
import logging
from datetime import datetime, timezone
import pytest

from app.core.config import Settings, settings
from app.core.logging_config import JSONFormatter, TextFormatter, get_logger, setup_logging
from app.core.cache import TTLCacheWrapper, catalog_cache, observation_cache, pipeline_cache, api_cache
from app.models.schemas import (
    APIResponse,
    Locale,
    PlanetXEvidence,
    PlanetXPrediction,
    SkyRegion,
    get_i18n_message,
)


def test_config_defaults_and_parsing():
    """Verify settings defaults and custom parsing logic."""
    assert settings.APP_NAME == "OrbitScope"
    assert settings.APP_VERSION == "1.0.0"
    assert settings.PORT == 8000
    assert isinstance(settings.CORS_ORIGINS, list)
    assert "http://localhost:3000" in settings.CORS_ORIGINS

    custom_cfg = Settings(CORS_ORIGINS="http://demo.example.com, https://app.example.com")
    assert custom_cfg.CORS_ORIGINS == ["http://demo.example.com", "https://app.example.com"]


def test_logging_formatters():
    """Verify JSONFormatter and TextFormatter outputs."""
    setup_logging(log_level="DEBUG", log_format="json")
    logger = get_logger("test.subsystem")
    assert logger.name == "test.subsystem"

    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Source detected at ra=%s",
        args=(83.63,),
        exc_info=None,
    )
    record.detection_snr = 14.5
    json_formatter = JSONFormatter()
    formatted_json = json_formatter.format(record)

    assert "Source detected at ra=83.63" in formatted_json
    assert "detection_snr" in formatted_json
    assert "test.logger" in formatted_json

    text_formatter = TextFormatter()
    formatted_text = text_formatter.format(record)
    assert "[INFO]" in formatted_text
    assert "Source detected at ra=83.63" in formatted_text


def test_cache_functionality():
    """Verify TTLCache operations, invalidation, and diagnostic stats."""
    cache = TTLCacheWrapper(maxsize=10, ttl=60.0, name="unit_test_cache")
    assert cache.name == "unit_test_cache"

    cache.set("obj_001", {"name": "Sedna", "q": 76.2})
    assert cache.contains("obj_001") is True
    assert "obj_001" in cache
    assert len(cache) == 1

    entry = cache.get("obj_001")
    assert entry is not None
    assert entry["name"] == "Sedna"

    # Invalidation
    removed = cache.invalidate("obj_001")
    assert removed is True
    assert cache.get("obj_001") is None
    assert cache.invalidate("non_existent") is False

    # get_or_set
    val = cache.get_or_set("computed", lambda: 42)
    assert val == 42
    assert cache.get("computed") == 42

    stats = cache.stats()
    assert stats["name"] == "unit_test_cache"
    assert stats["hits"] >= 1


def test_schemas_and_i18n():
    """Remaining API models: literature labelling and localized messages."""
    region = SkyRegion(
        ra=45.5, dec=-12.3, radius=2.5, name="Planet X Sector 1",
        description="Search area in Taurus",
        descriptions={"en": "Search area in Taurus", "az": "Buğa bürcündə axtarış sahəsi"},
    )
    assert region.get_description(Locale.EN) == "Search area in Taurus"
    assert region.get_description(Locale.AZ) == "Buğa bürcündə axtarış sahəsi"

    evidence = PlanetXEvidence(clustering_sigma=3.8, predicted_regions=[region], notes="Batygin & Brown 2016")
    assert evidence.is_simulated is False and evidence.data_source == "published literature"
    assert PlanetXPrediction().data_source == "published literature"

    resp_en = APIResponse[SkyRegion].build(data=region, message_key="catalog_search_success", locale=Locale.EN)
    assert resp_en.success is True and resp_en.locale == Locale.EN
    assert resp_en.message == "Catalog query returned matching celestial objects."
    resp_az = APIResponse[SkyRegion].build(data=region, message_key="catalog_search_success", locale=Locale.AZ)
    assert resp_az.message == "Kataloq sorğusu uyğun səma cisimlərini qaytardı."
    assert get_i18n_message("catalog_search_success", Locale.AZ) == resp_az.message
