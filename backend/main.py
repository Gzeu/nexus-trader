"""
main.py – Entry point. Run with: uvicorn backend.main:app --reload
"""
import structlog
import logging

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
)

from backend.api.app import create_app

app = create_app()
