"""
Extensions for PortfolioEngine — paste these methods into the existing class
in backend/core/portfolio_engine.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.models_extra import AccountInfo, AssetBalance, BalanceSummary, FuturesAsset

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Paste into class PortfolioEngine:
# ─────────────────────────────────────────────────────────────────────────────


async def get_account_info(self) -> AccountInfo:
    """Fetch full Binance account snapshot (spot + futures)."""
    try:
        spot = await self.client.get_spot_account()
        futs = await self.client.get_futures_account()

        spot_assets = [
            AssetBalance(
                asset=a["asset"],
                free=float(a["free"]),
                locked=float(a["locked"]),
                total=float(a["free"]) + float(a["locked"]),
                usdt_valuation=_usdt_value(a["asset"], float(a["free"]) + float(a["locked"])),
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

        total_spot = sum(a.usdt_valuation for a in spot_assets)
        total_futs_wallet = sum(a.wallet_balance for a in futures_assets)
        total_unreal = sum(a.unrealized_profit for a in futures_assets)
        total_avail  = sum(a.available_balance  for a in futures_assets)

        return AccountInfo(
            total_equity=total_spot + total_futs_wallet + total_unreal,
            total_wallet_balance=total_spot + total_futs_wallet,
            total_unrealized_profit=total_unreal,
            total_margin_balance=total_futs_wallet + total_unreal,
            available_balance=total_avail,
            total_position_initial_margin=float(futs.get("totalPositionInitialMargin", 0)),
            total_open_order_initial_margin=float(futs.get("totalOpenOrderInitialMargin", 0)),
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
    except Exception as e:
        logger.error("get_account_info failed: %s", e)
        return AccountInfo(
            total_equity=self._cached_equity,
            total_wallet_balance=self._cached_equity,
            total_unrealized_profit=0.0,
            total_margin_balance=0.0,
            available_balance=self._cached_equity,
            total_position_initial_margin=0.0,
            total_open_order_initial_margin=0.0,
            max_withdraw_amount=0.0,
        )


async def get_balance_summary(self) -> BalanceSummary:
    """Aggregated USDT summary for the quick-glance panel."""
    try:
        info = await self.get_account_info()
        spot_val  = sum(a.usdt_valuation for a in info.assets)
        futs_wal  = sum(a.wallet_balance for a in info.futures_assets)
        unreal    = sum(a.unrealized_profit for a in info.futures_assets)
        avail     = sum(a.available_balance for a in info.futures_assets) + sum(
            a.free * 1.0 for a in info.assets if a.asset == "USDT"
        )
        total     = spot_val + futs_wal + unreal
        init_mar  = info.total_position_initial_margin + info.total_open_order_initial_margin
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
    except Exception as e:
        logger.error("get_balance_summary failed: %s", e)
        return BalanceSummary(
            total_usdt_value=0.0, spot_usdt_value=0.0, futures_usdt_value=0.0,
            unrealized_pnl=0.0, available_margin=0.0, used_margin_pct=0.0,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )


def _usdt_value(asset: str, amount: float) -> float:
    """Placeholder — in production use price cache / USDT pairs."""
    if asset in ("USDT", "BUSD"):
        return amount
    # TODO: replace with real-time price from PriceCache
    return 0.0
