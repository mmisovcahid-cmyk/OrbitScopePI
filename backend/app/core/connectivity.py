"""
OrbitScope - is the internet reachable?
=======================================
A cheap TCP probe (no HTTP request) to the archives the app depends on, cached for 30 s.
Used by /system/status (the UI's offline banner) and to skip long network timeouts when a
Raspberry Pi runs without internet and a cached answer is available.
"""
from __future__ import annotations

import asyncio
import time

PROBE_HOSTS = (("irsa.ipac.caltech.edu", 443), ("ssd-api.jpl.nasa.gov", 443))
PROBE_TIMEOUT_S = 3.0
CACHE_S = 30.0

_state: dict[str, float | bool] = {"checked": 0.0, "online": True}
_lock: asyncio.Lock | None = None


async def _probe(host: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), PROBE_TIMEOUT_S)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def is_online(force: bool = False) -> bool:
    """True if at least one of the archive hosts accepts a TCP connection."""
    global _lock
    if not force and time.time() - float(_state["checked"]) < CACHE_S:
        return bool(_state["online"])
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        if not force and time.time() - float(_state["checked"]) < CACHE_S:
            return bool(_state["online"])
        results = await asyncio.gather(*(_probe(h, p) for h, p in PROBE_HOSTS))
        _state["online"] = any(results)
        _state["checked"] = time.time()
        return bool(_state["online"])


def last_known() -> dict[str, object]:
    return {"online": bool(_state["online"]), "checked_at": float(_state["checked"]) or None}
