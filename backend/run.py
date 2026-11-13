"""
OrbitScope Backend - Entry Point
Start the FastAPI server with uvicorn.
"""
import uvicorn
from app.core.config import settings


def main() -> None:
    """Start the OrbitScope backend server."""
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
