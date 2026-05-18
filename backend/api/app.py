"""
app.py – FastAPI application factory.
All routers, WebSocket, lifespan (startup reconciliation), and CORS.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router as http_router
from backend.api.websocket import router as ws_router

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Startup: init clients + mandatory reconciliation. Shutdown: graceful teardown."""
    state = app.state.ctx
    log.info("startup_begin")
    await state.setup()
    result = await state.portfolio.reconcile()
    if not result.success:
        log.critical("reconciliation_failed_at_startup", notes=result.notes)
    else:
        log.info("startup_reconciled", equity=state.portfolio.account.total_equity)
        state.automation.start()
    yield
    log.info("shutdown_begin")
    state.automation.stop()
    await state.journal.close()
    await state.spot_client.__aexit__(None, None, None)
    await state.futures_client.__aexit__(None, None, None)
    log.info("shutdown_complete")


def create_app() -> FastAPI:
    """Create and wire the FastAPI application."""
    from backend.api.state import AppState
    from backend.config import get_settings

    ctx = AppState(get_settings())

    app = FastAPI(
        title="Nexus Trader API",
        version="1.0.0",
        docs_url="/docs",
        lifespan=lifespan,
    )
    app.state.ctx = ctx

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(http_router, prefix="/api/v1")
    app.include_router(ws_router)
    return app
