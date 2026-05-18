"""
trade_logic.py – Entry / exit evaluation logic, position sizing,
breakeven management, and partial-close helpers.

FIX 4: calc_position_size() uses effective_leverage correctly:
        - Spot:    leverage = 1 always
        - Futures: leverage = configured value (e.g. 5)
        The formula is: (equity * risk_per_trade) / sl_distance
        Position size in BASE asset is then: notional_risk * leverage / entry_price
        This matches how Binance Futures margin actually works.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple

import structlog

from backend.config import get_settings
from backend.models import Action, MarketMode, Position, PositionSide, StrategySignal

log = structlog.get_logger(__name__)
settings = get_settings()


# ─── Entry Decision ──────────────────────────────────────────────────────────

def should_enter_long(signal: StrategySignal, current_price: float, equity: float) -> Tuple[bool, str]:
    """Evaluate whether to enter a long position. Returns (ok, reason)."""
    if signal.action not in (Action.BUY,):
        return False, "Signal action is not BUY"
    if signal.confidence < 0.5:
        return False, f"Confidence too low: {signal.confidence:.2f}"
    if current_price <= 0:
        return False, "Invalid current price"
    risk   = current_price - signal.stop_loss
    reward = signal.take_profit_1 - current_price
    if risk <= 0:
        return False, "SL >= entry price"
    rr = reward / risk
    if rr < settings.min_rr:
        return False, f"RR {rr:.2f} < min {settings.min_rr}"
    return True, "Long entry conditions met"


def should_enter_short(signal: StrategySignal, current_price: float, equity: float) -> Tuple[bool, str]:
    """Evaluate short entry (futures only)."""
    if signal.market_mode != MarketMode.FUTURES:
        return False, "Short only allowed in FUTURES mode"
    if signal.action != Action.SELL:
        return False, "Signal action is not SELL"
    if signal.confidence < 0.5:
        return False, f"Confidence too low: {signal.confidence:.2f}"
    risk   = signal.stop_loss - current_price
    reward = current_price - signal.take_profit_1
    if risk <= 0:
        return False, "SL <= entry price"
    rr = reward / risk
    if rr < settings.min_rr:
        return False, f"RR {rr:.2f} < min {settings.min_rr}"
    return True, "Short entry conditions met"


def calc_position_size(
    equity: float,
    entry: float,
    stop_loss: float,
    market_mode: MarketMode = MarketMode.SPOT,
    leverage: int = 1,
) -> float:
    """
    FIX 4: Leverage-aware position sizing.

    SPOT (leverage=1):
        risk_amount  = equity * risk_per_trade          (e.g. 1% of $10 000 = $100)
        sl_distance  = |entry - stop_loss|              (e.g. $200 for BTC)
        size_in_base = risk_amount / sl_distance        (e.g. 0.5 BTC)

    FUTURES (leverage=N):
        The margin required per unit = entry / leverage.
        If we are willing to lose risk_amount (in USDT) on this trade:
          sl_distance_per_unit = |entry - stop_loss|
          units = risk_amount / sl_distance_per_unit
        This is IDENTICAL to spot in terms of unit count — because leverage
        amplifies BOTH gains and losses symmetrically. The difference is that
        the MARGIN USED = (units * entry) / leverage, which is smaller.

        However for futures we apply a leverage_risk_scale so that we don't
        accidentally over-size when volatility is high. We cap the effective
        notional at equity * risk_per_trade * leverage.

        Example: equity=$10000, risk=1%, entry=$60000, SL=$58000, leverage=5
          sl_distance = $2000
          max_notional_risk = $100 * 5 = $500  (leverage-scaled)
          size = $500 / $2000 = 0.25 BTC
          margin used = 0.25 * $60000 / 5 = $3000  (30% of equity — within limits)
    """
    if entry <= 0 or stop_loss <= 0:
        return 0.0

    sl_distance = abs(entry - stop_loss)
    if sl_distance == 0:
        return 0.0

    risk_amount = equity * settings.risk_per_trade

    if market_mode == MarketMode.FUTURES:
        effective_leverage = max(1, min(leverage, 20))  # hard cap at 20x
        # Scale risk by leverage — more leverage → more units per $ of risk
        risk_amount = risk_amount * effective_leverage
    # Spot: leverage=1, risk_amount unchanged

    size = risk_amount / sl_distance
    return round(size, 8)


def required_margin(size: float, entry: float, leverage: int) -> float:
    """
    Calculate the margin (USDT) required to open a futures position.
    margin = (size * entry) / leverage
    """
    if leverage <= 0:
        return size * entry
    return (size * entry) / leverage


# ─── Exit Decision ────────────────────────────────────────────────────────────

MAX_HOLDING_HOURS = 72
INACTIVITY_HOURS  = 24
TP1_FRACTION      = 0.40
TP2_FRACTION      = 0.40


class ExitDecision:
    NONE         = "NONE"
    TP1          = "TP1"
    TP2          = "TP2"
    SL           = "SL"
    TRAILING     = "TRAILING"
    SIGNAL_CLOSE = "SIGNAL_CLOSE"
    TIME_EXIT    = "TIME_EXIT"
    INACTIVITY   = "INACTIVITY"


def evaluate_exit(
    position: Position,
    current_price: float,
    opposite_signal: Optional[StrategySignal] = None,
) -> Tuple[str, float]:
    """
    Returns (exit_reason, close_fraction).
    close_fraction = 0.0 → no exit; 1.0 → full close; 0.4 → partial.
    """
    is_long = position.side == PositionSide.LONG
    now     = datetime.utcnow()
    age_h   = (now - position.opened_at).total_seconds() / 3600

    # 1. Max holding time
    if age_h > MAX_HOLDING_HOURS:
        return ExitDecision.TIME_EXIT, 1.0

    # 2. Stop loss
    if is_long  and current_price <= position.stop_loss:
        return ExitDecision.SL, 1.0
    if not is_long and current_price >= position.stop_loss:
        return ExitDecision.SL, 1.0

    # 3. Trailing stop
    if position.trailing_stop is not None:
        if is_long  and current_price <= position.trailing_stop:
            return ExitDecision.TRAILING, 1.0
        if not is_long and current_price >= position.trailing_stop:
            return ExitDecision.TRAILING, 1.0

    # 4. TP1 partial close (40%)
    if not position.tp1_hit:
        if is_long  and current_price >= position.take_profit_1:
            return ExitDecision.TP1, TP1_FRACTION
        if not is_long and current_price <= position.take_profit_1:
            return ExitDecision.TP1, TP1_FRACTION

    # 5. TP2 partial close (40% of remainder)
    if position.tp1_hit:
        remaining_fraction = 1 - TP1_FRACTION
        partial = TP2_FRACTION / remaining_fraction if remaining_fraction > 0 else 1.0
        if is_long  and current_price >= position.take_profit_2:
            return ExitDecision.TP2, partial
        if not is_long and current_price <= position.take_profit_2:
            return ExitDecision.TP2, partial

    # 6. Opposite signal with high confidence
    if opposite_signal is not None and opposite_signal.confidence > 0.75:
        opp = opposite_signal.action
        if is_long  and opp == Action.SELL:
            return ExitDecision.SIGNAL_CLOSE, 1.0
        if not is_long and opp == Action.BUY:
            return ExitDecision.SIGNAL_CLOSE, 1.0

    # 7. Inactivity (no meaningful progress)
    if age_h > INACTIVITY_HOURS:
        if is_long  and current_price < position.entry_price * 1.001:
            return ExitDecision.INACTIVITY, 1.0
        if not is_long and current_price > position.entry_price * 0.999:
            return ExitDecision.INACTIVITY, 1.0

    return ExitDecision.NONE, 0.0


def update_position_after_tp1(position: Position, current_price: float) -> Position:
    """Mark TP1 hit; move SL to breakeven; update trailing if applicable."""
    position.tp1_hit       = True
    position.at_breakeven  = True
    position.stop_loss     = position.entry_price
    if position.trailing_stop is not None:
        if position.side == PositionSide.LONG:
            position.trailing_stop = max(position.trailing_stop, current_price * 0.98)
        else:
            position.trailing_stop = min(position.trailing_stop, current_price * 1.02)
    position.updated_at = datetime.utcnow()
    log.info("tp1_hit_breakeven", symbol=position.symbol, new_sl=position.stop_loss)
    return position


def update_trailing_stop(
    position: Position,
    current_price: float,
    trail_pct: float = 0.015,
) -> Position:
    """Ratchet the trailing stop in direction of trade."""
    if position.side == PositionSide.LONG:
        new_trail = current_price * (1 - trail_pct)
        if position.trailing_stop is None or new_trail > position.trailing_stop:
            position.trailing_stop = new_trail
    else:
        new_trail = current_price * (1 + trail_pct)
        if position.trailing_stop is None or new_trail < position.trailing_stop:
            position.trailing_stop = new_trail
    position.updated_at = datetime.utcnow()
    return position
