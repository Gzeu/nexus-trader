"""
strategy_engine.py – BaseStrategy ABC + TrendFollowing, MeanReversion,
Breakout, and CompositeStrategy implementations.
"""
from __future__ import annotations

import abc
import asyncio
from typing import List, Optional, Sequence

import structlog

from backend.models import Action, EntryType, MarketMode, StrategySignal

log = structlog.get_logger(__name__)


# ── Indicators (lightweight, numpy-free fallbacks) ────────────────────────────

def _ema(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    k = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema


def _sma(prices: List[float], period: int) -> float:
    data = prices[-period:]
    return sum(data) / len(data) if data else 0.0


def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if not trs:
        return 0.0
    data = trs[-period:]
    return sum(data) / len(data)


def _rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas[-period:]]
    losses = [abs(min(d, 0)) for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _bollinger(closes: List[float], period: int = 20, std_mult: float = 2.0):
    """Returns (upper, middle, lower)."""
    data = closes[-period:]
    mid = sum(data) / len(data)
    variance = sum((p - mid) ** 2 for p in data) / len(data)
    std = variance ** 0.5
    return mid + std_mult * std, mid, mid - std_mult * std


# ── OHLCV helper ──────────────────────────────────────────────────────────────

class OHLCV:
    """Thin wrapper around raw kline data."""

    def __init__(self, klines: List[List]):
        self.opens = [float(k[1]) for k in klines]
        self.highs = [float(k[2]) for k in klines]
        self.lows = [float(k[3]) for k in klines]
        self.closes = [float(k[4]) for k in klines]
        self.volumes = [float(k[5]) for k in klines]
        self.times = [int(k[0]) for k in klines]

    @property
    def last_close(self) -> float:
        return self.closes[-1]

    @property
    def last_time(self) -> int:
        return self.times[-1]


# ── Base Strategy ─────────────────────────────────────────────────────────────

class BaseStrategy(abc.ABC):
    """Abstract base. Every strategy must implement `compute`."""

    def __init__(self, symbol: str, timeframe: str = "5m", market_mode: MarketMode = MarketMode.SPOT):
        self.symbol = symbol
        self.timeframe = timeframe
        self.market_mode = market_mode
        self.name = self.__class__.__name__

    @abc.abstractmethod
    async def compute(self, ohlcv: OHLCV) -> Optional[StrategySignal]:
        """Return a StrategySignal or None if no trade opportunity."""
        ...

    def _make_signal(
        self,
        action: Action,
        entry_price: float,
        stop_loss: float,
        take_profit_1: float,
        take_profit_2: float,
        confidence: float,
        reason: str,
        entry_type: EntryType = EntryType.MARKET,
        trailing_stop: Optional[float] = None,
        metadata: Optional[dict] = None,
        candle_open_time: Optional[int] = None,
    ) -> StrategySignal:
        return StrategySignal(
            symbol=self.symbol,
            action=action,
            confidence=confidence,
            entry_type=entry_type,
            entry_price=entry_price if entry_type == EntryType.LIMIT else None,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            trailing_stop=trailing_stop,
            timeframe=self.timeframe,
            reason=reason,
            metadata=metadata or {},
            strategy_name=self.name,
            market_mode=self.market_mode,
            candle_open_time=candle_open_time,
        )


# ── Trend Following ───────────────────────────────────────────────────────────

class TrendFollowingStrategy(BaseStrategy):
    """
    EMA crossover (fast/slow) + RSI filter + ATR-based SL/TP.
    BUY when fast EMA crosses above slow EMA and RSI > 50.
    SELL (futures) when fast crosses below slow and RSI < 50.
    """

    def __init__(
        self,
        symbol: str,
        timeframe: str = "5m",
        market_mode: MarketMode = MarketMode.SPOT,
        fast: int = 9,
        slow: int = 21,
        atr_sl_mult: float = 1.5,
        atr_tp1_mult: float = 1.5,
        atr_tp2_mult: float = 3.0,
    ):
        super().__init__(symbol, timeframe, market_mode)
        self.fast = fast
        self.slow = slow
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp1_mult = atr_tp1_mult
        self.atr_tp2_mult = atr_tp2_mult

    async def compute(self, ohlcv: OHLCV) -> Optional[StrategySignal]:
        closes = ohlcv.closes
        if len(closes) < self.slow + 5:
            return None

        fast_now = _ema(closes, self.fast)
        slow_now = _ema(closes, self.slow)
        fast_prev = _ema(closes[:-1], self.fast)
        slow_prev = _ema(closes[:-1], self.slow)
        rsi = _rsi(closes)
        atr = _atr(ohlcv.highs, ohlcv.lows, closes)
        price = ohlcv.last_close

        bullish_cross = fast_prev <= slow_prev and fast_now > slow_now
        bearish_cross = fast_prev >= slow_prev and fast_now < slow_now

        if bullish_cross and rsi > 50:
            sl = price - self.atr_sl_mult * atr
            tp1 = price + self.atr_tp1_mult * atr
            tp2 = price + self.atr_tp2_mult * atr
            confidence = min(0.5 + (rsi - 50) / 100, 0.95)
            return self._make_signal(
                Action.BUY, price, sl, tp1, tp2, confidence,
                f"EMA({self.fast}/{self.slow}) bullish cross, RSI={rsi:.1f}",
                metadata={"fast_ema": fast_now, "slow_ema": slow_now, "rsi": rsi, "atr": atr},
                candle_open_time=ohlcv.last_time,
            )

        if bearish_cross and rsi < 50 and self.market_mode == MarketMode.FUTURES:
            sl = price + self.atr_sl_mult * atr
            tp1 = price - self.atr_tp1_mult * atr
            tp2 = price - self.atr_tp2_mult * atr
            confidence = min(0.5 + (50 - rsi) / 100, 0.95)
            return self._make_signal(
                Action.SELL, price, sl, tp1, tp2, confidence,
                f"EMA({self.fast}/{self.slow}) bearish cross, RSI={rsi:.1f}",
                metadata={"fast_ema": fast_now, "slow_ema": slow_now, "rsi": rsi, "atr": atr},
                candle_open_time=ohlcv.last_time,
            )

        return None


# ── Mean Reversion ────────────────────────────────────────────────────────────

class MeanReversionStrategy(BaseStrategy):
    """
    Bollinger Bands + RSI reversal.
    BUY at lower band when RSI < oversold_thresh.
    SELL at upper band when RSI > overbought_thresh (futures only).
    """

    def __init__(
        self,
        symbol: str,
        timeframe: str = "15m",
        market_mode: MarketMode = MarketMode.SPOT,
        bb_period: int = 20,
        bb_std: float = 2.0,
        oversold: float = 30.0,
        overbought: float = 70.0,
        atr_sl_mult: float = 1.2,
    ):
        super().__init__(symbol, timeframe, market_mode)
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.oversold = oversold
        self.overbought = overbought
        self.atr_sl_mult = atr_sl_mult

    async def compute(self, ohlcv: OHLCV) -> Optional[StrategySignal]:
        closes = ohlcv.closes
        if len(closes) < self.bb_period + 5:
            return None

        upper, mid, lower = _bollinger(closes, self.bb_period, self.bb_std)
        rsi = _rsi(closes)
        atr = _atr(ohlcv.highs, ohlcv.lows, closes)
        price = ohlcv.last_close

        if price <= lower and rsi < self.oversold:
            sl = price - self.atr_sl_mult * atr
            tp1 = mid
            tp2 = upper
            confidence = min(0.45 + (self.oversold - rsi) / 60, 0.90)
            return self._make_signal(
                Action.BUY, price, sl, tp1, tp2, confidence,
                f"MeanRev: price@lower_BB({lower:.2f}), RSI={rsi:.1f}",
                metadata={"upper": upper, "mid": mid, "lower": lower},
                candle_open_time=ohlcv.last_time,
            )

        if price >= upper and rsi > self.overbought and self.market_mode == MarketMode.FUTURES:
            sl = price + self.atr_sl_mult * atr
            tp1 = mid
            tp2 = lower
            confidence = min(0.45 + (rsi - self.overbought) / 60, 0.90)
            return self._make_signal(
                Action.SELL, price, sl, tp1, tp2, confidence,
                f"MeanRev: price@upper_BB({upper:.2f}), RSI={rsi:.1f}",
                metadata={"upper": upper, "mid": mid, "lower": lower},
                candle_open_time=ohlcv.last_time,
            )

        return None


# ── Breakout ──────────────────────────────────────────────────────────────────

class BreakoutStrategy(BaseStrategy):
    """
    N-candle high/low breakout with volume confirmation.
    BUY on break above resistance with volume > vol_mult * avg_volume.
    """

    def __init__(
        self,
        symbol: str,
        timeframe: str = "1h",
        market_mode: MarketMode = MarketMode.SPOT,
        lookback: int = 20,
        vol_mult: float = 1.5,
        atr_sl_mult: float = 1.0,
        atr_tp1_mult: float = 2.0,
        atr_tp2_mult: float = 4.0,
    ):
        super().__init__(symbol, timeframe, market_mode)
        self.lookback = lookback
        self.vol_mult = vol_mult
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp1_mult = atr_tp1_mult
        self.atr_tp2_mult = atr_tp2_mult

    async def compute(self, ohlcv: OHLCV) -> Optional[StrategySignal]:
        closes = ohlcv.closes
        if len(closes) < self.lookback + 5:
            return None

        resistance = max(ohlcv.highs[-self.lookback - 1 : -1])
        support = min(ohlcv.lows[-self.lookback - 1 : -1])
        avg_vol = sum(ohlcv.volumes[-self.lookback:]) / self.lookback
        current_vol = ohlcv.volumes[-1]
        price = ohlcv.last_close
        atr = _atr(ohlcv.highs, ohlcv.lows, closes)
        vol_confirm = current_vol > self.vol_mult * avg_vol

        if price > resistance and vol_confirm:
            sl = resistance - self.atr_sl_mult * atr
            tp1 = price + self.atr_tp1_mult * atr
            tp2 = price + self.atr_tp2_mult * atr
            confidence = min(0.55 + (current_vol / avg_vol - self.vol_mult) * 0.1, 0.92)
            return self._make_signal(
                Action.BUY, price, sl, tp1, tp2, confidence,
                f"Breakout above resistance={resistance:.2f}, vol×{current_vol/avg_vol:.1f}",
                metadata={"resistance": resistance, "support": support, "vol_ratio": current_vol / avg_vol},
                candle_open_time=ohlcv.last_time,
            )

        if price < support and vol_confirm and self.market_mode == MarketMode.FUTURES:
            sl = support + self.atr_sl_mult * atr
            tp1 = price - self.atr_tp1_mult * atr
            tp2 = price - self.atr_tp2_mult * atr
            confidence = min(0.55 + (current_vol / avg_vol - self.vol_mult) * 0.1, 0.92)
            return self._make_signal(
                Action.SELL, price, sl, tp1, tp2, confidence,
                f"Breakdown below support={support:.2f}, vol×{current_vol/avg_vol:.1f}",
                metadata={"resistance": resistance, "support": support, "vol_ratio": current_vol / avg_vol},
                candle_open_time=ohlcv.last_time,
            )

        return None


# ── Composite Strategy ────────────────────────────────────────────────────────

class CompositeStrategy(BaseStrategy):
    """
    Weighted voting across multiple child strategies.
    Merges signals by action; applies conflict resolution:
    - If weighted net confidence < min_consensus → HOLD.
    - REVERSE action only when all child signals agree direction reversal.
    """

    def __init__(
        self,
        strategies: List[tuple],  # (strategy, weight)
        symbol: str,
        timeframe: str = "5m",
        market_mode: MarketMode = MarketMode.SPOT,
        min_consensus: float = 0.55,
    ):
        super().__init__(symbol, timeframe, market_mode)
        self.strategies = strategies
        self.min_consensus = min_consensus

    async def compute(self, ohlcv: OHLCV) -> Optional[StrategySignal]:
        tasks = [s.compute(ohlcv) for s, _ in self.strategies]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        votes: dict = {}
        for (strat, weight), result in zip(self.strategies, results):
            if isinstance(result, Exception) or result is None:
                continue
            signal: StrategySignal = result
            action = signal.action
            if action not in votes:
                votes[action] = (0.0, [])
            total_w, sigs = votes[action]
            votes[action] = (total_w + weight * signal.confidence, sigs + [signal])

        if not votes:
            return None

        best_action = max(votes, key=lambda a: votes[a][0])
        best_weight, best_sigs = votes[best_action]
        total_possible = sum(w for _, w in self.strategies)
        net_confidence = best_weight / total_possible if total_possible else 0.0

        if net_confidence < self.min_consensus or best_action == Action.HOLD:
            return None

        ref = best_sigs[0]
        sl = sum(s.stop_loss for s in best_sigs) / len(best_sigs)
        tp1 = sum(s.take_profit_1 for s in best_sigs) / len(best_sigs)
        tp2 = sum(s.take_profit_2 for s in best_sigs) / len(best_sigs)
        reason = f"Composite({len(best_sigs)}/{len(self.strategies)}): " + "; ".join(s.reason for s in best_sigs)

        return self._make_signal(
            best_action,
            ref.entry_price or ohlcv.last_close,
            sl, tp1, tp2,
            round(net_confidence, 4),
            reason,
            entry_type=ref.entry_type,
            trailing_stop=ref.trailing_stop,
            metadata={"votes": {str(k): v[0] for k, v in votes.items()}},
            candle_open_time=ohlcv.last_time,
        )
