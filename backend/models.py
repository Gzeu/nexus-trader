"""
Pydantic v2 domain models — complete version.
Toate modelele folosite de strategy engine, execution, portfolio si API.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, computed_field


# ─────────────────────────────────────────────────── enums

class Action(str, Enum):
    BUY     = "BUY"
    SELL    = "SELL"
    HOLD    = "HOLD"
    CLOSE   = "CLOSE"
    REVERSE = "REVERSE"


class PositionSide(str, Enum):
    """Used in trade_logic to distinguish long vs short positions."""
    LONG  = "LONG"
    SHORT = "SHORT"
    # convenience aliases matching raw "BUY"/"SELL" side strings
    BUY   = "LONG"
    SELL  = "SHORT"


class OrderSide(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET           = "MARKET"
    LIMIT            = "LIMIT"
    STOP_LOSS        = "STOP_LOSS"
    STOP_LOSS_LIMIT  = "STOP_LOSS_LIMIT"
    TAKE_PROFIT      = "TAKE_PROFIT"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"
    OCO              = "OCO"


class OrderStatus(str, Enum):
    NEW              = "NEW"
    PENDING          = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED           = "FILLED"
    CANCELED         = "CANCELED"
    REJECTED         = "REJECTED"
    EXPIRED          = "EXPIRED"
    DRY_RUN          = "DRY_RUN"   # dry-run simulated fill


class RiskVeto(str, Enum):
    OK                   = "OK"
    PAUSED               = "PAUSED"
    MAX_DRAWDOWN         = "MAX_DRAWDOWN"
    DAILY_LOSS           = "DAILY_LOSS"
    MAX_POSITIONS        = "MAX_POSITIONS"
    DUPLICATE_SYMBOL     = "DUPLICATE_SYMBOL"
    COOLDOWN             = "COOLDOWN"
    CONSECUTIVE_LOSSES   = "CONSECUTIVE_LOSSES"
    MIN_RR               = "MIN_RR"
    HOLD_SIGNAL          = "HOLD_SIGNAL"
    NOT_RECONCILED       = "NOT_RECONCILED"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"


class MarketMode(str, Enum):
    SPOT    = "SPOT"
    FUTURES = "FUTURES"


class WSEventType(str, Enum):
    """WebSocket event type constants used by ExecutionEngine and AutomationEngine."""
    ORDER_FILLED       = "order_filled"
    POSITION_UPDATED   = "position_update_required"
    POSITION_OPENED    = "position_opened"
    POSITION_CLOSED    = "position_closed"
    SIGNAL_CREATED     = "signal_created"
    SIGNAL_REJECTED    = "signal_rejected"
    TP_HIT             = "tp_hit"
    SL_HIT             = "sl_hit"
    RISK_EVENT         = "risk_event"
    RECONCILE_DONE     = "reconcile_done"
    EMERGENCY_STOP     = "emergency_stop"
    DAILY_SUMMARY      = "daily_summary"


# ─────────────────────────────────────────────────── signal

class StrategySignal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    entry_type: str = "market"           # "market" | "limit"
    entry_price: Optional[float] = None
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    trailing_stop: Optional[float] = None
    timeframe: str = "5m"
    reason: str = ""
    market_mode: MarketMode = MarketMode.SPOT
    metadata: Dict[str, Any] = Field(default_factory=dict)
    candle_open_time: Optional[int] = None   # ms timestamp — anti-duplicate key
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────── order request (input)

class OrderRequest(BaseModel):
    """Input model for ExecutionEngine.place_order()."""
    symbol: str
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: Decimal = Decimal("0")
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    market_mode: MarketMode = MarketMode.SPOT
    time_in_force: str = "GTC"
    reduce_only: bool = False
    signal_id: Optional[str] = None
    idempotency_key: uuid.UUID = Field(default_factory=uuid.uuid4)


# ─────────────────────────────────────────────────── order (result)

class Order(BaseModel):
    """Order as returned by ExecutionEngine after placement / simulation."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    exchange_order_id: Optional[str] = None
    idempotency_key: Optional[uuid.UUID] = None
    symbol: str
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: Decimal = Decimal("0")
    filled_quantity: Decimal = Decimal("0")
    avg_fill_price: Optional[Decimal] = None
    price: Optional[Decimal] = None              # limit price
    stop_price: Optional[Decimal] = None
    status: OrderStatus = OrderStatus.NEW
    market_mode: MarketMode = MarketMode.SPOT
    commission: float = 0.0
    signal_id: Optional[str] = None
    filled_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    raw_response: Optional[Dict[str, Any]] = None

    # legacy aliases kept for backward compat
    @property
    def filled_qty(self) -> Decimal:
        return self.filled_quantity

    @property
    def avg_price(self) -> Optional[Decimal]:
        return self.avg_fill_price


# ─────────────────────────────────────────────────── FilledOrder (alias used by execution_engine)

class FilledOrder(Order):
    """
    Alias / subclass of Order representing a confirmed fill.
    ExecutionEngine imports this; it is functionally identical to Order
    but semantically communicates that the order has been executed.
    """
    pass


# ─────────────────────────────────────────────────── position

class Position(BaseModel):
    symbol: str
    side: str                             # "BUY" | "SELL" | "LONG" | "SHORT"
    quantity: float
    entry_price: float
    current_price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    trailing_stop: Optional[float] = None
    tp1_hit: bool = False
    tp2_hit: bool = False
    breakeven_set: bool = False
    at_breakeven: bool = False            # alias used by trade_logic
    strategy: str = ""
    market_mode: MarketMode = MarketMode.SPOT
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None

    @computed_field  # type: ignore[misc]
    @property
    def unrealized_pnl(self) -> float:
        if self.current_price == 0:
            return 0.0
        side_norm = self.side.upper()
        if side_norm in ("BUY", "LONG"):
            return (self.current_price - self.entry_price) * self.quantity
        return (self.entry_price - self.current_price) * self.quantity

    @computed_field  # type: ignore[misc]
    @property
    def unrealized_pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        return (self.unrealized_pnl / (self.entry_price * self.quantity)) * 100

    @property
    def position_side(self) -> PositionSide:
        """Normalize side string → PositionSide enum."""
        if self.side.upper() in ("BUY", "LONG"):
            return PositionSide.LONG
        return PositionSide.SHORT


# ─────────────────────────────────────────────────── trade (closed)

class Trade(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    side: str
    entry_price: float
    exit_price: Optional[float] = None
    quantity: float
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    r_multiple: Optional[float] = None
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    strategy: str = ""
    exit_reason: str = ""
    fees: float = 0.0


# ─────────────────────────────────────────────────── risk / analytics

class RiskMetrics(BaseModel):
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    expectancy: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    max_drawdown_pct: float = 0.0
    consecutive_losses: int = 0


# ─────────────────────────────────────────────────── reconciliation

class ReconciliationResult(BaseModel):
    success: bool
    equity: float = 0.0
    positions_synced: int = 0
    orders_synced: int = 0
    missing_locally: List[str] = Field(default_factory=list)
    ghost_locally: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────── websocket events

class WSEvent(BaseModel):
    event: str                            # use WSEventType values
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────── account

class AccountInfo(BaseModel):
    """Account balance summary used by reconcile() and /balance endpoint."""
    total_equity: float = 0.0
    available_balance: float = 0.0
    unrealized_pnl: float = 0.0
    mode: str = "SPOT"
    asset: str = "USDT"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
