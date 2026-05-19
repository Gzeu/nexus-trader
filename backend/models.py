"""
models.py – All Pydantic v2 domain models for the trading system.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, computed_field


# ─── Enumerations ────────────────────────────────────────────────────────────────────────

class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE = "CLOSE"
    REVERSE = "REVERSE"


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
    PENDING_CANCEL = "PENDING_CANCEL"
    DRY_RUN = "DRY_RUN"


class MarketMode(str, Enum):
    SPOT = "spot"
    FUTURES = "futures"


class RiskVeto(str, Enum):
    OK = "OK"
    PAUSED = "PAUSED"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"
    MAX_DAILY_LOSS = "MAX_DAILY_LOSS"
    MAX_POSITIONS = "MAX_POSITIONS"
    ONE_PER_SYMBOL = "ONE_PER_SYMBOL"
    COOLDOWN = "COOLDOWN"
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    LOW_RR = "LOW_RR"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    HIGH_SPREAD = "HIGH_SPREAD"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    NOT_RECONCILED = "NOT_RECONCILED"


class ExitReason(str, Enum):
    TP1 = "TP1"
    TP2 = "TP2"
    TRAILING_STOP = "TRAILING_STOP"
    STOP_LOSS = "STOP_LOSS"
    SIGNAL_REVERSE = "SIGNAL_REVERSE"
    TIME_EXIT = "TIME_EXIT"
    INACTIVITY = "INACTIVITY"
    MANUAL = "MANUAL"
    EMERGENCY = "EMERGENCY"


# ─── Core Domain Models ─────────────────────────────────────────────────────────────────

class StrategySignal(BaseModel):
    """Signal emitted by any strategy. All fields required except optionals."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    entry_type: str = Field(pattern="^(market|limit)$")
    entry_price: Optional[float] = None
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    trailing_stop: Optional[float] = None
    timeframe: str
    reason: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Used for anti-duplicate detection (ISO candle open time)
    candle_open_time: Optional[str] = None

    @computed_field  # type: ignore[misc]
    @property
    def rr_ratio(self) -> Optional[float]:
        if self.entry_price and self.stop_loss and self.take_profit_1:
            risk = abs(self.entry_price - self.stop_loss)
            reward = abs(self.take_profit_1 - self.entry_price)
            return round(reward / risk, 3) if risk > 0 else None
        return None


class Order(BaseModel):
    """Represents one exchange order (real or dry-run)."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_order_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    exchange_order_id: Optional[str] = None
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.NEW
    filled_qty: float = 0.0
    avg_fill_price: Optional[float] = None
    commission: float = 0.0
    commission_asset: str = "USDT"
    is_dry_run: bool = False
    reject_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    signal_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Position(BaseModel):
    """Represents an open position."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    current_price: float = 0.0
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    trailing_stop: Optional[float] = None
    tp1_hit: bool = False
    tp2_hit: bool = False
    breakeven_set: bool = False
    realized_pnl: float = 0.0
    commission_paid: float = 0.0
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_progress_at: datetime = Field(default_factory=datetime.utcnow)
    signal_id: Optional[str] = None
    is_dry_run: bool = False
    market_mode: MarketMode = MarketMode.SPOT
    leverage: int = 1
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[misc]
    @property
    def unrealized_pnl(self) -> float:
        if self.current_price <= 0 or self.entry_price <= 0:
            return 0.0
        direction = 1 if self.side == OrderSide.BUY else -1
        return round(direction * (self.current_price - self.entry_price) * self.quantity * self.leverage, 6)

    @computed_field  # type: ignore[misc]
    @property
    def total_pnl(self) -> float:
        return round(self.realized_pnl + self.unrealized_pnl - self.commission_paid, 6)


class Trade(BaseModel):
    """A completed trade (closed position record)."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    side: OrderSide
    entry_price: float
    exit_price: float
    quantity: float
    realized_pnl: float
    commission_paid: float
    exit_reason: ExitReason
    r_multiple: Optional[float] = None
    opened_at: datetime
    closed_at: datetime = Field(default_factory=datetime.utcnow)
    signal_id: Optional[str] = None
    duration_seconds: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AccountInfo(BaseModel):
    """Exchange account snapshot."""
    total_equity: float
    available_balance: float
    used_margin: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl_today: float = 0.0
    balances: Dict[str, float] = Field(default_factory=dict)
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class RiskMetrics(BaseModel):
    """Risk and performance analytics."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    r_multiples: List[float] = Field(default_factory=list)
    equity_curve: List[float] = Field(default_factory=list)
    is_paused: bool = False
    pause_reason: Optional[str] = None


class ReconciliationResult(BaseModel):
    """Result of a position/order reconciliation pass."""
    success: bool
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    positions_synced: int = 0
    orders_synced: int = 0
    drifts_detected: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    duration_ms: float = 0.0


class WSEvent(BaseModel):
    """WebSocket event envelope sent to TradingView frontend."""
    event: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ─── API Request/Response ──────────────────────────────────────────────────────────────

class PlaceOrderRequest(BaseModel):
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    signal_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    is_reconciled: bool
    dry_run: bool
    testnet: bool
    market_mode: str
    open_positions: int
    is_paused: bool
    timestamp: datetime = Field(default_factory=datetime.utcnow)
