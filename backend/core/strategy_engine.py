"""
Strategy Engine — BaseStrategy + implementari concrete + CompositeStrategy.

CHANGELOG:
  🟡 FIX #6: CompositeStrategy normalizeaza weight-urile inainte de voting.
     Daca suma weights != 1.0 (e.g. [0.5, 0.3, 0.3] = 1.1),
     confidence final putea depasi 1.0 → clampat dupa normalizare.
  🔴 FIX REVIEW #2: _make_signal() accepta param timeframe (nu mai e hardcodat "1m").
     Fiecare strategie paseza timeframe-ul corect primit din context.
  🟡 FIX REVIEW #5: BreakoutStrategy confidence dinamic bazat pe magnitudinea breakout-ului.
     Anterior: confidence=0.75 fix → distorsiona votul in CompositeStrategy.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from backend.models import Action, StrategySignal

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────── helpers

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _ema(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    k     = 2 / (period + 1)
    ema   = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[-i] - closes[-i - 1]
        (gains if diff > 0 else losses).append(abs(diff))
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 1e-9
    rs       = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.0
    trs = [
        max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        for i in range(1, len(closes))
    ]
    return sum(trs[-period:]) / period


def _bollinger(closes: List[float], period: int = 20, std_mult: float = 2.0
               ) -> Tuple[float, float, float]:
    """Returneaza (upper, middle, lower)."""
    if len(closes) < period:
        c = closes[-1] if closes else 0.0
        return c, c, c
    window = closes[-period:]
    mean   = sum(window) / period
    std    = (sum((x - mean) ** 2 for x in window) / period) ** 0.5
    return mean + std_mult * std, mean, mean - std_mult * std


# ──────────────────────────────────────────────────────────────── Base

class BaseStrategy(ABC):
    """Contract comun pentru toate strategiile."""

    name: str = "base"

    @abstractmethod
    def compute(self, klines: List[List[Any]], timeframe: str = "1m") -> Optional[StrategySignal]:
        """Primeste klines OHLCV si returneaza StrategySignal sau None."""
        ...

    def _make_signal(
        self,
        symbol: str,
        action: Action,
        confidence: float,
        close: float,
        atr: float,
        sl_atr_mult: float = 1.5,
        tp1_rr: float = 1.0,
        tp2_rr: float = 2.0,
        entry_type: str = "market",
        reason: str = "",
        candle_open_time: Optional[str] = None,
        metadata: Optional[Dict] = None,
        timeframe: str = "1m",
    ) -> StrategySignal:
        # 🔴 FIX REVIEW #2: timeframe passat ca param — nu mai e hardcodat "1m"
        sl_dist = atr * sl_atr_mult
        if action in (Action.BUY,):
            stop_loss    = close - sl_dist
            take_profit1 = close + sl_dist * tp1_rr
            take_profit2 = close + sl_dist * tp2_rr
        else:
            stop_loss    = close + sl_dist
            take_profit1 = close - sl_dist * tp1_rr
            take_profit2 = close - sl_dist * tp2_rr

        # Adauga atr_pct in metadata pentru VETO_VOLATILITY din RiskManager
        meta = metadata or {}
        if close > 0 and atr > 0:
            meta["atr_pct"] = round(atr / close, 6)

        return StrategySignal(
            symbol=symbol,
            action=action,
            confidence=round(min(max(confidence, 0.0), 1.0), 4),
            entry_type=entry_type,
            entry_price=close,
            stop_loss=round(stop_loss, 8),
            take_profit_1=round(take_profit1, 8),
            take_profit_2=round(take_profit2, 8),
            timeframe=timeframe,
            reason=reason,
            candle_open_time=candle_open_time,
            metadata=meta,
        )


# ──────────────────────────────────────────────────────────────── Strategies

class TrendFollowingStrategy(BaseStrategy):
    """EMA crossover (fast/slow) + RSI filter + ATR SL/TP."""

    name = "trend_following"

    def __init__(self, symbol: str, fast: int = 9, slow: int = 21) -> None:
        self._symbol = symbol
        self._fast   = fast
        self._slow   = slow

    def compute(self, klines: List[List[Any]], timeframe: str = "1m") -> Optional[StrategySignal]:
        if len(klines) < self._slow + 5:
            return None

        closes  = [_safe_float(k[4]) for k in klines]
        highs   = [_safe_float(k[2]) for k in klines]
        lows    = [_safe_float(k[3]) for k in klines]
        ts      = str(klines[-1][0]) if klines else None

        ema_fast = _ema(closes, self._fast)
        ema_slow = _ema(closes, self._slow)
        if len(ema_fast) < 2 or len(ema_slow) < 2:
            return None

        rsi  = _rsi(closes)
        atr  = _atr(highs, lows, closes)
        prev_cross = ema_fast[-2] - ema_slow[-2]
        curr_cross = ema_fast[-1] - ema_slow[-1]

        if prev_cross < 0 and curr_cross > 0 and rsi < 70:
            conf = min(0.5 + (curr_cross / closes[-1]) * 10, 1.0)
            return self._make_signal(
                self._symbol, Action.BUY, conf, closes[-1], atr,
                reason="EMA bullish crossover", candle_open_time=ts, timeframe=timeframe,
            )
        if prev_cross > 0 and curr_cross < 0 and rsi > 30:
            conf = min(0.5 + abs(curr_cross / closes[-1]) * 10, 1.0)
            return self._make_signal(
                self._symbol, Action.SELL, conf, closes[-1], atr,
                reason="EMA bearish crossover", candle_open_time=ts, timeframe=timeframe,
            )
        return None


class MeanReversionStrategy(BaseStrategy):
    """Bollinger Bands + RSI oversold/overbought."""

    name = "mean_reversion"

    def __init__(self, symbol: str, period: int = 20, rsi_ob: int = 70, rsi_os: int = 30) -> None:
        self._symbol = symbol
        self._period = period
        self._rsi_ob = rsi_ob
        self._rsi_os = rsi_os

    def compute(self, klines: List[List[Any]], timeframe: str = "1m") -> Optional[StrategySignal]:
        if len(klines) < self._period + 5:
            return None

        closes = [_safe_float(k[4]) for k in klines]
        highs  = [_safe_float(k[2]) for k in klines]
        lows   = [_safe_float(k[3]) for k in klines]
        ts     = str(klines[-1][0]) if klines else None

        upper, mid, lower = _bollinger(closes, self._period)
        rsi  = _rsi(closes)
        atr  = _atr(highs, lows, closes)
        close = closes[-1]

        if close < lower and rsi < self._rsi_os:
            dist_pct = (lower - close) / lower if lower else 0
            conf     = min(0.45 + dist_pct * 5, 0.95)
            return self._make_signal(
                self._symbol, Action.BUY, conf, close, atr,
                reason=f"BB lower touch + RSI={rsi:.1f}", candle_open_time=ts, timeframe=timeframe,
            )
        if close > upper and rsi > self._rsi_ob:
            dist_pct = (close - upper) / upper if upper else 0
            conf     = min(0.45 + dist_pct * 5, 0.95)
            return self._make_signal(
                self._symbol, Action.SELL, conf, close, atr,
                reason=f"BB upper touch + RSI={rsi:.1f}", candle_open_time=ts, timeframe=timeframe,
            )
        return None


class BreakoutStrategy(BaseStrategy):
    """N-candle high/low breakout + volume confirmation."""

    name = "breakout"

    def __init__(self, symbol: str, lookback: int = 20, vol_mult: float = 1.5) -> None:
        self._symbol   = symbol
        self._lookback = lookback
        self._vol_mult = vol_mult

    def compute(self, klines: List[List[Any]], timeframe: str = "1m") -> Optional[StrategySignal]:
        if len(klines) < self._lookback + 2:
            return None

        closes  = [_safe_float(k[4]) for k in klines]
        highs   = [_safe_float(k[2]) for k in klines]
        lows    = [_safe_float(k[3]) for k in klines]
        volumes = [_safe_float(k[5]) for k in klines]
        ts      = str(klines[-1][0]) if klines else None

        atr   = _atr(highs, lows, closes)
        close = closes[-1]

        prev_highs  = highs[-(self._lookback + 1):-1]
        prev_lows   = lows[-(self._lookback + 1):-1]
        avg_vol     = sum(volumes[-(self._lookback + 1):-1]) / self._lookback
        curr_vol    = volumes[-1]
        vol_ok      = curr_vol > avg_vol * self._vol_mult

        resistance = max(prev_highs)
        support    = min(prev_lows)

        if close > resistance and vol_ok:
            # 🟡 FIX REVIEW #5: confidence dinamic pe baza magnitudinii breakout-ului
            # Anterior: confidence=0.75 fix → distorsiona votul in CompositeStrategy
            breakout_pct = (close - resistance) / resistance if resistance else 0.0
            conf = min(0.60 + breakout_pct * 20, 0.95)
            return self._make_signal(
                self._symbol, Action.BUY, conf, close, atr,
                reason=f"{self._lookback}c high breakout + vol", candle_open_time=ts, timeframe=timeframe,
            )
        if close < support and vol_ok:
            breakout_pct = (support - close) / support if support else 0.0
            conf = min(0.60 + breakout_pct * 20, 0.95)
            return self._make_signal(
                self._symbol, Action.SELL, conf, close, atr,
                reason=f"{self._lookback}c low breakout + vol", candle_open_time=ts, timeframe=timeframe,
            )
        return None


# ──────────────────────────────────────────────────────────────── Composite

class CompositeStrategy(BaseStrategy):
    """
    Weighted voting intre mai multe strategii cu conflict resolution.

    🟡 FIX #6: Weight-urile sunt normalizate la suma=1.0 inainte de voting.
    Daca weights=[0.5, 0.3, 0.3] (suma=1.1), confidence depasea 1.0.
    Acum: weights normalizate → confidence garantat in [0.0, 1.0].
    """

    name = "composite"

    def __init__(
        self,
        strategies: List[BaseStrategy],
        weights: Optional[Dict[str, float]] = None,
        min_consensus: float = 0.55,
    ) -> None:
        self._strategies    = strategies
        self._min_consensus = min_consensus

        # Build raw weights
        raw: Dict[str, float] = {
            s.name: (weights.get(s.name, 1.0) if weights else 1.0)
            for s in strategies
        }
        # 🟡 FIX #6: Normalizeaza la suma = 1.0
        total_w = sum(raw.values()) or 1.0
        self._weights: Dict[str, float] = {k: v / total_w for k, v in raw.items()}
        logger.debug("CompositeStrategy normalized weights: %s", self._weights)

    def compute(self, klines: List[List[Any]], timeframe: str = "1m") -> Optional[StrategySignal]:
        signals: List[Tuple[StrategySignal, float]] = []

        for strat in self._strategies:
            try:
                sig = strat.compute(klines, timeframe=timeframe)
            except Exception as exc:
                logger.warning("CompositeStrategy: %s failed: %s", strat.name, exc)
                sig = None
            if sig and sig.action != Action.HOLD:
                w = self._weights.get(strat.name, 1.0 / len(self._strategies))
                signals.append((sig, w))

        if not signals:
            return None

        # Tally votes per action
        votes: Dict[str, float] = {}
        for sig, w in signals:
            votes[sig.action] = votes.get(sig.action, 0.0) + w

        best_action = max(votes, key=lambda a: votes[a])
        net_conf    = votes[best_action]   # in [0, 1] datorita normalizarii

        if net_conf < self._min_consensus:
            return None   # HOLD implicit

        concordant = [sig for sig, _ in signals if sig.action == best_action]
        avg_sl  = sum(s.stop_loss     for s in concordant) / len(concordant)
        avg_tp1 = sum(s.take_profit_1 for s in concordant) / len(concordant)
        avg_tp2 = sum(s.take_profit_2 for s in concordant) / len(concordant)
        ref     = concordant[-1]

        return StrategySignal(
            symbol=ref.symbol,
            action=best_action,
            confidence=round(min(net_conf, 1.0), 4),
            entry_type=ref.entry_type,
            entry_price=ref.entry_price,
            stop_loss=round(avg_sl,  8),
            take_profit_1=round(avg_tp1, 8),
            take_profit_2=round(avg_tp2, 8),
            timeframe=timeframe,
            reason=f"Composite({best_action}) conf={net_conf:.2f} from {len(concordant)} strategies",
            candle_open_time=ref.candle_open_time,
            metadata={"votes": votes, "weights": self._weights},
        )
