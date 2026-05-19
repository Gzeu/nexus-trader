"""
FastAPI application factory.
Lifespan: setup -> serve -> teardown.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.api.state import init_state, get_state
from backend.api.websocket import router as ws_router
from backend.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup + shutdown managed prin context manager."""
    state = init_state()
    app.state.trading = state
    await state.setup()
    logger.info("=== NexusTrader backend ready ===")
    yield
    logger.info("=== NexusTrader backend shutting down ===")
    await state.teardown()


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(
        title="NexusTrader API",
        version="1.0.0",
        description="Production-grade trading system — Binance + TradingView",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/api/v1")
    app.include_router(ws_router, prefix="/api/v1")

    return app


app = create_app()
