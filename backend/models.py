"""
models.py – All Pydantic v2 domain models for the trading system.

Merged from models_extra.py:
- AssetBalance      (spot balance per asset with USDT valuation)
- FuturesAsset      (futures wallet per asset, extended fields)
- BalanceSummary    (aggregated USDT dashboard summary)
- AccountInfo       (unified Spot + Futures snapshot)

Backward-compat:
- AccountInfo.unrealized_pnl is an alias for total_unrealized_profit
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, computed_field, model_validator


# ── Enumerations ──────────────────────────────────────────────────────────────

class MarketMode(str, Enum):
    SPOT    = "SPOT"
    FUTURES = "FUTURES"


class Action(str, Enum):
    BUY     = "BUY"
    SELL    = "SELL"
    HOLD    = "HOLD"
    CLOSE   = "CLOSE"
    REVERSE = "REVERSE"


class OrderStatus(str, Enum):
    NEW              = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED           = "FILLED"
    CANCELED         = "CANCELED"
    REJECTED         = "REJECTED"
    EXPIRED          = "EXPIRED"
    PENDING          = "PENDING"
    DRY_RUN          = "DRY_RUN"


class OrderType(str, Enum):
    MARKET        = "MARKET"
    LIMIT         = "LIMIT"
    STOP_MARKET   = "STOP_MARKET"
    TAKE_PROFIT   = "TAKE_PROFIT"
    OCO           = "OCO"
    BRACKET       = "BRACKET"


class OrderSide(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


class PositionSide(str, Enum):
    LONG  = "LONG"
    SHORT = "SHORT"


class RiskVeto(str, Enum):
    ALLOWED                  = "ALLOWED"
    PAUSED                   = "PAUSED"
    MAX_DRAWDOWN             = "MAX_DRAWDOWN"
    DAILY_LOSS               = "DAILY_LOSS"
    MAX_POSITIONS            = "MAX_POSITIONS"
    DUPLICATE_SYMBOL         = "DUPLICATE_SYMBOL"
    COOLDOWN                 = "COOLDOWN"
    CONSECUTIVE_LOSSES       = "CONSECUTIVE_LOSSES"
    INSUFFICIENT_RR          = "INSUFFICIENT_RR"
    NOT_RECONCILED           = "NOT_RECONCILED"
    VOLATILITY_FILTER        = "VOLATILITY_FILTER"
    SPREAD_FILTER            = "SPREAD_FILTER"


class WSEventType(str, Enum):
    SIGNAL_CREATED          = "signal_created"
    SIGNAL_REJECTED         = "signal_rejected"
    ORDER_PLACED            = "order_placed"
    ORDER_FILLED            = "order_filled"
    ORDER_CANCELED          = "order_canceled"
    POSITION_OPENED         = "position_opened"
    POSITION_CLOSED         = "position_closed"
    TP_HIT                  = "tp_hit"
    SL_HIT                  = "sl_hit"
    RISK_EVENT              = "risk_event"
    RECONCILE_COMPLETE      = "reconcile_complete"
    EMERGENCY_STOP          = "emergency_stop"
    HEALTH_UPDATE           = "health_update"


# ── Strategy Signal ───────────────────────────────────────────────────────────

class StrategySignal(BaseModel):
    """Output contract for every strategy — BaseStrategy subclasses must return this."""
    symbol:          str
    action:          Action
    confidence:      float                         = Field(ge=0.0, le=1.0)
    entry_type:      str                           = "market"
    entry_price:     Optional[float]               = None
    stop_loss:       float
    take_profit_1:   float
    take_profit_2:   float
    trailing_stop:   Optional[float]               = None
    timeframe:       str                           = "1h"
    reason:          str                           = ""
    metadata:        Dict[str, Any]                = Field(default_factory=dict)
    # Anti-duplicate: block same action on same candle
    candle_open_time: Optional[datetime]           = None
    created_at:      datetime                      = Field(default_factory=datetime.utcnow)
    strategy_name:   str                           = ""
    market_mode:     MarketMode                    = MarketMode.SPOT


# ── Order ─────────────────────────────────────────────────────────────────────

class Order(BaseModel):
    """Represents a single order (pending or executed)."""
    id:              str                           = ""
    client_order_id: str                           = ""
    symbol:          str
    side:            OrderSide
    type:            OrderType                     = OrderType.MARKET
    status:          OrderStatus                   = OrderStatus.PENDING
    quantity:        float
    filled_quantity: float                         = 0.0
    price:           Optional[float]               = None
    stop_price:      Optional[float]               = None
    avg_fill_price:  Optional[float]               = None
    commission:      float                         = 0.0
    is_dry_run:      bool                          = False
    market_mode:     MarketMode                    = MarketMode.SPOT
    created_at:      datetime                      = Field(default_factory=datetime.utcnow)
    updated_at:      datetime                      = Field(default_factory=datetime.utcnow)
    raw_response:    Optional[Dict[str, Any]]      = None


# ── Position ──────────────────────────────────────────────────────────────────

class Position(BaseModel):
    """Open trading position with live PnL properties."""
    symbol:          str
    side:            PositionSide                  = PositionSide.LONG
    entry_price:     float
    current_price:   float                         = 0.0
    quantity:        float
    stop_loss:       float
    take_profit_1:   float
    take_profit_2:   float
    trailing_stop:   Optional[float]               = None
    breakeven_moved: bool                          = False
    tp1_hit:         bool                          = False
    market_mode:     MarketMode                    = MarketMode.SPOT
    leverage:        int                           = 1
    opened_at:       datetime                      = Field(default_factory=datetime.utcnow)
    updated_at:      datetime                      = Field(default_factory=datetime.utcnow)

    @property
    def unrealized_pnl(self) -> float:
        if not self.current_price:
            return 0.0
        if self.side == PositionSide.LONG:
            return (self.current_price - self.entry_price) * self.quantity
        return (self.entry_price - self.current_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        if self.side == PositionSide.LONG:
            return (self.current_price - self.entry_price) / self.entry_price
        return (self.entry_price - self.current_price) / self.entry_price


# ── Trade (closed) ────────────────────────────────────────────────────────────

class Trade(BaseModel):
    """Completed (closed) trade — persisted to journal."""
    id:              str                           = ""
    symbol:          str
    side:            OrderSide
    entry_price:     float
    exit_price:      float
    quantity:        float
    stop_loss:       float                         = 0.0
    take_profit_1:   float                         = 0.0
    realized_pnl:    float                         = 0.0
    commission:      float                         = 0.0
    exit_reason:     str                           = ""
    market_mode:     MarketMode                    = MarketMode.SPOT
    strategy_name:   str                           = ""
    opened_at:       Optional[datetime]            = None
    closed_at:       datetime                      = Field(default_factory=datetime.utcnow)
    is_dry_run:      bool                          = False


# ── Risk Metrics ──────────────────────────────────────────────────────────────

class RiskMetrics(BaseModel):
    equity:                float   = 0.0
    peak_equity:           float   = 0.0
    drawdown_pct:          float   = 0.0
    daily_loss_pct:        float   = 0.0
    open_positions:        int     = 0
    consecutive_losses:    int     = 0
    is_paused:             bool    = False
    pause_reason:          str     = ""
    win_rate:              float   = 0.0
    profit_factor:         float   = 0.0
    expectancy:            float   = 0.0
    sharpe:                float   = 0.0
    last_updated:          datetime = Field(default_factory=datetime.utcnow)


# ── Reconciliation ────────────────────────────────────────────────────────────

class ReconciliationResult(BaseModel):
    success:           bool
    equity:            float              = 0.0
    positions_synced:  int                = 0
    drift_detected:    bool               = False
    errors:            List[str]          = Field(default_factory=list)
    timestamp:         datetime           = Field(default_factory=datetime.utcnow)


# ── Balance / Account models (merged from models_extra.py) ────────────────────

class AssetBalance(BaseModel):
    """Spot account balance for a single asset."""
    asset:            str
    free:             float = 0.0
    locked:           float = 0.0
    total:            float = 0.0
    usdt_valuation:   float = 0.0   # approximate USDT equivalent

    @model_validator(mode="after")
    def _compute_total(self) -> "AssetBalance":
        if self.total == 0.0:
            self.total = self.free + self.locked
        return self


class FuturesAsset(BaseModel):
    """Futures wallet snapshot for a single asset (from /fapi/v2/account .assets[])."""
    asset:                str
    wallet_balance:       float = 0.0
    unrealized_profit:    float = 0.0
    margin_balance:       float = 0.0
    maint_margin:         float = 0.0
    initial_margin:       float = 0.0
    available_balance:    float = 0.0
    max_withdraw_amount:  float = 0.0
    margin_available:     bool  = True
    update_time:          int   = 0


class AccountInfo(BaseModel):
    """Unified Spot + Futures account snapshot.

    Backward-compat notes:
    - `unrealized_pnl` is an alias for `total_unrealized_profit` (old callers still work)
    - `balances` dict is populated from spot AssetBalance list for quick lookups
    """
    total_equity:                     float               = 0.0
    total_wallet_balance:             float               = 0.0
    total_unrealized_profit:          float               = 0.0
    total_margin_balance:             float               = 0.0
    available_balance:                float               = 0.0
    total_position_initial_margin:    float               = 0.0
    total_open_order_initial_margin:  float               = 0.0
    max_withdraw_amount:              float               = 0.0

    # Spot
    assets:           List[AssetBalance]  = Field(default_factory=list)
    # Futures
    futures_assets:   List[FuturesAsset]  = Field(default_factory=list)
    # Quick-lookup dict {asset: total_amount}
    balances:         Dict[str, float]    = Field(default_factory=dict)

    # Permissions
    can_trade:        bool  = True
    can_withdraw:     bool  = True
    can_deposit:      bool  = True
    update_time:      int   = 0
    account_type:     str   = "UNIFIED"
    maker_commission: int   = 10
    taker_commission: int   = 10

    # Backward-compat alias — old code sets unrealized_pnl directly
    unrealized_pnl: float = 0.0

    @model_validator(mode="after")
    def _sync_alias(self) -> "AccountInfo":
        """Keep unrealized_pnl ↔ total_unrealized_profit in sync."""
        if self.unrealized_pnl and not self.total_unrealized_profit:
            self.total_unrealized_profit = self.unrealized_pnl
        elif self.total_unrealized_profit and not self.unrealized_pnl:
            self.unrealized_pnl = self.total_unrealized_profit
        return self


class BalanceSummary(BaseModel):
    """Aggregated USDT value — used by GET /balance dashboard endpoint."""
    total_usdt_value:     float              = 0.0
    spot_usdt_value:      float              = 0.0
    futures_usdt_value:   float              = 0.0
    unrealized_pnl:       float              = 0.0
    available_margin:     float              = 0.0
    used_margin_pct:      float              = 0.0
    top_assets:           List[AssetBalance] = Field(default_factory=list)
    last_updated:         str               = ""


# ── WebSocket Event ────────────────────────────────────────────────────────────

class WSEvent(BaseModel):
    event:     WSEventType
    payload:   Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime       = Field(default_factory=datetime.utcnow)
