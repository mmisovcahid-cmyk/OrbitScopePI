"""Per-client rate limit for the expensive endpoints.

Every blink, photometry, detection or catalog request makes the backend download data from
IRSA, ESA or JPL. On a public deployment one client could otherwise queue enough work to slow
the site down for everyone (and put load on the NASA archives). Cheap requests (status, job
polling, saved candidates, docs) are not limited.

In-process sliding window, keyed by client IP. Behind the bundled nginx proxy the client IP
comes from ``X-Real-IP``; that header is only trusted when ``TRUST_PROXY_HEADERS`` is true,
otherwise any client could spoof it.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

# (method, path prefix) pairs that trigger external downloads or heavy computation.
LIMITED: tuple[tuple[str, str], ...] = (
    ("POST", "/api/v1/jobs"),
    ("GET", "/api/v1/spherex/blink"),        # also blink.gif
    ("GET", "/api/v1/spherex/photometry"),
    ("GET", "/api/v1/spherex/detect"),
    ("GET", "/api/v1/spherex/overlay"),
    ("GET", "/api/v1/spherex/coverage"),
    ("GET", "/api/v1/spherex/resolve"),
    ("GET", "/api/v1/catalog/"),
    ("GET", "/api/v1/planetx/clustering"),
)

MESSAGES = {
    "en": "Too many requests from your address. Please wait {s} s and try again.",
    "az": "Ünvanınızdan çox sorğu gəldi. {s} saniyə gözləyib yenidən cəhd edin.",
}

WINDOW_S = 60.0


def is_limited(method: str, path: str) -> bool:
    return any(method == m and path.startswith(p) for m, p in LIMITED)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, per_minute: int | None = None) -> None:
        super().__init__(app)
        self.per_minute = per_minute if per_minute is not None else settings.RATE_LIMIT_PER_MINUTE
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def client_key(self, request: Request) -> str:
        if settings.TRUST_PROXY_HEADERS:
            real = request.headers.get("x-real-ip")
            if real:
                return real.strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        if self.per_minute <= 0 or not is_limited(request.method, request.url.path):
            return await call_next(request)
        now = time.monotonic()
        q = self.hits[self.client_key(request)]
        while q and now - q[0] > WINDOW_S:
            q.popleft()
        if len(q) >= self.per_minute:
            retry = max(1, int(WINDOW_S - (now - q[0])) + 1)
            locale = request.query_params.get("locale", "en")
            msg = MESSAGES.get(locale, MESSAGES["en"]).format(s=retry)
            return JSONResponse(status_code=429, content={"detail": msg}, headers={"Retry-After": str(retry)})
        q.append(now)
        if len(self.hits) > 10_000:  # drop idle clients so memory stays bounded
            for k in [k for k, v in self.hits.items() if not v or now - v[-1] > WINDOW_S]:
                del self.hits[k]
        return await call_next(request)
