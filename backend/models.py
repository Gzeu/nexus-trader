"""
Modele Pydantic v2 pentru intregul sistem de trading.

CHANGELOG:
  🟠 FIX #5: RiskMetrics adauga gross_profit si gross_loss (default 0.0).
     Fara aceste campuri, routes.py crapa cu AttributeError la
     rm.gross_profit - rm.gross_loss in /metrics endpoint.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


# ─────────────────────────────────────────────────────────────── Enums

class Action(str, Enum):
    BUY     = "BUY"
    SELL    = "SELL"
    HOLD    = "HOLD"
    CLOSE   = "CLOSE"
    REVERSE = "REVERSE"


class MarketMode(str, Enum):
    SPOT    = "spot"
    FUTURES = "futures"


class OrderStatus(str, Enum):
    NEW              = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED           = "FILLED"
    CANCELED         = "CANCELED"
    REJECTED         = "REJECTED"
    EXPIRED          = "EXPIRED"


class OrderType(str, Enum):
    MARKET    = "MARKET"
    LIMIT     = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    OCO       = "OCO"


class RiskVeto(str, Enum):
    PASS               = "PASS"
    PAUSED             = "PAUSED"
    MAX_DRAWDOWN       = "MAX_DRAWDOWN"
    DAILY_LOSS         = "DAILY_LOSS"
    MAX_POSITIONS      = "MAX_POSITIONS"
    DUPLICATE_SYMBOL   = "DUPLICATE_SYMBOL"
    COOLDOWN           = "COOLDOWN"
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    MIN_RR             = "MIN_RR"
    VOLATILITY_FILTER  = "VOLATILITY_FILTER"
    SPREAD_FILTER      = "SPREAD_FILTER"
    LOW_CONFIDENCE     = "LOW_CONFIDENCE"


# ─────────────────────────────────────────────────────────────── Signal

class StrategySignal(BaseModel):
    """Output standardizat al oricarei strategii."""
    symbol:           str
    action:           Action
    confidence:       float = Field(ge=0.0, le=1.0)
    entry_type:       str   = "market"           # "market" | "limit"
    entry_price:      Optional[float] = None
    stop_loss:        float
    take_profit_1:    float
    take_profit_2:    float
    trailing_stop:    Optional[float] = None
    timeframe:        str   = "1m"
    reason:           str   = ""
    metadata:         Dict[str, Any] = Field(default_factory=dict)
    candle_open_time: Optional[str]  = None      # pentru anti-dupe per candle


# ─────────────────────────────────────────────────────────────── Order

class Order(BaseModel):
    id:              str
    symbol:          str
    side:            str               # "BUY" | "SELL"
    type:            str = "MARKET"
    quantity:        float
    price:           float = 0.0
    stop_price:      Optional[float] = None
    status:          str  = OrderStatus.NEW
    filled_qty:      float = 0.0
    avg_fill_price:  float = 0.0
    commission:      float = 0.0
    created_at:      datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at:      Optional[datetime] = None
    client_order_id: Optional[str] = None
    exchange_order_id: Optional[str] = None


# ─────────────────────────────────────────────────────────────── Position

class Position(BaseModel):
    symbol:         str
    side:           str               # "BUY" | "SELL"
    quantity:       float
    entry_price:    float
    current_price:  float = 0.0
    stop_loss:      Optional[float] = None
    take_profit_1:  Optional[float] = None
    take_profit_2:  Optional[float] = None
    trailing_stop:  Optional[float] = None
    leverage:       int   = 1
    mode:           MarketMode = MarketMode.SPOT
    opened_at:      datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tp1_hit:        bool  = False
    breakeven_set:  bool  = False
    metadata:       Dict[str, Any] = Field(default_factory=dict)

    @property
    def unrealized_pnl(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        mult = 1.0 if self.side == "BUY" else -1.0
        return mult * (self.current_price - self.entry_price) * self.quantity * self.leverage

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        mult = 1.0 if self.side == "BUY" else -1.0
        return mult * (self.current_price - self.entry_price) / self.entry_price * 100


# ─────────────────────────────────────────────────────────────── Trade

class Trade(BaseModel):
    id:            str
    symbol:        str
    side:          str
    quantity:      float
    entry_price:   float
    exit_price:    Optional[float] = None
    pnl:           Optional[float] = None
    pnl_pct:       Optional[float] = None
    commission:    float = 0.0
    opened_at:     datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at:     Optional[datetime] = None
    exit_reason:   Optional[str] = None
    r_multiple:    Optional[float] = None     # PnL / initial_risk
    strategy_name: Optional[str] = None


# ─────────────────────────────────────────────────────────────── RiskMetrics

class RiskMetrics(BaseModel):
    """
    Metrici de performanta calculate din trade history.

    🟠 FIX #5: gross_profit + gross_loss adaugate ca campuri explicite.
    Fara ele, routes.py /metrics crapa cu AttributeError la
    `rm.gross_profit - rm.gross_loss`.
    """
    win_rate:        float = 0.0
    profit_factor:   float = 0.0
    sharpe_ratio:    float = 0.0
    expectancy:      float = 0.0
    total_trades:    int   = 0
    winning_trades:  int   = 0
    losing_trades:   int   = 0
    gross_profit:    float = 0.0   # 🟠 FIX #5
    gross_loss:      float = 0.0   # 🟠 FIX #5
    max_drawdown:    float = 0.0
    avg_win:         float = 0.0
    avg_loss:        float = 0.0
    largest_win:     float = 0.0
    largest_loss:    float = 0.0


# ─────────────────────────────────────────────────────────────── Reconciliation

class ReconciliationResult(BaseModel):
    success:           bool
    equity:            float = 0.0
    positions_synced:  int   = 0
    orders_synced:     int   = 0
    missing_locally:   List[str] = Field(default_factory=list)
    ghost_locally:     List[str] = Field(default_factory=list)
    error:             Optional[str] = None
    timestamp:         datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────────────────── WebSocket Event

class WSEvent(BaseModel):
    event:     str
    payload:   Any   = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
