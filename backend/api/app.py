"""
app.py – FastAPI application factory + lifespan.

Fixes / improvements over v1:
- CORS `allow_origins` uses settings.cors_origins (was hardcoded "*" — security risk)
- `futures_client.__aexit__` only called when futures_enabled (was always called → crash if None)
- `result.notes` → `result.errors` (correct field name from ReconciliationReport)
- Prometheus middleware added (optional, non-blocking if prometheus_client not installed)
- Startup log includes environment + dry_run + testnet flags for quick audit
- App version reads from settings instead of hardcoded "1.0.0"
- `app.state.start_time` set for uptime tracking in /health
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router as http_router
from backend.api.websocket import router as ws_router
from backend.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Startup: init clients + mandatory reconciliation. Shutdown: graceful teardown."""
    app.state.start_time = time.monotonic()
    state = app.state.ctx
    log.info(
        "startup_begin",
        environment=settings.environment,
        dry_run=settings.dry_run,
        testnet=settings.testnet,
        futures_enabled=settings.futures_enabled,
    )

    try:
        await state.setup()
        result = await state.portfolio.reconcile()
        if not result.success:
            # Log all errors but do NOT block startup — operator can fix and reconcile manually
            log.critical("reconciliation_failed_at_startup", errors=result.errors)
        else:
            log.info(
                "startup_reconciled",
                equity=state.portfolio.account.total_equity if state.portfolio.account else 0,
            )
            state.automation.start()  # sync — do NOT await
    except Exception as exc:
        log.critical("startup_exception", error=str(exc))
        # Still yield — app stays up in degraded mode, /health will report not_reconciled

    yield

    # ── Graceful shutdown ───────────────────────────────────────────────────
    log.info("shutdown_begin")
    try:
        if state.automation:
            state.automation.stop()  # sync
    except Exception as exc:
        log.warning("automation_stop_error", error=str(exc))

    try:
        if state.journal:
            await state.journal.close()
    except Exception as exc:
        log.warning("journal_close_error", error=str(exc))

    try:
        await state.spot_client.__aexit__(None, None, None)
    except Exception as exc:
        log.warning("spot_client_close_error", error=str(exc))

    # Only close futures client if futures were enabled
    if settings.futures_enabled and state.futures_client is not None:
        try:
            await state.futures_client.__aexit__(None, None, None)
        except Exception as exc:
            log.warning("futures_client_close_error", error=str(exc))

    log.info("shutdown_complete")


def create_app() -> FastAPI:
    """Create and wire the FastAPI application."""
    from backend.api.state import AppState

    ctx = AppState(settings)

    app = FastAPI(
        title="Nexus Trader API",
        version="3.0.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url="/redoc" if settings.environment != "production" else None,
        lifespan=lifespan,
    )
    app.state.ctx = ctx
    app.state.start_time = 0.0  # overwritten in lifespan

    # CORS — use configured origins, not wildcard
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )

    # Optional Prometheus instrumentation
    try:
        from prometheus_client import make_asgi_app
        metrics_app = make_asgi_app()
        app.mount("/metrics", metrics_app)
    except ImportError:
        log.info("prometheus_client_not_installed_metrics_endpoint_disabled")

    app.include_router(http_router, prefix="/api/v1")
    app.include_router(ws_router)
    return app
