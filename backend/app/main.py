"""OrbitScope Backend - FastAPI Application
Main application entry point configuring lifespan management, service singletons,
CORS policies, routing, and global exception handling.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.catalog import router as catalog_router
from app.api.routes.ground import router as ground_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.planetx import router as planetx_router
from app.api.routes.spherex import router as spherex_router
from app.api.routes.system import router as system_router
from app.core.config import settings
from app.core.logging_config import get_logger, setup_logging
from app.core.rate_limit import RateLimitMiddleware
from app.core.validation_i18n import localize_errors


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown: logging, uptime clock and SPHEREx cache upkeep."""
    setup_logging(settings.LOG_LEVEL if hasattr(settings, "LOG_LEVEL") else "INFO")
    logger = get_logger("main")
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} (DEBUG={settings.DEBUG})")
    app.state.startup_time = datetime.now(timezone.utc)

    # Keep the SPHEREx cutout cache within its size limit (runs in the background).
    from app.services.spherex_archive import spherex_archive as _archive
    import asyncio as _asyncio

    _asyncio.get_running_loop().run_in_executor(None, _archive.prune_cache)

    # Public deployments: fetch the challenge targets' data before the first visitor asks for it.
    warm_task = None
    if settings.PREWARM_ON_STARTUP:
        from app.services.prewarm import prewarm

        async def _warm() -> None:
            try:
                await prewarm(log=logger.info)
            except Exception as exc:  # noqa: BLE001 - never take the server down
                logger.warning(f"Startup prewarm failed: {exc}")

        warm_task = _asyncio.create_task(_warm())
    yield
    if warm_task is not None and not warm_task.done():
        warm_task.cancel()
    logger.info("OrbitScope backend shutting down.")


# Initialize FastAPI instance
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="SPHEREx Time-Domain Sky Monitoring & Moving Object Detection Platform",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

@app.middleware("http")
async def json_errors(request: Request, call_next):
    """Turn unexpected exceptions into JSON 500s *inside* the CORS middleware.

    Starlette's default 500 page is produced outside CORS, so browsers only saw an opaque
    'Network Error'. Registered before CORSMiddleware so CORS wraps it.
    """
    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001 - last-resort handler
        get_logger("main").exception(f"Unhandled error on {request.url.path}: {exc}")
        return JSONResponse(status_code=500, content={"detail": f"Internal server error: {type(exc).__name__}"})


# Per-client limit on the expensive endpoints (IRSA downloads, detection, JPL lookups).
# Added before CORS so 429 responses still carry CORS headers.
app.add_middleware(RateLimitMiddleware)

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 with one readable sentence in the request's language (the raw list stays in `errors`)."""
    errors = exc.errors()
    raw = [{k: v for k, v in e.items() if k in ("type", "loc", "msg")} for e in errors]
    locale = request.query_params.get("locale", "en")
    return JSONResponse(status_code=422, content={"detail": localize_errors(errors, locale), "errors": raw})


# Configure CORS Middleware
origins = settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else [str(settings.CORS_ORIGINS)]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    # Any local dev port (Vite falls back to 5174, 5175, ... when 5173 is busy).
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all API routers
app.include_router(spherex_router)
app.include_router(jobs_router)
app.include_router(catalog_router)
app.include_router(planetx_router)
app.include_router(system_router)
app.include_router(ground_router)


@app.get(
    "/",
    summary="OrbitScope Root Welcome",
    description="Provides basic service metadata, documentation URL, and multilingual greeting.",
)
async def root() -> dict[str, Any]:
    """Root endpoint welcoming clients and indicating operational mode."""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": "OrbitScope - SPHEREx Time-Domain Sky Monitoring & Moving Object Detection Platform",
        "message": "Welcome to OrbitScope API. Explore the sky, detect changes, track celestial objects.",
        "message_az": "OrbitScope API-yə xoş gəlmisiniz. Göyü kəşf edin, dəyişiklikləri aşkar edin, göy cisimlərini izləyin.",
        "documentation": "/docs",
        "data": "real public NASA/IPAC, NASA/JPL and ESA archives (no simulated data)",
        "locale_default": getattr(settings, "DEFAULT_LOCALE", "en"),
        "status": "operational",
    }
