"""
portfolio_engine.py – Full reconciliation (Spot + Futures), PnL analytics,
equity curve, drift detection, startup gating.

Fixes applied:
- Constructor now accepts (spot_client, futures_client=None, risk_manager=None)
  — was missing futures_client → crashed when state.py passed 3 args
- get_summary() method added — was missing → AttributeError on GET /metrics
- Spot open positions cross-checked via get_open_orders() per symbol
- _sharpe_trade_by_trade() documented as non-annualized
"""
from __future__ import annotations

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
    is_ready gates all trading — set True only after successful reconcile().
    """

    def __init__(
        self,
        spot_client,
        futures_client=None,
        risk_manager=None,
    ):
        self._spot = spot_client
        self._futures = futures_client
        self._risk = risk_manager
        self.positions: Dict[str, Position] = {}
        self.account: Optional[AccountInfo] = None
        self.trades: List[Trade] = []
        self.is_ready: bool = False
        self._equity_curve: List[float] = []
        self._last_reconcile: Optional[datetime] = None

    # ── Reconciliation ────────────────────────────────────────────────────

    async def reconcile(self) -> ReconciliationResult:
        """
        Full reconciliation: sync Binance state → local state.
        Blocks trading (is_ready=False) until this succeeds.
        """
        log.info("reconciliation_start")
        errors: List[str] = []
        positions_synced = 0
        drift_detected = False

        try:
            # ─ Account & Equity ─────────────────────────────────────────
            account_data = await self._spot.get_account()
            if not account_data:
                raise RuntimeError("Empty account response from Binance")

            balances = {
                b["asset"]: float(b["free"]) + float(b["locked"])
                for b in account_data.get("balances", [])
                if float(b["free"]) + float(b["locked"]) > 0
            }
            equity = balances.get("USDT", 0.0)
            self.account = AccountInfo(
                total_equity=equity,
                available_balance=float(
                    account_data.get("totalAvailableBalance", equity)
                ),
                unrealized_pnl=float(account_data.get("totalUnrealizedProfit", 0)),
                balances=balances,
                can_trade=account_data.get("canTrade", True),
            )

            if self._risk:
                self._risk.update_equity(equity)
                self._equity_curve.append(equity)

            # ─ Futures positions ──────────────────────────────────────
            if settings.futures_enabled and self._futures:
                exchange_positions = await self._futures.get_positions()
                live_symbols: set = set()

                for ep in exchange_positions:
                    sym = ep["symbol"]
                    amt = float(ep.get("positionAmt", 0))
                    if abs(amt) < 1e-9:
                        continue
                    live_symbols.add(sym)
                    side = PositionSide.LONG if amt > 0 else PositionSide.SHORT
                    ep_price = float(ep.get("entryPrice", 0))

                    if sym not in self.positions:
                        log.warning("drift_position_added", symbol=sym, amt=amt)
                        drift_detected = True
                        self.positions[sym] = Position(
                            symbol=sym,
                            side=side,
                            entry_price=ep_price,
                            quantity=abs(amt),
                            market_mode=settings.futures_market_mode,
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

                # Local has position that exchange doesn't → drift
                for sym in list(self.positions.keys()):
                    if sym not in live_symbols:
                        log.warning("drift_position_removed", symbol=sym)
                        drift_detected = True
                        del self.positions[sym]
                        if self._risk:
                            self._risk.position_closed(sym)

            # ─ Spot cross-check via open orders ───────────────────────
            # Spot doesn't have a dedicated positions endpoint; we cross-check
            # by verifying that local positions still have open orders on exchange.
            # If not, log a warning and flag for manual review (don't auto-remove).
            if not settings.futures_enabled:
                for sym in list(self.positions.keys()):
                    try:
                        open_orders = await self._spot.get_open_orders(sym)
                        if not open_orders:
                            log.warning(
                                "spot_position_no_open_orders",
                                symbol=sym,
                                note="Position exists locally but no open orders on exchange. Manual review required.",
                            )
                    except Exception as exc:
                        log.warning("spot_open_orders_check_failed", symbol=sym, error=str(exc))

            self.is_ready = True
            self._last_reconcile = datetime.utcnow()
            log.info(
                "reconciliation_ok",
                equity=equity,
                positions=positions_synced,
                drift=drift_detected,
            )

        except Exception as exc:
            errors.append(str(exc))
            log.error("reconciliation_failed", error=str(exc))
            self.is_ready = False

        return ReconciliationResult(
            success=self.is_ready,
            equity=self.account.total_equity if self.account else 0.0,
            positions_synced=positions_synced,
            drift_detected=drift_detected,
            errors=errors,
            timestamp=datetime.utcnow(),
        )

    # ── Position helpers ──────────────────────────────────────────────────

    def add_position(self, position: Position) -> None:
        self.positions[position.symbol] = position

    def remove_position(self, symbol: str) -> Optional[Position]:
        return self.positions.pop(symbol, None)

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def record_trade(self, trade: Trade) -> None:
        self.trades.append(trade)

    # ── Analytics ──────────────────────────────────────────────────────────

    def get_summary(self) -> dict:
        """Top-level summary dict used by GET /metrics endpoint."""
        analytics = self.get_analytics()
        return {
            "equity": self.account.total_equity if self.account else 0.0,
            "available_balance": self.account.available_balance if self.account else 0.0,
            "unrealized_pnl": self.account.unrealized_pnl if self.account else 0.0,
            "open_positions": len(self.positions),
            "last_reconcile": (
                self._last_reconcile.isoformat() if self._last_reconcile else None
            ),
            **analytics,
        }

    def get_analytics(self) -> dict:
        """Full trade analytics: win rate, profit factor, Sharpe, R-multiples."""
        if not self.trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "sharpe": 0.0,
                "r_multiples": [],
                "equity_curve": self._equity_curve[-100:],
            }

        pnls = [t.realized_pnl for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses)) if losses else 0.0

        r_multiples = []
        for t in self.trades:
            risk = abs(t.entry_price - t.stop_loss) if getattr(t, "stop_loss", None) else 1.0
            if risk > 0:
                r_multiples.append(t.realized_pnl / risk)

        return {
            "total_trades": len(self.trades),
            "win_rate": len(wins) / len(pnls),
            "profit_factor": gross_profit / gross_loss if gross_loss else 0.0,
            "expectancy": sum(pnls) / len(pnls),
            "sharpe": self._sharpe_trade_by_trade(pnls),
            "r_multiples": r_multiples,
            "equity_curve": self._equity_curve[-100:],
        }

    def _sharpe_trade_by_trade(self, pnls: List[float]) -> float:
        """
        Trade-by-trade Sharpe ratio (NOT annualized).
        Measures consistency of PnL per trade — not suitable for time-based comparison.
        For annualized Sharpe, multiply by sqrt(trades_per_year).
        """
        if len(pnls) < 2:
            return 0.0
        import statistics
        avg = statistics.mean(pnls)
        std = statistics.stdev(pnls)
        return (avg / std) if std else 0.0
