"""
main.py – Uvicorn entry point.

Fix: configures structlog JSON renderer at startup so all logs are structured
from the first line. Was missing — default structlog config outputs plain text.
"""
from __future__ import annotations

import logging

import structlog


def _configure_logging() -> None:
    """Configure structlog for JSON output (production) or console (dev)."""
    from backend.config import get_settings
    settings = get_settings()

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.environment == "production"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configure_logging()

from backend.api.app import create_app  # noqa: E402 (after logging config)

app = create_app()
