"""
main.py – Uvicorn entry point.
Configures structlog at startup before any module imports the logger.
"""
from __future__ import annotations

import logging

import structlog


def _configure_logging() -> None:
    """Configure structlog: JSON in production, coloured console otherwise."""
    from backend.config import get_settings
    settings = get_settings()

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.is_production
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

from backend.api.app import create_app  # noqa: E402  (intentional: after logging init)

app = create_app()
