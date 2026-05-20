"""
PortfolioEngine — reconciliere Binance <-> state local, PnL analytics,
get_account_info() si get_balance_summary() integrate complet.

STARTUP GATE: reconcile() trebuie sa returneze succes inainte ca trading-ul
sa fie permis. `is_ready` property blocheaza orice actiune pana atunci.

CHANGELOG:
  🔴 update_position() adaugat — automation_engine.py apela aceasta metoda
     dar nu exista, cauzand AttributeError silentios la fiecare exit partial.
  🟡 peak_equity expus ca property public (folosit de /metrics pentru drawdown).
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
        self._client = client
        self._price_cache = price_cache
        self._mode = mode

        # Stare locala
        self._positions: Dict[str, Position] = {}
        self._open_orders: Dict[str, Order] = {}
        self._trades: List[Trade] = []
        self._cached_equity: float = 0.0
        self._peak_equity: float = 0.0  # 🟡 tracked intern, expus ca property

        self._reconciled = False
        self._reconcile_lock = asyncio.Lock()

    # ---------------------------------------------------------------- gateway

    @property
    def is_ready(self) -> bool:
        """True doar dupa prima reconciliere reusita."""
        return self._reconciled

    @property
    def peak_equity(self) -> float:
        """🟡 Cel mai mare nivel de equity atins — folosit pentru drawdown calc."""
        return self._peak_equity

    # ------------------------------------------------------------- reconcile

    async def reconcile(self) -> ReconciliationResult:
        """
        Sincronizeaza starea locala cu Binance.
        Apelat la startup (blocant cu timeout extern) si periodic.
        """
        async with self._reconcile_lock:
            logger.info("[reconcile] Starting reconciliation (mode=%s)", self._mode)
            try:
                if self._mode == "futures":
                    remote_positions = await self._client.get_positions()
                    remote_orders = await self._client.get_open_orders()
                else:
                    remote_positions = []
                    remote_orders = await self._client.get_open_orders()

                # Detecteaza drift pozitii
                remote_symbols = {
                    p["symbol"]
                    for p in remote_positions
                    if float(p.get("positionAmt", 0)) != 0
                }
                local_symbols = set(self._positions.keys())

                missing_locally = remote_symbols - local_symbols
                ghost_locally = local_symbols - remote_symbols

                if missing_locally:
                    logger.warning(
                        "[reconcile] Positions on exchange but not locally: %s", missing_locally
                    )
                if ghost_locally:
                    logger.warning(
                        "[reconcile] Positions locally but not on exchange: %s", ghost_locally
                    )

                # Sync orders
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

                # Update equity + peak
                equity = await self._fetch_raw_equity()
                self._cached_equity = equity
                if equity > self._peak_equity:
                    self._peak_equity = equity

                self._reconciled = True
                logger.info(
                    "[reconcile] OK — equity=%.2f peak=%.2f positions=%d orders=%d",
                    self._cached_equity,
                    self._peak_equity,
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
        """Fetch full Binance account snapshot (spot + futures)."""
        try:
            spot = await self._client.get_spot_account()
            futs = await self._client.get_futures_account()

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
                for a in futs.get("assets", [])
                if float(a.get("walletBalance", 0)) > 1e-9
            ]

            total_spot    = sum(a.usdt_valuation for a in spot_assets)
            total_futs_w  = sum(a.wallet_balance for a in futures_assets)
            total_unreal  = sum(a.unrealized_profit for a in futures_assets)
            total_avail   = sum(a.available_balance for a in futures_assets)

            info = AccountInfo(
                total_equity=total_spot + total_futs_w + total_unreal,
                total_wallet_balance=total_spot + total_futs_w,
                total_unrealized_profit=total_unreal,
                total_margin_balance=total_futs_w + total_unreal,
                available_balance=total_avail,
                total_position_initial_margin=float(
                    futs.get("totalPositionInitialMargin", 0)
                ),
                total_open_order_initial_margin=float(
                    futs.get("totalOpenOrderInitialMargin", 0)
                ),
                max_withdraw_amount=float(futs.get("maxWithdrawAmount", 0)),
                assets=sorted(spot_assets, key=lambda x: -x.usdt_valuation),
                futures_assets=futures_assets,
                can_trade=spot.get("canTrade", True),
                can_withdraw=spot.get("canWithdraw", True),
                can_deposit=spot.get("canDeposit", True),
                update_time=spot.get("updateTime", 0),
                account_type="UNIFIED",
                maker_commission=spot.get("makerCommission", 10),
                taker_commission=spot.get("takerCommission", 10),
            )

            # Actualizeaza cache + peak dupa fiecare fetch live
            self._cached_equity = info.total_equity
            if info.total_equity > self._peak_equity:
                self._peak_equity = info.total_equity

            return info

        except Exception as exc:
            logger.error("get_account_info failed: %s", exc)
            return AccountInfo(
                total_equity=self._cached_equity,
                total_wallet_balance=self._cached_equity,
            )

    async def get_balance_summary(self) -> BalanceSummary:
        """Aggregated USDT summary pentru quick-glance panel."""
        try:
            info = await self.get_account_info()
            spot_val  = sum(a.usdt_valuation for a in info.assets)
            futs_wal  = sum(a.wallet_balance for a in info.futures_assets)
            unreal    = sum(a.unrealized_profit for a in info.futures_assets)
            avail     = sum(a.available_balance for a in info.futures_assets) + sum(
                a.free for a in info.assets if a.asset == "USDT"
            )
            total     = spot_val + futs_wal + unreal
            init_mar  = (
                info.total_position_initial_margin
                + info.total_open_order_initial_margin
            )
            used_pct  = (init_mar / max(total, 1)) * 100 if total > 0 else 0.0

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

    # ─────────────────────────────────────── local state mutators

    def get_positions(self) -> List[Position]:
        return list(self._positions.values())

    def get_open_orders(self) -> List[Order]:
        return list(self._open_orders.values())

    def get_trades(self) -> List[Trade]:
        return list(self._trades)

    def add_position(self, position: Position) -> None:
        self._positions[position.symbol] = position

    def update_position(self, position: Position) -> None:
        """
        🔴 FIX: Actualizeaza o pozitie existenta in starea locala.

        Metoda lipsea complet — automation_engine.py apela
        self._portfolio.update_position(updated_pos) dupa TP1/trailing
        si primea AttributeError, lasand pozitia in starea veche (SL
        nu se muta la breakeven, trailing stop nu se actualiza).
        """
        self._positions[position.symbol] = position
        logger.debug(
            "[portfolio] position updated: symbol=%s side=%s qty=%.6f entry=%.4f sl=%.4f",
            position.symbol,
            position.side,
            position.quantity,
            position.entry_price,
            getattr(position, "stop_loss", 0),
        )

    def remove_position(self, symbol: str) -> Optional[Position]:
        return self._positions.pop(symbol, None)

    def add_trade(self, trade: Trade) -> None:
        self._trades.append(trade)

    def get_equity(self) -> float:
        """Returneaza equity-ul cached (actualizat la fiecare get_account_info)."""
        return self._cached_equity

    # ─────────────────────────────────────────────────────────── analytics

    def get_risk_metrics(self) -> RiskMetrics:
        """Calculeaza metrici de performanta din trades inchise."""
        closed = [t for t in self._trades if t.pnl is not None]
        if not closed:
            return RiskMetrics()

        wins   = [t for t in closed if (t.pnl or 0) > 0]
        losses = [t for t in closed if (t.pnl or 0) <= 0]
        total  = len(closed)

        win_rate      = len(wins) / total if total else 0.0
        gross_profit  = sum(t.pnl for t in wins if t.pnl)  # type: ignore
        gross_loss    = abs(sum(t.pnl for t in losses if t.pnl))  # type: ignore
        profit_factor = gross_profit / gross_loss if gross_loss else float("inf")

        pnls    = [t.pnl for t in closed if t.pnl is not None]
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
        if len(pnls) > 1:
            variance = sum((p - avg_pnl) ** 2 for p in pnls) / len(pnls)
            std      = variance ** 0.5
            sharpe   = (avg_pnl / std) if std > 0 else 0.0
        else:
            sharpe = 0.0

        expectancy = (
            win_rate * (gross_profit / len(wins) if wins else 0)
        ) - (
            (1 - win_rate) * (gross_loss / len(losses) if losses else 0)
        )

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

    # ─────────────────────────────────────────────────────── private helpers

    async def _fetch_raw_equity(self) -> float:
        """Fetch simplu de equity — fallback la cached daca esueaza."""
        try:
            if self._mode == "futures":
                futs = await self._client.get_futures_account()
                return float(futs.get("totalWalletBalance", 0))
            else:
                spot = await self._client.get_spot_account()
                usdt_bal = next(
                    (a for a in spot.get("balances", []) if a["asset"] == "USDT"),
                    None,
                )
                if usdt_bal:
                    return float(usdt_bal["free"]) + float(usdt_bal["locked"])
                return self._cached_equity
        except Exception:
            return self._cached_equity
