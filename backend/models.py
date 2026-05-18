"""
models.py – All Pydantic v2 domain models.
Covers signals, orders, positions, trades, risk metrics, account info.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ────────────────────────────────────────────────────────────────

class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE = "CLOSE"
    REVERSE = "REVERSE"


class EntryType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_LIMIT = "STOP_LOSS_LIMIT"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"
    OCO = "OCO"


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    PENDING = "PENDING"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    BOTH = "BOTH"


class MarketMode(str, Enum):
    SPOT = "SPOT"
    FUTURES = "FUTURES"


class RiskVeto(str, Enum):
    OK = "OK"
    MAX_POSITIONS = "MAX_POSITIONS"
    DAILY_LOSS = "DAILY_LOSS"
    DRAWDOWN = "DRAWDOWN"
    COOLDOWN = "COOLDOWN"
    LOW_RR = "LOW_RR"
    VOLATILITY = "VOLATILITY"
    SPREAD = "SPREAD"
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    DRY_RUN = "DRY_RUN"


# ── Core Signal ────────────────────────────────────────────────────────────────

class StrategySignal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    entry_type: EntryType = EntryType.MARKET
    entry_price: Optional[float] = None
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    trailing_stop: Optional[float] = None
    timeframe: str = "5m"
    reason: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    strategy_name: str = ""
    market_mode: MarketMode = MarketMode.SPOT
    candle_open_time: Optional[int] = None


# ── Order ──────────────────────────────────────────────────────────────────

class Order(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_order_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    exchange_order_id: Optional[str] = None
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: float = 0.0
    avg_fill_price: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    market_mode: MarketMode = MarketMode.SPOT
    dry_run: bool = False
    signal_id: Optional[str] = None
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Position ──────────────────────────────────────────────────────────────────

class Position(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    side: PositionSide
    quantity: float
    entry_price: float
    current_price: float = 0.0
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    trailing_stop: Optional[float] = None
    tp1_hit: bool = False
    at_breakeven: bool = False
    market_mode: MarketMode = MarketMode.SPOT
    leverage: int = 1
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    signal_id: Optional[str] = None

    @property
    def unrealized_pnl(self) -> float:
        if self.side == PositionSide.LONG:
            return (self.current_price - self.entry_price) * self.quantity
        return (self.entry_price - self.current_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        return self.unrealized_pnl / (self.entry_price * self.quantity)


# ── Trade (closed) ──────────────────────────────────────────────────────────────────

class Trade(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    side: PositionSide
    quantity: float
    entry_price: float
    exit_price: float
    realized_pnl: float
    pnl_pct: float
    r_multiple: float
    market_mode: MarketMode = MarketMode.SPOT
    opened_at: datetime
    closed_at: datetime = Field(default_factory=datetime.utcnow)
    exit_reason: str = ""
    signal_id: Optional[str] = None


# ── Account / Balances ────────────────────────────────────────────────────────────────

class AssetBalance(BaseModel):
    asset: str
    free: float
    locked: float

    @property
    def total(self) -> float:
        return self.free + self.locked


class AccountInfo(BaseModel):
    balances: List[AssetBalance] = Field(default_factory=list)
    total_equity_usdt: float = 0.0
    available_usdt: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Risk Metrics ──────────────────────────────────────────────────────────────────

class RiskMetrics(BaseModel):
    equity: float
    peak_equity: float
    daily_start_equity: float
    daily_pnl: float
    daily_pnl_pct: float
    current_drawdown: float
    max_drawdown: float
    open_positions: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    consecutive_losses: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    expectancy: float
    last_loss_time: Optional[datetime] = None
    paused: bool = False
    pause_reason: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("win_rate", "profit_factor", "sharpe_ratio", "expectancy", mode="before")
    @classmethod
    def default_nan(cls, v):
        import math
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return 0.0
        return v


# ── Reconciliation ────────────────────────────────────────────────────────────────

class ReconciliationResult(BaseModel):
    success: bool
    drifted_positions: List[str] = Field(default_factory=list)
    missing_orders: List[str] = Field(default_factory=list)
    extra_orders: List[str] = Field(default_factory=list)
    notes: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Websocket Events ────────────────────────────────────────────────────────────────

class WSEvent(BaseModel):
    event: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
