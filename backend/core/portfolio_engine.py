"""
PortfolioEngine — reconciliere Binance <-> state local, PnL analytics.

CHANGELOG:
  🔴 FIX #2: _fetch_raw_equity() calculeaza equity USDT complet pentru spot-only.
     Daca Futures nu e activat, get_futures_account() arunca 400 Bad Request.
     Acum: suma tuturor asset-urilor spot convertite in USDT via price_cache.
  🔴 FIX #3: get_account_info() are fallback explicit pentru spot-only
     (futures_assets=[] in loc de except silentios cu cached 0.0).
  ➕ ADD: update_position() — folosit de automation_engine la partial close.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional

from backend.models import (
    Order,
    Position,
    ReconciliationResult,
    RiskMetrics,
    Trade,
)
from backend.models_extra import (
    AccountInfo,
    AssetBalance,
    BalanceSummary,
    FuturesAsset,
)

if TYPE_CHECKING:
    from backend.binance.binance_client import BinanceClient
    from backend.core.price_cache import PriceCache

logger = logging.getLogger(__name__)


class PortfolioEngine:
    """
    Gestioneaza starea locala a portfoliului si o mentine sincronizata
    cu Binance prin reconciliere periodica si event-driven.
    """

    def __init__(
        self,
        client: "BinanceClient",
        price_cache: "PriceCache",
        mode: str = "spot",  # "spot" | "futures"
    ) -> None:
        self._client       = client
        self._price_cache  = price_cache
        self._mode         = mode

        self._positions: Dict[str, Position]  = {}
        self._open_orders: Dict[str, Order]   = {}
        self._trades: List[Trade]             = []
        self._cached_equity: float            = 0.0

        self._reconciled       = False
        self._reconcile_lock   = asyncio.Lock()

    # ---------------------------------------------------------------- gateway

    @property
    def is_ready(self) -> bool:
        return self._reconciled

    # ------------------------------------------------------------- reconcile

    async def reconcile(self) -> ReconciliationResult:
        """
        Sincronizeaza starea locala cu Binance.
        Apelat la startup (blocant) si periodic.
        """
        async with self._reconcile_lock:
            logger.info("[reconcile] Starting (mode=%s)", self._mode)
            try:
                if self._mode == "futures":
                    remote_positions = await self._client.get_positions()
                    remote_orders    = await self._client.get_open_orders()
                else:
                    remote_positions = []
                    remote_orders    = await self._client.get_open_orders()

                remote_symbols = {
                    p["symbol"]
                    for p in remote_positions
                    if float(p.get("positionAmt", 0)) != 0
                }
                local_symbols  = set(self._positions.keys())

                missing_locally = remote_symbols - local_symbols
                ghost_locally   = local_symbols  - remote_symbols

                if missing_locally:
                    logger.warning("[reconcile] On exchange, not locally: %s", missing_locally)
                if ghost_locally:
                    logger.warning("[reconcile] Locally, not on exchange: %s", ghost_locally)

                self._open_orders = {
                    str(o["orderId"]): Order(
                        id=str(o["orderId"]),
                        symbol=o["symbol"],
                        side=o["side"],
                        type=o["type"],
                        quantity=float(o["origQty"]),
                        price=float(o.get("price") or 0),
                        status=o["status"],
                        created_at=datetime.now(timezone.utc),
                    )
                    for o in remote_orders
                }

                self._cached_equity = await self._fetch_raw_equity()
                self._reconciled    = True

                logger.info(
                    "[reconcile] OK — equity=%.2f positions=%d orders=%d",
                    self._cached_equity,
                    len(remote_symbols),
                    len(self._open_orders),
                )
                return ReconciliationResult(
                    success=True,
                    equity=self._cached_equity,
                    positions_synced=len(remote_symbols),
                    orders_synced=len(self._open_orders),
                    missing_locally=list(missing_locally),
                    ghost_locally=list(ghost_locally),
                    timestamp=datetime.now(timezone.utc),
                )
            except Exception as exc:
                logger.error("[reconcile] FAILED: %s", exc, exc_info=True)
                return ReconciliationResult(
                    success=False,
                    error=str(exc),
                    timestamp=datetime.now(timezone.utc),
                )

    # -------------------------------------------------------------- account

    async def get_account_info(self) -> AccountInfo:
        """Fetch full account snapshot. Spot-only safe."""
        # --- Spot ---
        try:
            spot = await self._client.get_spot_account()
        except Exception as exc:
            logger.error("get_account_info: spot fetch failed: %s", exc)
            spot = {}

        spot_assets = [
            AssetBalance(
                asset=a["asset"],
                free=float(a["free"]),
                locked=float(a["locked"]),
                total=float(a["free"]) + float(a["locked"]),
                usdt_valuation=self._price_cache.usdt_value(
                    a["asset"], float(a["free"]) + float(a["locked"])
                ),
            )
            for a in spot.get("balances", [])
            if float(a["free"]) + float(a["locked"]) > 1e-9
        ]

        total_spot_usdt = sum(a.usdt_valuation for a in spot_assets)

        # --- Futures (optional — spot-only accounts nu au futures) ---
        futures_assets: List[FuturesAsset] = []
        futs_data: dict = {}
        if self._mode == "futures":
            try:
                futs_data = await self._client.get_futures_account()
                futures_assets = [
                    FuturesAsset(
                        asset=a["asset"],
                        wallet_balance=float(a["walletBalance"]),
                        unrealized_profit=float(a.get("unrealizedProfit", 0)),
                        margin_balance=float(a.get("marginBalance", a["walletBalance"])),
                        maint_margin=float(a.get("maintMargin", 0)),
                        initial_margin=float(a.get("initialMargin", 0)),
                        available_balance=float(a.get("availableBalance", a["walletBalance"])),
                        max_withdraw_amount=float(a.get("maxWithdrawAmount", 0)),
                        margin_available=a.get("marginAvailable", True),
                        update_time=int(a.get("updateTime", 0)),
                    )
                    for a in futs_data.get("assets", [])
                    if float(a.get("walletBalance", 0)) > 1e-9
                ]
            except Exception as exc:
                # 🔴 FIX #2: Futures nu e activat — log warning, nu crash
                logger.warning(
                    "get_account_info: futures fetch skipped (spot-only account?): %s", exc
                )

        total_futs_wallet = sum(a.wallet_balance     for a in futures_assets)
        total_unreal      = sum(a.unrealized_profit  for a in futures_assets)
        total_avail_futs  = sum(a.available_balance  for a in futures_assets)

        # Spot available = free USDT
        spot_usdt_free = next(
            (float(a["free"]) for a in spot.get("balances", []) if a["asset"] == "USDT"), 0.0
        )
        total_available = total_avail_futs + spot_usdt_free
        total_equity    = total_spot_usdt + total_futs_wallet + total_unreal

        info = AccountInfo(
            total_equity=total_equity,
            total_wallet_balance=total_spot_usdt + total_futs_wallet,
            total_unrealized_profit=total_unreal,
            total_margin_balance=total_futs_wallet + total_unreal,
            available_balance=total_available,
            total_position_initial_margin=float(futs_data.get("totalPositionInitialMargin", 0)),
            total_open_order_initial_margin=float(futs_data.get("totalOpenOrderInitialMargin", 0)),
            max_withdraw_amount=float(futs_data.get("maxWithdrawAmount", 0)),
            assets=sorted(spot_assets, key=lambda x: -x.usdt_valuation),
            futures_assets=futures_assets,
            can_trade=spot.get("canTrade", True),
            can_withdraw=spot.get("canWithdraw", True),
            can_deposit=spot.get("canDeposit", True),
            update_time=spot.get("updateTime", 0),
            account_type="SPOT" if self._mode == "spot" else "UNIFIED",
            maker_commission=spot.get("makerCommission", 10),
            taker_commission=spot.get("takerCommission", 10),
        )
        self._cached_equity = info.total_equity
        return info

    async def get_balance_summary(self) -> BalanceSummary:
        """Aggregated USDT summary pentru quick-glance panel."""
        try:
            info        = await self.get_account_info()
            spot_val    = sum(a.usdt_valuation    for a in info.assets)
            futs_wal    = sum(a.wallet_balance    for a in info.futures_assets)
            unreal      = sum(a.unrealized_profit for a in info.futures_assets)
            avail       = info.available_balance
            total       = spot_val + futs_wal + unreal
            init_mar    = (
                info.total_position_initial_margin
                + info.total_open_order_initial_margin
            )
            used_pct    = (init_mar / max(total, 1)) * 100 if total > 0 else 0.0

            return BalanceSummary(
                total_usdt_value=total,
                spot_usdt_value=spot_val,
                futures_usdt_value=futs_wal + unreal,
                unrealized_pnl=unreal,
                available_margin=avail,
                used_margin_pct=round(used_pct, 2),
                top_assets=info.assets[:6],
                last_updated=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            logger.error("get_balance_summary failed: %s", exc)
            return BalanceSummary(
                last_updated=datetime.now(timezone.utc).isoformat()
            )

    # --------------------------------------------------------- local state

    def get_positions(self) -> List[Position]:
        return list(self._positions.values())

    def get_open_orders(self) -> List[Order]:
        return list(self._open_orders.values())

    def get_trades(self) -> List[Trade]:
        return list(self._trades)

    def add_position(self, position: Position) -> None:
        self._positions[position.symbol] = position

    def remove_position(self, symbol: str) -> Optional[Position]:
        return self._positions.pop(symbol, None)

    def update_position(self, position: Position) -> None:
        """Actualizeaza o pozitie existenta (e.g. dupa partial close)."""
        self._positions[position.symbol] = position

    def add_trade(self, trade: Trade) -> None:
        self._trades.append(trade)

    def get_equity(self) -> float:
        return self._cached_equity

    # ---------------------------------------------------------- analytics

    def get_risk_metrics(self) -> RiskMetrics:
        """Calculeaza metrici de performanta din trades inchise."""
        closed = [t for t in self._trades if t.pnl is not None]
        if not closed:
            return RiskMetrics()

        wins   = [t for t in closed if (t.pnl or 0) > 0]
        losses = [t for t in closed if (t.pnl or 0) <= 0]
        total  = len(closed)

        win_rate     = len(wins) / total if total else 0.0
        gross_profit = sum(t.pnl for t in wins   if t.pnl)  # type: ignore
        gross_loss   = abs(sum(t.pnl for t in losses if t.pnl))  # type: ignore
        profit_factor = gross_profit / gross_loss if gross_loss else float("inf")

        pnls    = [t.pnl for t in closed if t.pnl is not None]
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
        if len(pnls) > 1:
            variance = sum((p - avg_pnl) ** 2 for p in pnls) / len(pnls)
            std      = variance ** 0.5
            sharpe   = avg_pnl / std if std > 0 else 0.0
        else:
            sharpe = 0.0

        expectancy = (
            win_rate * (gross_profit / len(wins)   if wins   else 0)
        ) - (
            (1 - win_rate) * (gross_loss / len(losses) if losses else 0)
        )

        # 🟠 FIX #5: gross_profit/gross_loss sunt campuri in RiskMetrics
        return RiskMetrics(
            win_rate=round(win_rate, 4),
            profit_factor=round(profit_factor, 4),
            sharpe_ratio=round(sharpe, 4),
            expectancy=round(expectancy, 4),
            total_trades=total,
            winning_trades=len(wins),
            losing_trades=len(losses),
            gross_profit=round(gross_profit, 4),
            gross_loss=round(gross_loss, 4),
        )

    # ------------------------------------------------------- private helpers

    async def _fetch_raw_equity(self) -> float:
        """
        🔴 FIX #2: Calculeaza equity USDT pentru spot-only accounts.
        Nu mai depinde de Futures API — suma tuturor asset-urilor spot
        convertite in USDT via price_cache cu fallback 0.
        """
        try:
            if self._mode == "futures":
                futs = await self._client.get_futures_account()
                return float(futs.get("totalWalletBalance", 0))

            # SPOT: suma tuturor balante convertite in USDT
            spot  = await self._client.get_spot_account()
            total = 0.0
            for a in spot.get("balances", []):
                qty = float(a["free"]) + float(a["locked"])
                if qty < 1e-9:
                    continue
                if a["asset"] == "USDT":
                    total += qty
                else:
                    # usdt_value returneaza 0.0 daca pretul nu e in cache
                    total += self._price_cache.usdt_value(a["asset"], qty)
            return total
        except Exception as exc:
            logger.warning("_fetch_raw_equity failed, using cached: %s", exc)
            return self._cached_equity
