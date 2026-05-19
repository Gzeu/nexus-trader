"""
Extra Pydantic v2 models — AssetBalance, FuturesAsset, AccountInfo, BalanceSummary.
Importate in portfolio_engine.py si routes.py.
"""
from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, Field


class AssetBalance(BaseModel):
    """Single spot asset balance with USDT valuation."""
    asset: str
    free: float = 0.0
    locked: float = 0.0
    total: float = 0.0
    usdt_valuation: float = 0.0


class FuturesAsset(BaseModel):
    """Single futures asset from /fapi/v2/account."""
    asset: str
    wallet_balance: float = 0.0
    unrealized_profit: float = 0.0
    margin_balance: float = 0.0
    maint_margin: float = 0.0
    initial_margin: float = 0.0
    available_balance: float = 0.0
    max_withdraw_amount: float = 0.0
    margin_available: bool = True
    update_time: int = 0


class AccountInfo(BaseModel):
    """Full unified account snapshot (spot + futures)."""
    total_equity: float = 0.0
    total_wallet_balance: float = 0.0
    total_unrealized_profit: float = 0.0
    total_margin_balance: float = 0.0
    available_balance: float = 0.0
    total_position_initial_margin: float = 0.0
    total_open_order_initial_margin: float = 0.0
    max_withdraw_amount: float = 0.0
    assets: List[AssetBalance] = Field(default_factory=list)
    futures_assets: List[FuturesAsset] = Field(default_factory=list)
    can_trade: bool = True
    can_withdraw: bool = True
    can_deposit: bool = True
    update_time: int = 0
    account_type: str = "UNIFIED"
    maker_commission: int = 10
    taker_commission: int = 10


class BalanceSummary(BaseModel):
    """Aggregated USDT summary for the quick-glance dashboard panel."""
    total_usdt_value: float = 0.0
    spot_usdt_value: float = 0.0
    futures_usdt_value: float = 0.0
    unrealized_pnl: float = 0.0
    available_margin: float = 0.0
    used_margin_pct: float = 0.0
    top_assets: List[AssetBalance] = Field(default_factory=list)
    last_updated: str = ""
