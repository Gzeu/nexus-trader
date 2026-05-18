"""
portfolio_engine.py – Full reconciliation against Binance, PnL analytics,
equity curve tracking, drift detection, and startup gating.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict, List, Optional

import structlog

from backend.config import get_settings
from backend.models import AccountInfo, Position, PositionSide, ReconciliationResult, Trade

log = structlog.get_logger(__name__)
settings = get_settings()


class PortfolioEngine:
    """
    Single source of truth for account state.
    is_ready is gated by successful reconciliation.
    """

    def __init__(self, binance_client, risk_manager=None):
        self._client = binance_client
        self._risk = risk_manager
        self.positions: Dict[str, Position] = {}
        self.account: Optional[AccountInfo] = None
        self.trades: List[Trade] = []
        self.is_ready: bool = False
        self._equity_curve: List[float] = []
        self._last_reconcile: Optional[datetime] = None

    async def reconcile(self) -> ReconciliationResult:
        """
        Full reconciliation: compare Binance state vs local state.
        MUST succeed before trading is allowed.
        """
        log.info("reconciliation_start")
        errors: List[str] = []
        positions_synced = 0
        drift_detected = False

        try:
            account_data = await self._client.get_account()
            if not account_data:
                raise RuntimeError("Empty account response from Binance")

            # Build AccountInfo
            balances = {b["asset"]: float(b["free"]) + float(b["locked"])
                        for b in account_data.get("balances", []) if float(b["free"]) + float(b["locked"]) > 0}
            equity = balances.get("USDT", 0.0)
            self.account = AccountInfo(
                total_equity=equity,
                available_balance=float(account_data.get("totalAvailableBalance", equity)),
                unrealized_pnl=float(account_data.get("totalUnrealizedProfit", 0)),
                balances=balances,
                can_trade=account_data.get("canTrade", True),
            )

            # Sync equity into risk manager
            if self._risk:
                self._risk.update_equity(equity)
                self._equity_curve.append(equity)

            # Sync futures open positions if applicable
            if settings.futures_enabled:
                exchange_positions = await self._client.get_positions()
                live_symbols = set()
                for ep in exchange_positions:
                    sym = ep["symbol"]
                    amt = float(ep.get("positionAmt", 0))
                    if abs(amt) < 1e-9:
                        continue
                    live_symbols.add(sym)
                    side = PositionSide.LONG if amt > 0 else PositionSide.SHORT
                    ep_price = float(ep.get("entryPrice", 0))
                    if sym not in self.positions:
                        # Drift: exchange has position, local doesn't
                        log.warning("drift_position_added", symbol=sym, amt=amt)
                        drift_detected = True
                        self.positions[sym] = Position(
                            symbol=sym, side=side,
                            entry_price=ep_price, quantity=abs(amt),
                            stop_loss=ep_price * (0.98 if side == PositionSide.LONG else 1.02),
                            take_profit_1=ep_price * (1.03 if side == PositionSide.LONG else 0.97),
                            take_profit_2=ep_price * (1.06 if side == PositionSide.LONG else 0.94),
                        )
                        if self._risk:
                            self._risk.position_opened(sym)
                    else:
                        self.positions[sym].quantity = abs(amt)
                        self.positions[sym].updated_at = datetime.utcnow()
                    positions_synced += 1

                # Drift: local has position, exchange doesn't
                for sym in list(self.positions.keys()):
                    if sym not in live_symbols:
                        log.warning("drift_position_removed", symbol=sym)
                        drift_detected = True
                        del self.positions[sym]
                        if self._risk:
                            self._risk.position_closed(sym)

            self.is_ready = True
            self._last_reconcile = datetime.utcnow()
            log.info("reconciliation_ok", equity=equity, positions=positions_synced, drift=drift_detected)

        except Exception as exc:
            errors.append(str(exc))
            log.error("reconciliation_failed", error=str(exc))
            # We do NOT gate is_ready here – startup will retry
            self.is_ready = False

        return ReconciliationResult(
            success=self.is_ready,
            equity=self.account.total_equity if self.account else 0.0,
            positions_synced=positions_synced,
            drift_detected=drift_detected,
            errors=errors,
            timestamp=datetime.utcnow(),
        )

    def add_position(self, position: Position) -> None:
        self.positions[position.symbol] = position

    def remove_position(self, symbol: str) -> Optional[Position]:
        return self.positions.pop(symbol, None)

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def record_trade(self, trade: Trade) -> None:
        self.trades.append(trade)

    def get_analytics(self) -> dict:
        if not self.trades:
            return {"total_trades": 0, "win_rate": 0, "profit_factor": 0,
                    "expectancy": 0, "sharpe": 0, "r_multiples": []}
        pnls = [t.realized_pnl for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        r_multiples = []
        for t in self.trades:
            risk = abs(t.entry_price - t.stop_loss) if t.stop_loss else 1
            if risk > 0:
                r_multiples.append(t.realized_pnl / risk)

        return {
            "total_trades": len(self.trades),
            "win_rate": len(wins) / len(pnls),
            "profit_factor": gross_profit / gross_loss if gross_loss else 0.0,
            "expectancy": sum(pnls) / len(pnls),
            "sharpe": self._sharpe(pnls),
            "r_multiples": r_multiples,
            "equity_curve": self._equity_curve[-100:],
        }

    def _sharpe(self, pnls: List[float]) -> float:
        if len(pnls) < 2:
            return 0.0
        import statistics
        avg = statistics.mean(pnls)
        std = statistics.stdev(pnls)
        return (avg / std) if std else 0.0
