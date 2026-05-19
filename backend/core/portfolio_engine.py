"""
portfolio_engine.py – Full reconciliation against Binance, PnL analytics,
equity curve tracking, drift detection, and startup gating.

Integrated methods (previously in portfolio_engine_extension.py):
- get_account_info()     → full unified Spot + Futures snapshot → AccountInfo
- get_balance_summary()  → aggregated USDT summary → BalanceSummary
- _usdt_value()          → price lookup helper (USDT/BUSD pass-through)
- _cached_equity         → fallback equity for get_account_info() error path
"""
from __future__ import annotations

import asyncio
import statistics
from datetime import datetime, timezone
from typing import Dict, List, Optional

import structlog

from backend.config import get_settings
from backend.models import (
    AccountInfo,
    AssetBalance,
    BalanceSummary,
    FuturesAsset,
    Position,
    PositionSide,
    ReconciliationResult,
    Trade,
)

log = structlog.get_logger(__name__)
settings = get_settings()


def _usdt_value(asset: str, amount: float) -> float:
    """Convert asset amount to approximate USDT value.
    USDT / BUSD / FDUSD are 1:1. Other assets return 0 until PriceCache is wired.
    TODO: inject BinanceClient.get_all_ticker_prices() result here.
    """
    if asset in ("USDT", "BUSD", "FDUSD"):
        return amount
    return 0.0


class PortfolioEngine:
    """
    Single source of truth for account state.
    `is_ready` is gated by successful reconciliation — no trading until True.
    """

    def __init__(self, binance_client, risk_manager=None):
        self._client = binance_client
        self._risk   = risk_manager
        self.positions: Dict[str, Position]      = {}
        self.account: Optional[AccountInfo]      = None
        self.trades: List[Trade]                 = []
        self.is_ready: bool                      = False
        self._equity_curve: List[float]          = []
        self._last_reconcile: Optional[datetime] = None
        self._cached_equity: float               = 0.0

    # ── Reconciliation ────────────────────────────────────────────────────────────

    async def reconcile(self) -> ReconciliationResult:
        """Full reconciliation: compare Binance state vs local state.
        MUST succeed before trading is allowed (blocks is_ready gate).
        """
        log.info("reconciliation_start")
        errors:           List[str] = []
        positions_synced: int       = 0
        drift_detected:   bool      = False

        try:
            account_data = await self._client.get_account()
            if not account_data:
                raise RuntimeError("Empty account response from Binance")

            # Parse equity from either Spot or Futures account format
            if "balances" in account_data:                          # Spot
                balances: Dict[str, float] = {
                    b["asset"]: float(b["free"]) + float(b["locked"])
                    for b in account_data["balances"]
                    if float(b["free"]) + float(b["locked"]) > 0
                }
                equity = balances.get("USDT", 0.0)
            else:                                                   # Futures
                equity      = float(account_data.get("totalWalletBalance", 0.0))
                unrealized  = float(account_data.get("totalUnrealizedProfit", 0.0))
                equity     += unrealized
                balances    = {}

            self._cached_equity = equity
            self.account = AccountInfo(
                total_equity        = equity,
                total_wallet_balance= equity,
                available_balance   = float(
                    account_data.get(
                        "availableBalance",
                        account_data.get("totalAvailableBalance", equity)
                    )
                ),
                unrealized_pnl              = float(account_data.get("totalUnrealizedProfit", 0.0)),
                total_unrealized_profit     = float(account_data.get("totalUnrealizedProfit", 0.0)),
                balances                    = balances,
                can_trade                   = account_data.get("canTrade", True),
                can_withdraw                = account_data.get("canWithdraw", True),
                can_deposit                 = account_data.get("canDeposit", True),
            )

            if self._risk:
                self._risk.update_equity(equity)
            self._equity_curve.append(equity)

            # Sync futures open positions
            if settings.futures_enabled:
                exchange_positions = await self._client.get_positions()
                live_symbols: set  = set()

                for ep in exchange_positions:
                    sym = ep["symbol"]
                    amt = float(ep.get("positionAmt", 0))
                    if abs(amt) < 1e-9:
                        continue
                    live_symbols.add(sym)
                    side     = PositionSide.LONG if amt > 0 else PositionSide.SHORT
                    ep_price = float(ep.get("entryPrice", 0))

                    if sym not in self.positions:
                        log.warning("drift_position_added", symbol=sym, amt=amt)
                        drift_detected = True
                        sl_mult  = 0.98 if side == PositionSide.LONG else 1.02
                        tp1_mult = 1.03 if side == PositionSide.LONG else 0.97
                        tp2_mult = 1.06 if side == PositionSide.LONG else 0.94
                        self.positions[sym] = Position(
                            symbol        = sym,
                            side          = side,
                            entry_price   = ep_price,
                            quantity      = abs(amt),
                            stop_loss     = ep_price * sl_mult,
                            take_profit_1 = ep_price * tp1_mult,
                            take_profit_2 = ep_price * tp2_mult,
                        )
                        if self._risk:
                            self._risk.position_opened(sym)
                    else:
                        self.positions[sym].quantity   = abs(amt)
                        self.positions[sym].updated_at = datetime.utcnow()

                    positions_synced += 1

                for sym in list(self.positions.keys()):
                    if sym not in live_symbols:
                        log.warning("drift_position_removed", symbol=sym)
                        drift_detected = True
                        del self.positions[sym]
                        if self._risk:
                            self._risk.position_closed(sym)

            self.is_ready         = True
            self._last_reconcile  = datetime.utcnow()
            log.info("reconciliation_ok", equity=equity,
                     positions=positions_synced, drift=drift_detected)

        except Exception as exc:
            errors.append(str(exc))
            log.error("reconciliation_failed", error=str(exc))
            self.is_ready = False

        return ReconciliationResult(
            success          = self.is_ready,
            equity           = self.account.total_equity if self.account else 0.0,
            positions_synced = positions_synced,
            drift_detected   = drift_detected,
            errors           = errors,
            timestamp        = datetime.utcnow(),
        )

    # ── Account Info (Spot + Futures unified) ───────────────────────────────────

    async def get_account_info(self) -> AccountInfo:
        """Fetch full Binance account snapshot — Spot balances + Futures assets.
        Returns a cached/empty AccountInfo on error (never raises, never 500).
        """
        try:
            spot_raw, futs_raw = await asyncio.gather(
                self._client.get_spot_account(),
                self._client.get_futures_account(),
                return_exceptions=True,
            )

            # ── Spot balances ──
            spot_assets: List[AssetBalance] = []
            if isinstance(spot_raw, dict) and "balances" in spot_raw:
                for a in spot_raw["balances"]:
                    total = float(a["free"]) + float(a["locked"])
                    if total > 1e-9:
                        spot_assets.append(
                            AssetBalance(
                                asset         = a["asset"],
                                free          = float(a["free"]),
                                locked        = float(a["locked"]),
                                total         = total,
                                usdt_valuation= _usdt_value(a["asset"], total),
                            )
                        )
                spot_assets.sort(key=lambda x: -x.usdt_valuation)

            # ── Futures assets ──
            futures_assets: List[FuturesAsset] = []
            if isinstance(futs_raw, dict) and "assets" in futs_raw:
                for a in futs_raw["assets"]:
                    wb = float(a.get("walletBalance", 0))
                    if wb > 1e-9:
                        futures_assets.append(
                            FuturesAsset(
                                asset               = a["asset"],
                                wallet_balance      = wb,
                                unrealized_profit   = float(a.get("unrealizedProfit", 0)),
                                margin_balance      = float(a.get("marginBalance", wb)),
                                maint_margin        = float(a.get("maintMargin", 0)),
                                initial_margin      = float(a.get("initialMargin", 0)),
                                available_balance   = float(a.get("availableBalance", wb)),
                                max_withdraw_amount = float(a.get("maxWithdrawAmount", 0)),
                                margin_available    = a.get("marginAvailable", True),
                                update_time         = int(a.get("updateTime", 0)),
                            )
                        )

            total_spot      = sum(a.usdt_valuation for a in spot_assets)
            total_futs_wal  = sum(a.wallet_balance for a in futures_assets)
            total_unreal    = sum(a.unrealized_profit for a in futures_assets)
            total_avail     = sum(a.available_balance for a in futures_assets)
            total_equity    = total_spot + total_futs_wal + total_unreal
            self._cached_equity = total_equity

            spot_data = spot_raw if isinstance(spot_raw, dict) else {}
            futs_data = futs_raw if isinstance(futs_raw, dict) else {}

            return AccountInfo(
                total_equity                     = total_equity,
                total_wallet_balance             = total_spot + total_futs_wal,
                total_unrealized_profit          = total_unreal,
                total_margin_balance             = total_futs_wal + total_unreal,
                available_balance                = total_avail,
                total_position_initial_margin    = float(futs_data.get("totalPositionInitialMargin", 0)),
                total_open_order_initial_margin  = float(futs_data.get("totalOpenOrderInitialMargin", 0)),
                max_withdraw_amount              = float(futs_data.get("maxWithdrawAmount", 0)),
                assets                           = spot_assets,
                futures_assets                   = futures_assets,
                balances                         = {a.asset: a.total for a in spot_assets},
                can_trade                        = spot_data.get("canTrade", True),
                can_withdraw                     = spot_data.get("canWithdraw", True),
                can_deposit                      = spot_data.get("canDeposit", True),
                update_time                      = spot_data.get("updateTime", 0),
                account_type                     = "UNIFIED",
                maker_commission                 = spot_data.get("makerCommission", 10),
                taker_commission                 = spot_data.get("takerCommission", 10),
                unrealized_pnl                   = total_unreal,
            )

        except Exception as exc:
            log.error("get_account_info_failed", error=str(exc))
            return AccountInfo(
                total_equity         = self._cached_equity,
                total_wallet_balance = self._cached_equity,
                available_balance    = self._cached_equity,
                unrealized_pnl       = 0.0,
                total_unrealized_profit = 0.0,
            )

    # ── Balance Summary ───────────────────────────────────────────────────────────

    async def get_balance_summary(self) -> BalanceSummary:
        """Aggregated USDT summary for the quick-glance dashboard panel."""
        try:
            info     = await self.get_account_info()
            spot_val = sum(a.usdt_valuation    for a in info.assets)
            futs_wal = sum(a.wallet_balance    for a in info.futures_assets)
            unreal   = sum(a.unrealized_profit for a in info.futures_assets)
            avail    = sum(a.available_balance for a in info.futures_assets)
            # Add free spot USDT
            avail   += sum(a.free for a in info.assets if a.asset == "USDT")
            total    = spot_val + futs_wal + unreal
            init_mar = info.total_position_initial_margin + info.total_open_order_initial_margin
            used_pct = round((init_mar / max(total, 1)) * 100, 2)

            return BalanceSummary(
                total_usdt_value   = total,
                spot_usdt_value    = spot_val,
                futures_usdt_value = futs_wal + unreal,
                unrealized_pnl     = unreal,
                available_margin   = avail,
                used_margin_pct    = used_pct,
                top_assets         = info.assets[:6],
                last_updated       = datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            log.error("get_balance_summary_failed", error=str(exc))
            return BalanceSummary(
                last_updated=datetime.now(timezone.utc).isoformat()
            )

    # ── Position management ────────────────────────────────────────────────────────

    def add_position(self, position: Position) -> None:
        self.positions[position.symbol] = position

    def remove_position(self, symbol: str) -> Optional[Position]:
        return self.positions.pop(symbol, None)

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def record_trade(self, trade: Trade) -> None:
        self.trades.append(trade)
        if trade.realized_pnl:
            self._cached_equity += trade.realized_pnl
            self._equity_curve.append(self._cached_equity)

    # ── Analytics ────────────────────────────────────────────────────────────────

    def get_analytics(self) -> dict:
        if not self.trades:
            return {
                "total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                "expectancy":   0.0, "sharpe": 0.0, "r_multiples": [],
                "equity_curve": self._equity_curve[-100:],
            }
        pnls         = [t.realized_pnl for t in self.trades]
        wins         = [p for p in pnls if p > 0]
        losses       = [p for p in pnls if p <= 0]
        gross_profit = sum(wins)
        gross_loss   = abs(sum(losses))
        r_multiples  = []
        for t in self.trades:
            risk = abs(t.entry_price - t.stop_loss) if t.stop_loss else 1
            if risk > 0:
                r_multiples.append(round(t.realized_pnl / risk, 3))

        return {
            "total_trades":  len(self.trades),
            "win_rate":      round(len(wins) / len(pnls), 4),
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else 0.0,
            "expectancy":    round(sum(pnls) / len(pnls), 4),
            "sharpe":        round(self._sharpe(pnls), 4),
            "r_multiples":   r_multiples,
            "equity_curve":  self._equity_curve[-100:],
        }

    def _sharpe(self, pnls: List[float]) -> float:
        if len(pnls) < 2:
            return 0.0
        avg = statistics.mean(pnls)
        std = statistics.stdev(pnls)
        return (avg / std) if std else 0.0
