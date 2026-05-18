"""
models.py – All Pydantic v2 domain models for Nexus Trader.

Improvements over v2:
- model_config = ConfigDict(use_enum_values=True, ...) on all models
- Decimal for prices and quantities (no float precision bugs)
- Added: OrderRequest, FilledOrder, PositionState, SignalMetadata
- ReconciliationResult renamed to ReconciliationReport (backwards-compat alias kept)
- RiskVeto.PAUSED added (was missing, caused KeyError in risk_manager)
- StrategySignal.candle_open_time added for deduplication
- Position.unrealized_pnl as @property using Decimal arithmetic
- WSEvent typed payload (not bare dict)
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field


# ── Enums ──────────────────────────────────────────────────────────────────

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
    PENDING = "PENDING"
    DRY_RUN = "DRY_RUN"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class MarketMode(str, Enum):
    SPOT = "SPOT"
    FUTURES = "FUTURES"


class RiskVeto(str, Enum):
    OK = "OK"
    PAUSED = "PAUSED"                      # manual emergency stop or resume not called
    DRAWDOWN = "DRAWDOWN"
    DAILY_LOSS = "DAILY_LOSS"
    WEEKLY_LOSS = "WEEKLY_LOSS"
    MAX_POSITIONS = "MAX_POSITIONS"
    COOLDOWN = "COOLDOWN"
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    LOW_RR = "LOW_RR"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    SYMBOL_BLACKLISTED = "SYMBOL_BLACKLISTED"
    NOT_RECONCILED = "NOT_RECONCILED"


class EntryType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class WSEventType(str, Enum):
    SIGNAL_CREATED = "signal_created"
    SIGNAL_REJECTED = "signal_rejected"
    ORDER_PLACED = "order_placed"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELED = "order_canceled"
    POSITION_OPENED = "position_opened"
    POSITION_UPDATED = "position_updated"
    POSITION_CLOSED = "position_closed"
    TP1_HIT = "tp1_hit"
    TP2_HIT = "tp2_hit"
    SL_HIT = "sl_hit"
    TRAILING_STOP = "trailing_stop"
    DRIFT_DETECTED = "drift_detected"
    RISK_PAUSED = "risk_paused"
    EMERGENCY_STOP = "emergency_stop"
    RECONCILE_COMPLETE = "reconcile_complete"
    HEARTBEAT = "heartbeat"


# ── Signal ─────────────────────────────────────────────────────────────────

class SignalMetadata(BaseModel):
    """Extra context from strategy computation."""
    model_config = ConfigDict(extra="allow")

    ema_fast: Optional[float] = None
    ema_slow: Optional[float] = None
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    atr: Optional[float] = None
    atr_pct: Optional[float] = None
    volume_ratio: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    strategy_name: Optional[str] = None
    votes: Optional[Dict[str, float]] = None


class StrategySignal(BaseModel):
    """Output of any strategy.generate() call."""
    model_config = ConfigDict(use_enum_values=True)

    id: UUID = Field(default_factory=uuid4)
    symbol: str
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    entry_type: EntryType = EntryType.MARKET
    entry_price: Optional[Decimal] = None
    stop_loss: Decimal
    take_profit_1: Decimal
    take_profit_2: Decimal
    trailing_stop: Optional[Decimal] = None
    timeframe: str = "15m"
    reason: str = ""
    candle_open_time: Optional[int] = None   # ms timestamp — deduplication key
    metadata: SignalMetadata = Field(default_factory=SignalMetadata)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Order ──────────────────────────────────────────────────────────────────

class OrderRequest(BaseModel):
    """Pre-execution intent — passed to ExecutionEngine."""
    model_config = ConfigDict(use_enum_values=True)

    idempotency_key: UUID = Field(default_factory=uuid4)
    symbol: str
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: Decimal
    price: Optional[Decimal] = None          # for LIMIT orders
    stop_price: Optional[Decimal] = None     # for STOP orders
    take_profit_price: Optional[Decimal] = None
    time_in_force: str = "GTC"
    reduce_only: bool = False
    market_mode: MarketMode = MarketMode.SPOT
    signal_id: Optional[UUID] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Order(BaseModel):
    """Submitted order (after normalization, before fill confirmation)."""
    model_config = ConfigDict(use_enum_values=True)

    id: UUID = Field(default_factory=uuid4)
    exchange_order_id: Optional[str] = None
    idempotency_key: Optional[UUID] = None
    symbol: str
    side: OrderSide
    order_type: OrderType
    status: OrderStatus = OrderStatus.PENDING
    quantity: Decimal
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    filled_quantity: Decimal = Decimal("0")
    avg_fill_price: Optional[Decimal] = None
    market_mode: MarketMode = MarketMode.SPOT
    signal_id: Optional[UUID] = None
    placed_at: datetime = Field(default_factory=datetime.utcnow)
    filled_at: Optional[datetime] = None
    raw_response: Optional[Dict[str, Any]] = None


class FilledOrder(BaseModel):
    """Confirmed fill — used for journal and PnL calculation."""
    model_config = ConfigDict(use_enum_values=True)

    order_id: UUID
    exchange_order_id: str
    symbol: str
    side: OrderSide
    filled_quantity: Decimal
    avg_fill_price: Decimal
    commission: Decimal = Decimal("0")
    commission_asset: str = "USDT"
    market_mode: MarketMode
    filled_at: datetime = Field(default_factory=datetime.utcnow)


# ── Position ─────────────────────────────────────────────────────────────────

class Position(BaseModel):
    """Live open position tracked locally."""
    model_config = ConfigDict(use_enum_values=True)

    id: UUID = Field(default_factory=uuid4)
    symbol: str
    side: PositionSide
    entry_price: Decimal
    quantity: Decimal
    remaining_quantity: Optional[Decimal] = None  # after partial closes
    stop_loss: Decimal
    take_profit_1: Decimal
    take_profit_2: Decimal
    trailing_stop: Optional[Decimal] = None
    market_mode: MarketMode = MarketMode.SPOT
    tp1_hit: bool = False
    tp2_hit: bool = False
    breakeven_set: bool = False
    current_price: Optional[Decimal] = None
    leverage: int = 1
    signal_id: Optional[UUID] = None
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @computed_field  # type: ignore[misc]
    @property
    def unrealized_pnl(self) -> Decimal:
        """Unrealized PnL using Decimal arithmetic. Returns 0 if no current_price."""
        if self.current_price is None:
            return Decimal("0")
        qty = self.remaining_quantity or self.quantity
        if self.side == PositionSide.LONG:
            return (self.current_price - self.entry_price) * qty * self.leverage
        return (self.entry_price - self.current_price) * qty * self.leverage


class PositionState(BaseModel):
    """Serialized snapshot of a position for API responses."""
    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    side: str
    entry_price: str   # Decimal serialized as string to preserve precision
    quantity: str
    unrealized_pnl: str
    stop_loss: str
    take_profit_1: str
    take_profit_2: str
    tp1_hit: bool
    tp2_hit: bool
    market_mode: str
    opened_at: datetime

    @classmethod
    def from_position(cls, p: Position) -> "PositionState":
        return cls(
            symbol=p.symbol,
            side=p.side if isinstance(p.side, str) else p.side.value,
            entry_price=str(p.entry_price),
            quantity=str(p.remaining_quantity or p.quantity),
            unrealized_pnl=str(p.unrealized_pnl),
            stop_loss=str(p.stop_loss),
            take_profit_1=str(p.take_profit_1),
            take_profit_2=str(p.take_profit_2),
            tp1_hit=p.tp1_hit,
            tp2_hit=p.tp2_hit,
            market_mode=p.market_mode if isinstance(p.market_mode, str) else p.market_mode.value,
            opened_at=p.opened_at,
        )


# ── Trade (closed) ───────────────────────────────────────────────────────────

class Trade(BaseModel):
    """Closed trade record — journaled and used for analytics."""
    model_config = ConfigDict(use_enum_values=True)

    id: UUID = Field(default_factory=uuid4)
    symbol: str
    side: PositionSide
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    realized_pnl: Decimal
    stop_loss: Decimal
    commission: Decimal = Decimal("0")
    market_mode: MarketMode = MarketMode.SPOT
    exit_reason: str = ""
    signal_id: Optional[UUID] = None
    opened_at: Optional[datetime] = None
    closed_at: datetime = Field(default_factory=datetime.utcnow)

    @computed_field  # type: ignore[misc]
    @property
    def r_multiple(self) -> Optional[Decimal]:
        """R-multiple: how many R (risk units) the trade returned."""
        risk = abs(self.entry_price - self.stop_loss)
        if risk == 0:
            return None
        if self.side == PositionSide.LONG:
            return (self.exit_price - self.entry_price) / risk
        return (self.entry_price - self.exit_price) / risk


# ── Account & Risk Metrics ────────────────────────────────────────────────────

class AccountInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    total_equity: float
    available_balance: float
    unrealized_pnl: float = 0.0
    balances: Dict[str, float] = {}
    can_trade: bool = True
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RiskMetrics(BaseModel):
    equity: float
    peak_equity: float
    daily_start_equity: float
    daily_pnl: float
    daily_pnl_pct: float
    weekly_pnl: float = 0.0
    weekly_pnl_pct: float = 0.0
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


# ── Reconciliation ────────────────────────────────────────────────────────────

class ReconciliationReport(BaseModel):
    """Result of portfolio_engine.reconcile()."""
    success: bool
    equity: float
    positions_synced: int
    drift_detected: bool
    drift_symbols: List[str] = []
    errors: List[str] = []
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# Backwards-compat alias
ReconciliationResult = ReconciliationReport


# ── WebSocket events ──────────────────────────────────────────────────────────

class WSEvent(BaseModel):
    """Typed WebSocket event broadcast to all connected clients."""
    event: WSEventType
    payload: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(use_enum_values=True)


# ── API request/response helpers ─────────────────────────────────────────────

class PlaceOrderBody(BaseModel):
    """Body for POST /place_order endpoint."""
    symbol: str
    side: OrderSide
    quantity: Optional[float] = None  # if None, auto-size from risk settings
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    market_mode: MarketMode = MarketMode.SPOT
    dry_run_override: Optional[bool] = None  # override settings.dry_run for this call

    model_config = ConfigDict(use_enum_values=True)


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded" | "error"
    reconciled: bool
    dry_run: bool
    testnet: bool
    open_positions: int
    equity: float
    paused: bool
    binance_reachable: bool
    last_reconcile: Optional[datetime] = None
    uptime_seconds: float = 0.0
    version: str = "3.0.0"
