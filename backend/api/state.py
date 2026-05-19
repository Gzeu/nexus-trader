"""
state.py – AppState: wires all components into a single shared container.

Fixes / improvements over v1:
- `set_exchange_info()` removed — function doesn't exist in v3 ExecutionEngine
  (ExecutionEngine.setup() handles its own exchange_info refresh internally)
- `execution_engine` constructed with correct signature (spot, futures, ws_broadcast)
- `automation_engine` constructed with correct v3 signature
- Per-symbol CompositeStrategy dict passed to automation ("*" fallback key)
- futures_client only opened/passed when futures_enabled
- `ws_broadcast` callable passed to execution so post_fill() can emit WS events
- `telegram_alerts` instance created and passed to automation
- `start_time` tracked for uptime metric
"""
from __future__ import annotations

import time

import structlog

from backend.binance.binance_client import BinanceClient
from backend.config import Settings, get_settings
from backend.core.automation_engine import AutomationEngine, EventEmitter
from backend.core.execution_engine import ExecutionEngine
from backend.core.portfolio_engine import PortfolioEngine
from backend.core.risk_manager import RiskManager
from backend.core.strategy_engine import (
    BreakoutStrategy,
    CompositeStrategy,
    MeanReversionStrategy,
    TrendFollowingStrategy,
)
from backend.journal.journal import TradeJournal
from backend.journal.telegram_alerts import TelegramAlerter

log = structlog.get_logger(__name__)


class AppState:
    """Central dependency container — one instance per process."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.start_time: float = time.monotonic()

        # Binance clients
        self.spot_client = BinanceClient(mode="SPOT")
        self.futures_client: BinanceClient | None = (
            BinanceClient(mode="FUTURES") if self.settings.futures_enabled else None
        )

        # Core components (initialized in setup())
        self.risk = RiskManager()
        self.portfolio: PortfolioEngine | None = None
        self.execution: ExecutionEngine | None = None
        self.automation: AutomationEngine | None = None
        self.journal = TradeJournal()
        self.telegram = TelegramAlerter()
        self.emitter = EventEmitter()

        # WS broadcast callable — set by websocket.py after app creation
        self.ws_broadcast = None

    async def setup(self) -> None:
        """Async init: open HTTP sessions, build all components."""
        log.info("state_setup_begin")

        # Open HTTP clients
        await self.spot_client.__aenter__()
        if self.futures_client is not None:
            await self.futures_client.__aenter__()

        # Journal + telegram
        await self.journal.setup()

        # Execution engine: handles its own exchange_info cache refresh in setup()
        self.execution = ExecutionEngine(
            spot_client=self.spot_client,
            futures_client=self.futures_client,
            ws_broadcast=self._ws_broadcast_wrapper,
        )
        await self.execution.setup()

        # Portfolio engine
        self.portfolio = PortfolioEngine(
            binance_client=self.spot_client,
            risk_manager=self.risk,
        )

        # Build per-symbol strategy dict for automation
        # Key = symbol, "*" = fallback for any unlisted symbol
        strategy_map = {}
        whitelist = self.settings.symbol_whitelist
        for sym in whitelist:
            tf = TrendFollowingStrategy(sym, self.settings.primary_timeframe)
            mr = MeanReversionStrategy(sym, self.settings.primary_timeframe)
            bo = BreakoutStrategy(sym, self.settings.primary_timeframe)
            strategy_map[sym] = CompositeStrategy(
                strategies=[(tf, 0.4), (mr, 0.3), (bo, 0.3)],
                symbol=sym,
                timeframe=self.settings.primary_timeframe,
            )

        self.automation = AutomationEngine(
            strategy=strategy_map,
            portfolio_engine=self.portfolio,
            risk_manager=self.risk,
            execution_engine=self.execution,
            binance_client=self.spot_client,
            ws_broadcast=self._ws_broadcast_wrapper,
            journal=self.journal,
            telegram=self.telegram,
        )

        log.info("state_setup_complete", symbols=whitelist)

    async def _ws_broadcast_wrapper(self, event_type, payload: dict) -> None:
        """Forward events to the WebSocket hub if it's been registered."""
        if self.ws_broadcast is not None:
            try:
                await self.ws_broadcast(event_type, payload)
            except Exception as exc:
                log.warning("ws_broadcast_error", error=str(exc))
