"""
AppState — dependency injection container pentru FastAPI.
Wiring complet: BinanceClient -> PriceCache -> PortfolioEngine -> engines.
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.binance.binance_client import BinanceClient
from backend.config import get_settings
from backend.core.automation_engine import AutomationEngine
from backend.core.execution_engine import ExecutionEngine
from backend.core.ohlcv_provider import OHLCVProvider
from backend.core.portfolio_engine import PortfolioEngine
from backend.core.price_cache import PriceCache
from backend.core.risk_manager import RiskManager
from backend.core.strategy_engine import CompositeStrategy
from backend.journal.trade_journal import TradeJournal
from backend.journal.telegram_alerts import TelegramAlerter

logger = logging.getLogger(__name__)


class AppState:
    """
    Singleton container — initializat o singura data in lifespan.
    Toate componentele sunt accesate prin Depends(get_state).

    NOTE (Pydantic v2): BaseSettings normalizeaza campurile la lowercase.
    Foloseste cfg.telegram_bot_token, cfg.dry_run, cfg.market_mode etc.
    NOTE (ExecutionEngine): __init__ primeste spot_client/futures_client/
    ws_broadcast, nu 'client' sau 'dry_run' — dry_run este citit intern
    din get_settings().
    """

    def __init__(self) -> None:
        cfg = get_settings()

        # ── Infrastructure ─────────────────────────────────────────
        self.client = BinanceClient()
        self.price_cache = PriceCache(self.client, refresh_interval=30.0)
        self.ohlcv = OHLCVProvider(self.client)
        self.journal = TradeJournal()
        self.telegram = TelegramAlerter(
            token=cfg.telegram_bot_token,
            chat_id=cfg.telegram_chat_id,
        )

        # ── Core engines ───────────────────────────────────────────
        self.portfolio = PortfolioEngine(
            client=self.client,
            price_cache=self.price_cache,
            mode=cfg.market_mode,
        )
        self.risk = RiskManager()

        # ExecutionEngine.__init__(self, spot_client, futures_client=None, ws_broadcast=None)
        # dry_run este citit intern din get_settings() — nu se paseaza ca argument
        self.execution = ExecutionEngine(
            spot_client=self.client,
            futures_client=None,          # se poate inlocui cu un FuturesClient dedicat
            ws_broadcast=None,            # se seteaza post-init in setup() dupa ce WS hub e gata
        )
        self.strategy = CompositeStrategy(
            symbols=cfg.symbol_whitelist,
        )
        self.automation = AutomationEngine(
            strategy=self.strategy,
            ohlcv=self.ohlcv,
            risk=self.risk,
            execution=self.execution,
            portfolio=self.portfolio,
            journal=self.journal,
            telegram=self.telegram,
        )

    async def setup(self) -> None:
        """Porneste toate serviciile async in ordine corecta."""
        cfg = get_settings()
        await self.client.start()
        logger.info(
            "BinanceClient started (testnet=%s, dry_run=%s)",
            cfg.testnet,
            cfg.dry_run,
        )

        await self.price_cache.start()
        ready = await self.price_cache.wait_ready(timeout=15.0)
        if not ready:
            logger.warning("PriceCache not ready after 15s — continuing anyway")

        await self.execution.setup()
        logger.info("ExecutionEngine initialized (idempotency store ready)")

        await self.journal.init()
        logger.info("TradeJournal initialized")

        result = await self.portfolio.reconcile()
        if result.success:
            logger.info("Reconciliation OK — trading enabled")
        else:
            logger.error(
                "Reconciliation FAILED: %s — trading BLOCKED", result.error
            )

        await self.automation.start()
        logger.info("AutomationEngine started")

    async def teardown(self) -> None:
        """Opreste toate serviciile in ordine inversa."""
        await self.automation.stop()
        await self.price_cache.stop()
        await self.client.stop()
        logger.info("AppState teardown complete")


_state: Optional[AppState] = None


def get_state() -> AppState:
    """FastAPI Depends() factory — returneaza singleton-ul AppState."""
    if _state is None:
        raise RuntimeError("AppState not initialized — call init_state() first")
    return _state


def init_state() -> AppState:
    global _state
    _state = AppState()
    return _state
