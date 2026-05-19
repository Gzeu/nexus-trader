"""
Pydantic v2 domain models.
Toate modelele folosite de strategy engine, execution, portfolio si API.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
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


class OrderStatus(str, Enum):
    NEW             = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED          = "FILLED"
    CANCELED        = "CANCELED"
    REJECTED        = "REJECTED"
    EXPIRED         = "EXPIRED"


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
    SPOT    = "spot"
    FUTURES = "futures"


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
    metadata: Dict[str, Any] = Field(default_factory=dict)
    candle_open_time: Optional[int] = None   # ms timestamp — anti-duplicate
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────── order

class Order(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    side: str                             # "BUY" | "SELL"
    type: str = "MARKET"                  # "MARKET" | "LIMIT" | "OCO"
    quantity: float
    price: float = 0.0
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.NEW
    filled_qty: float = 0.0
    avg_price: float = 0.0
    commission: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    idempotency_key: Optional[str] = None


# ─────────────────────────────────────────────────── position

class Position(BaseModel):
    symbol: str
    side: str                             # "BUY" | "SELL"
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
    strategy: str = ""
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @computed_field  # type: ignore[misc]
    @property
    def unrealized_pnl(self) -> float:
        if self.current_price == 0:
            return 0.0
        if self.side == "BUY":
            return (self.current_price - self.entry_price) * self.quantity
        return (self.entry_price - self.current_price) * self.quantity

    @computed_field  # type: ignore[misc]
    @property
    def unrealized_pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        return (self.unrealized_pnl / (self.entry_price * self.quantity)) * 100


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
    event: str                            # "order_filled", "position_opened", etc.
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────── legacy compat
# Pastreaza compatibilitate cu codul vechi care importa AccountInfo din models
class AccountInfo(BaseModel):
    """Legacy AccountInfo — folosit intern de reconcile(). Vezi models_extra.py pentru versiunea full."""
    total_equity: float = 0.0
    available_balance: float = 0.0
    unrealized_pnl: float = 0.0
    mode: str = "spot"
