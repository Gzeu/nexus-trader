"""
trade_logic.py – Entry / exit evaluation logic, position sizing,
breakeven management, and partial-close helpers.

FIX 4: calc_position_size() uses effective_leverage correctly:
        - Spot:    leverage = 1 always
        - Futures: leverage = configured value (e.g. 5)
        The formula is: (equity * risk_per_trade) / sl_distance
        Position size in BASE asset is then: notional_risk * leverage / entry_price
        This matches how Binance Futures margin actually works.

CHANGELOG (trade improvements):
  🔴 FIX #5: MAX_HOLDING_HOURS, INACTIVITY_HOURS, TP1_FRACTION, TP2_FRACTION
            mutate din constante hardcodate in valori citite din config.
            Configurabile din .env fara modificare de cod.
  🟡 FIX #6: trail_pct dinamic ATR-based daca position.metadata['atr_value'] e disponibil.
            trail_pct = atr_value / current_price (adaptat la volatilitate reala).
            Fallback la cfg.trail_pct (fix) daca ATR nu e in metadata.
  🟡 FIX #7: signal_close_min_confidence citit din config (anterior 0.75 hardcodat).
            Acum configurabil si verificat sa fie > min_consensus din CompositeStrategy.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple

import structlog

from backend.config import get_settings
from backend.models import Action, MarketMode, Position, PositionSide, StrategySignal

log = structlog.get_logger(__name__)


# ─── Entry Decision ───────────────────────────────────────────────────────────────────

def should_enter_long(signal: StrategySignal, current_price: float, equity: float) -> Tuple[bool, str]:
    """Evaluate whether to enter a long position. Returns (ok, reason)."""
    settings = get_settings()
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
    settings = get_settings()
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
    """
    settings = get_settings()
    if entry <= 0 or stop_loss <= 0:
        return 0.0

    sl_distance = abs(entry - stop_loss)
    if sl_distance == 0:
        return 0.0

    risk_amount = equity * settings.risk_per_trade

    if market_mode == MarketMode.FUTURES:
        effective_leverage = max(1, min(leverage, 20))
        risk_amount = risk_amount * effective_leverage

    size = risk_amount / sl_distance
    return round(size, 8)


def required_margin(size: float, entry: float, leverage: int) -> float:
    if leverage <= 0:
        return size * entry
    return (size * entry) / leverage


# ─── Exit Decision ─────────────────────────────────────────────────────────────────────

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

    🟡 FIX #5: MAX_HOLDING_HOURS, INACTIVITY_HOURS, TP1_FRACTION, TP2_FRACTION
            citite din config — nu mai sunt hardcodate.
    🟡 FIX #7: signal_close_min_confidence citit din config.
    """
    cfg     = get_settings()
    is_long = position.side == PositionSide.LONG
    now     = datetime.utcnow()
    age_h   = (now - position.opened_at).total_seconds() / 3600

    # 1. Max holding time
    if age_h > cfg.max_holding_hours:
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

    # 4. TP1 partial close
    if not position.tp1_hit:
        if is_long  and current_price >= position.take_profit_1:
            return ExitDecision.TP1, cfg.tp1_fraction
        if not is_long and current_price <= position.take_profit_1:
            return ExitDecision.TP1, cfg.tp1_fraction

    # 5. TP2 partial close
    if position.tp1_hit:
        remaining_fraction = 1 - cfg.tp1_fraction
        partial = cfg.tp2_fraction / remaining_fraction if remaining_fraction > 0 else 1.0
        if is_long  and current_price >= position.take_profit_2:
            return ExitDecision.TP2, partial
        if not is_long and current_price <= position.take_profit_2:
            return ExitDecision.TP2, partial

    # 6. Opposite signal with configurable confidence threshold
    # 🟡 FIX #7: signal_close_min_confidence din config (nu mai e 0.75 hardcodat)
    if opposite_signal is not None and opposite_signal.confidence > cfg.signal_close_min_confidence:
        opp = opposite_signal.action
        if is_long  and opp == Action.SELL:
            return ExitDecision.SIGNAL_CLOSE, 1.0
        if not is_long and opp == Action.BUY:
            return ExitDecision.SIGNAL_CLOSE, 1.0

    # 7. Inactivity
    if age_h > cfg.inactivity_hours:
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
    trail_pct: float | None = None,
) -> Position:
    """
    Ratchet the trailing stop in direction of trade.

    🟡 FIX #6: trail_pct dinamic ATR-based daca position.metadata['atr_value'] e disponibil.
    trail_pct = atr_value / current_price — adaptat la volatilitate reala.
    Fallback la cfg.trail_pct (fix) daca ATR nu e prezent sau trail_pct e furnizat explicit.
    """
    if trail_pct is None:
        cfg = get_settings()
        # ATR-based dynamic trailing: mai larg pe piete volatile, mai stramt pe piete line
        atr_value = None
        if hasattr(position, "metadata") and position.metadata:
            atr_value = position.metadata.get("atr_value")
        if atr_value and current_price > 0:
            trail_pct = atr_value / current_price
        else:
            trail_pct = cfg.trail_pct

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
