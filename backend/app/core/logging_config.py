"""
OrbitScope Backend Structured Logging Configuration
===================================================
Provides structured JSON and human-readable text logging formatters,
runtime log level configuration, and logger instance retrieval helpers.
"""
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import settings


class JSONFormatter(logging.Formatter):
    """
    Formatter that outputs log records as single-line structured JSON objects.
    Enriches records with timestamp (UTC ISO 8601), level, logger name, module,
    line number, process/thread identifiers, stack traces, and custom extra attributes.
    """

    # Reserved attributes on standard logging.LogRecord to avoid duplicating in 'extra'
    RESERVED_ATTRS = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a single-line JSON string."""
        log_payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "process": record.process,
            "thread": record.threadName,
        }

        # Include exception information if present
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        # Include stack trace info if present
        if record.stack_info:
            log_payload["stack_info"] = self.formatStack(record.stack_info)

        # Collect arbitrary contextual keys passed via extra={...}
        extra_fields: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS and not key.startswith("_"):
                extra_fields[key] = value

        if extra_fields:
            log_payload["extra"] = extra_fields

        try:
            return json.dumps(log_payload, default=str, ensure_ascii=False)
        except Exception:
            # Fallback to string conversions if complex non-serializable objects exist
            safe_payload = {k: str(v) for k, v in log_payload.items()}
            return json.dumps(safe_payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """
    Human-readable text formatter designed for local development console viewing.
    """

    DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s"
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
    ) -> None:
        super().__init__(
            fmt=fmt or self.DEFAULT_FORMAT,
            datefmt=datefmt or self.DATE_FORMAT,
        )


def setup_logging(
    log_level: Optional[str] = None,
    log_format: Optional[str] = None,
) -> None:
    """
    Initialize root logging configuration based on application settings.

    Args:
        log_level: Optional level override (e.g. 'DEBUG', 'INFO', 'WARNING').
        log_format: Optional format override ('json' or 'text').
    """
    resolved_level_name = (log_level or settings.LOG_LEVEL).upper()
    level = getattr(logging, resolved_level_name, logging.INFO)
    format_type = (log_format or settings.LOG_FORMAT).lower()

    # Select appropriate formatter
    formatter: logging.Formatter
    if format_type == "json":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates on re-configuration
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Moderate noisiness from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("astropy").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Retrieve or create a named logger for a module.

    Args:
        name: Name of the logger, typically __name__ of the calling module.

    Returns:
        logging.Logger: Configured logger instance.
    """
    return logging.getLogger(name)


# Default module-level application logger instance
logger = get_logger("orbitscope")
