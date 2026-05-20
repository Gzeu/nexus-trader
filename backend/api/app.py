"""
FastAPI application factory + lifespan.

CHANGELOG:
  🟠 reconcile() wrapped in asyncio.wait_for(timeout=30s) — nu mai poate bloca
     startup-ul la infinit daca Binance e lent sau API key-ul e invalid.
     La timeout: serverul porneste in stare not_reconciled (trading blocat),
     logheza CRITICAL si trimite Telegram alert.
  🟢 settings_routes inregistrat in create_app() — GET/PATCH /api/v1/settings functional.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router as main_router
from backend.api.settings_routes import router as settings_router
from backend.api.state import AppState, set_state
from backend.api.websocket import manager as ws_manager
from backend.api.websocket import router as ws_router
from backend.config import get_settings

logger = logging.getLogger(__name__)

RECONCILE_TIMEOUT_S = 30  # secunde — configurabil daca necesitar


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: reconciliere cu timeout + automation start. Shutdown: cleanup."""
    cfg = get_settings()
    state = AppState(cfg)
    await state.setup()
    set_state(state)

    # Injecteaza Telegram in WS manager pentru RISK_EVENT alerts
    if state.telegram:
        ws_manager.set_telegram(state.telegram)

    # ── Startup reconciliation cu timeout ────────────────────────────────────
    # 🟠 FIX: asyncio.wait_for previne blocajul infinit la startup.
    # Daca Binance nu raspunde in RECONCILE_TIMEOUT_S secunde:
    #   - serverul porneste (health check raspunde)
    #   - is_ready = False => toate ordinele sunt blocate
    #   - CRITICAL log + Telegram alert
    # Automation-ul NU porneste pana la reconciliere reusita.
    try:
        result = await asyncio.wait_for(
            state.portfolio.reconcile(),
            timeout=RECONCILE_TIMEOUT_S,
        )
        if result.success:
            logger.info(
                "Startup reconciliation OK — equity=%.2f positions=%d orders=%d",
                result.equity,
                result.positions_synced,
                result.orders_synced,
            )
            # Porneste automation doar dupa reconciliere reusita
            await state.automation.start()
            logger.info("AutomationEngine started")
        else:
            logger.critical(
                "Startup reconciliation FAILED: %s — trading blocked",
                result.error,
            )
            if state.telegram:
                await state.telegram.send_alert(
                    f"🚨 Reconciliere esuat la startup: {result.error}\nTrading BLOCAT."
                )
    except asyncio.TimeoutError:
        logger.critical(
            "Startup reconciliation TIMEOUT (%ds) — trading blocked",
            RECONCILE_TIMEOUT_S,
        )
        if state.telegram:
            try:
                await state.telegram.send_alert(
                    f"🚨 Reconciliere TIMEOUT ({RECONCILE_TIMEOUT_S}s) la startup.\n"
                    "Verifica API key Binance + conectivitate.\nTrading BLOCAT."
                )
            except Exception:
                pass
    except Exception as exc:
        logger.critical("Startup reconciliation unexpected error: %s", exc, exc_info=True)

    yield  # ── aplicatia ruleaza ─────────────────────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down...")
    try:
        await state.automation.stop()
    except Exception as exc:
        logger.warning("Automation stop error: %s", exc)
    try:
        await state.client.close()
    except Exception as exc:
        logger.warning("Binance client close error: %s", exc)
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(
        title="NexusTrader API",
        version="1.0.0",
        docs_url="/docs" if not cfg.is_production else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(main_router, prefix="/api/v1")
    app.include_router(settings_router)   # prefix /api/v1 definit intern in settings_routes.py
    app.include_router(ws_router)

    return app
