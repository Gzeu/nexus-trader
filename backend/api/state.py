"""
state.py – Wires all engine components into a single AppState instance
shared across the request lifecycle via app.state.ctx.
"""
from __future__ import annotations

from backend.binance.binance_client import BinanceClient
from backend.config import Settings, get_settings
from backend.core.automation_engine import AutomationEngine, EventEmitter
from backend.core.execution_engine import ExecutionEngine, set_exchange_info
from backend.core.portfolio_engine import PortfolioEngine
from backend.core.risk_manager import RiskManager
from backend.core.strategy_engine import (
    BreakoutStrategy,
    CompositeStrategy,
    MeanReversionStrategy,
    TrendFollowingStrategy,
)
from backend.journal.journal import TradeJournal
from backend.models import MarketMode


class AppState:
    """Central dependency container. Instantiated once in create_app()."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        # Binance clients (async httpx, entered in setup())
        self.spot_client = BinanceClient(mode="SPOT")
        self.futures_client = BinanceClient(mode="FUTURES")
        # Core engines (set in setup())
        self.risk: RiskManager | None = None
        self.portfolio: PortfolioEngine | None = None
        self.execution: ExecutionEngine | None = None
        self.automation: AutomationEngine | None = None
        # Journal + event bus
        self.journal = TradeJournal()
        self.emitter = EventEmitter()

    async def setup(self) -> None:
        """Open HTTP sessions, load exchangeInfo, wire all engines."""
        await self.spot_client.__aenter__()
        await self.futures_client.__aenter__()

        # Load exchangeInfo once; ExecutionEngine uses it for normalization
        info = await self.spot_client.get_exchange_info()
        set_exchange_info(info)

        self.risk = RiskManager()

        self.execution = ExecutionEngine(
            client=self.spot_client,
            event_emitter=self.emitter.emit,
        )

        self.portfolio = PortfolioEngine(
            spot_client=self.spot_client,
            futures_client=self.futures_client,
            risk_manager=self.risk,
        )

        # Build one CompositeStrategy per whitelisted spot symbol
        strategies: list[CompositeStrategy] = []
        for sym in self.settings.spot_whitelist:
            tf = TrendFollowingStrategy(sym, "5m")
            mr = MeanReversionStrategy(sym, "15m")
            bo = BreakoutStrategy(sym, "1h")
            composite = CompositeStrategy(
                strategies=[(tf, 0.4), (mr, 0.3), (bo, 0.3)],
                symbol=sym,
                timeframe="5m",
            )
            strategies.append(composite)

        self.automation = AutomationEngine(
            strategies=strategies,
            risk_manager=self.risk,
            execution_engine=self.execution,
            portfolio_engine=self.portfolio,
            binance_client=self.spot_client,
            market_mode=MarketMode.SPOT,
            interval=self.settings.automation_interval,
        )

        await self.journal.setup()
