"""
OrbitScope In-Memory Cache Module
=================================
Thread-safe TTL caching using cachetools for astronomical catalogs,
SPHEREx observation frames, external API responses, and pipeline execution artifacts.
"""
from threading import RLock
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

from cachetools import TTLCache as _CachetoolsTTLCache

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class TTLCacheWrapper(Generic[T]):
    """
    Thread-safe wrapper around cachetools.TTLCache.
    Provides get, set, invalidate, and clear methods with synchronization
    via an RLock, along with hit/miss diagnostic tracking.
    """

    def __init__(
        self,
        maxsize: Optional[int] = None,
        ttl: Optional[float] = None,
        name: str = "default_cache",
    ) -> None:
        """
        Initialize the thread-safe TTL cache.

        Args:
            maxsize: Maximum number of entries permitted in the cache.
            ttl: Time-to-live in seconds for each cache entry.
            name: Descriptive name for logging and diagnostic identification.
        """
        self.name = name
        self._maxsize = int(maxsize if maxsize is not None else settings.CACHE_MAX_SIZE)
        self._ttl = float(ttl if ttl is not None else settings.CACHE_TTL_SECONDS)
        self._lock = RLock()
        self._cache: _CachetoolsTTLCache = _CachetoolsTTLCache(maxsize=self._maxsize, ttl=self._ttl)
        self._hits: int = 0
        self._misses: int = 0

    @property
    def maxsize(self) -> int:
        """Maximum number of items allowed in the cache."""
        return self._maxsize

    @property
    def ttl(self) -> float:
        """Time-to-live for cache entries in seconds."""
        return self._ttl

    def get(self, key: str, default: Optional[T] = None) -> Optional[T]:
        """
        Retrieve a value from the cache.

        Args:
            key: Cache key to retrieve.
            default: Value to return if key is missing or expired.

        Returns:
            Cached item or default.
        """
        with self._lock:
            try:
                if key in self._cache:
                    val = self._cache[key]
                    self._hits += 1
                    return val
                self._misses += 1
                return default
            except KeyError:
                self._misses += 1
                return default

    def set(self, key: str, value: T) -> None:
        """
        Store a value in the cache with the configured TTL.

        Args:
            key: Cache key.
            value: Item to store.
        """
        with self._lock:
            self._cache[key] = value

    def invalidate(self, key: str) -> bool:
        """
        Remove a key from the cache immediately.

        Args:
            key: Cache key to invalidate.

        Returns:
            True if key existed and was deleted, False otherwise.
        """
        with self._lock:
            try:
                del self._cache[key]
                return True
            except KeyError:
                return False

    def clear(self) -> None:
        """Clear all entries from the cache and reset hit/miss counters."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def contains(self, key: str) -> bool:
        """Check whether an unexpired key exists in the cache."""
        with self._lock:
            return key in self._cache

    def __contains__(self, key: str) -> bool:
        return self.contains(key)

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def keys(self) -> List[str]:
        """Return a snapshot list of current unexpired cache keys."""
        with self._lock:
            return list(self._cache.keys())

    def get_or_set(self, key: str, supplier: Callable[[], T]) -> T:
        """
        Retrieve an item if present; otherwise, compute it via supplier, store, and return.

        Args:
            key: Cache key.
            supplier: Callable computing the value upon cache miss.

        Returns:
            Cached or newly computed value.
        """
        with self._lock:
            cached_val = self.get(key)
            if cached_val is not None:
                return cached_val
            value = supplier()
            self.set(key, value)
            return value

    def stats(self) -> Dict[str, Any]:
        """
        Return diagnostic statistics for this cache instance.
        """
        with self._lock:
            total_lookups = self._hits + self._misses
            hit_ratio = (self._hits / total_lookups) if total_lookups > 0 else 0.0
            return {
                "name": self.name,
                "current_size": len(self._cache),
                "max_size": self._maxsize,
                "ttl_seconds": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio": round(hit_ratio, 4),
            }


# Descriptive aliases
InMemoryCache = TTLCacheWrapper
TTLCache = TTLCacheWrapper

# Module-level cache instances for domain data types
catalog_cache: TTLCacheWrapper[Any] = TTLCacheWrapper(
    maxsize=settings.CACHE_MAX_SIZE,
    ttl=settings.CACHE_TTL_SECONDS,
    name="catalog_cache",
)

observation_cache: TTLCacheWrapper[Any] = TTLCacheWrapper(
    maxsize=settings.CACHE_MAX_SIZE,
    ttl=settings.CACHE_TTL_SECONDS,
    name="observation_cache",
)

pipeline_cache: TTLCacheWrapper[Any] = TTLCacheWrapper(
    maxsize=settings.CACHE_MAX_SIZE,
    ttl=settings.CACHE_TTL_SECONDS,
    name="pipeline_cache",
)

api_cache: TTLCacheWrapper[Any] = TTLCacheWrapper(
    maxsize=settings.CACHE_MAX_SIZE,
    ttl=settings.CACHE_TTL_SECONDS,
    name="api_cache",
)
