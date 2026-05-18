"""
strategy_engine.py – BaseStrategy ABC + TrendFollowing, MeanReversion,
Breakout, and CompositeStrategy implementations.

FIX 1: All indicators computed on closes[:-1] (confirmed candles only) —
        eliminates lookahead bias from intra-candle signal flipping.
FIX 2: ADX indicator + MarketRegime detection — routes strategies to the
        correct market regime (TRENDING vs RANGING vs VOLATILE).
FIX 3: Volume filter on TrendFollowing — skips dead-market entries.
"""
from __future__ import annotations

import abc
import asyncio
from enum import Enum
from typing import List, Optional, Sequence

import structlog

from backend.models import Action, EntryType, MarketMode, StrategySignal

log = structlog.get_logger(__name__)


# ── Market Regime ─────────────────────────────────────────────────────────────

class MarketRegime(str, Enum):
    TRENDING  = "TRENDING"   # ADX > 25 → TrendFollowing + Breakout
    RANGING   = "RANGING"    # ADX < 20 → MeanReversion
    VOLATILE  = "VOLATILE"   # ATR% > threshold → reduce size, skip breakout
    UNKNOWN   = "UNKNOWN"    # insufficient data


# ── Indicators (all operate on CONFIRMED candles — no lookahead) ──────────────

def _ema(prices: List[float], period: int) -> float:
    """Exponential moving average. Always pass confirmed (closed) candles."""
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
    """Average True Range. Always pass confirmed candles."""
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if not trs:
        return 0.0
    return sum(trs[-period:]) / min(len(trs), period)


def _rsi(closes: List[float], period: int = 14) -> float:
    """Relative Strength Index. Always pass confirmed candles."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [max(d, 0)   for d in deltas[-period:]]
    losses = [abs(min(d, 0)) for d in deltas[-period:]]
    avg_gain = sum(gains)  / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _bollinger(closes: List[float], period: int = 20, std_mult: float = 2.0):
    """Returns (upper, middle, lower). Always pass confirmed candles."""
    data = closes[-period:]
    mid  = sum(data) / len(data)
    variance = sum((p - mid) ** 2 for p in data) / len(data)
    std = variance ** 0.5
    return mid + std_mult * std, mid, mid - std_mult * std


def _adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """
    Average Directional Index — measures trend strength (not direction).
    ADX > 25  → trending market   (use TrendFollowing / Breakout)
    ADX < 20  → ranging market    (use MeanReversion)
    ADX 20-25 → transitional zone
    Always pass confirmed candles.
    """
    if len(closes) < period * 2:
        return 0.0

    plus_dm_list, minus_dm_list, tr_list = [], [], []
    for i in range(1, len(closes)):
        h_diff = highs[i]  - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]
        plus_dm_list.append(h_diff if h_diff > l_diff and h_diff > 0 else 0.0)
        minus_dm_list.append(l_diff if l_diff > h_diff and l_diff > 0 else 0.0)
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        )
        tr_list.append(tr)

    def _smooth(data: List[float], n: int) -> List[float]:
        """Wilder smoothing."""
        result = [sum(data[:n])]
        for v in data[n:]:
            result.append(result[-1] - result[-1] / n + v)
        return result

    tr_s    = _smooth(tr_list,      period)
    pdm_s   = _smooth(plus_dm_list, period)
    mdm_s   = _smooth(minus_dm_list, period)

    dx_list = []
    for tr_v, pdm_v, mdm_v in zip(tr_s, pdm_s, mdm_s):
        if tr_v == 0:
            continue
        pdi = 100 * pdm_v / tr_v
        mdi = 100 * mdm_v / tr_v
        denom = pdi + mdi
        if denom == 0:
            continue
        dx_list.append(100 * abs(pdi - mdi) / denom)

    if not dx_list:
        return 0.0
    return sum(dx_list[-period:]) / min(len(dx_list), period)


def detect_regime(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    adx_trend_threshold: float = 25.0,
    adx_range_threshold: float = 20.0,
    atr_vol_threshold: float = 0.035,  # ATR% > 3.5% → volatile
) -> MarketRegime:
    """
    Detect current market regime using ADX + ATR%.
    Call with CONFIRMED candles (closes[:-1] from raw OHLCV).
    """
    if len(closes) < 30:
        return MarketRegime.UNKNOWN

    adx = _adx(highs, lows, closes)
    atr = _atr(highs, lows, closes)
    atr_pct = atr / closes[-1] if closes[-1] > 0 else 0.0

    log.debug("regime_detection", adx=round(adx, 2), atr_pct=round(atr_pct, 4))

    if atr_pct > atr_vol_threshold:
        return MarketRegime.VOLATILE
    if adx >= adx_trend_threshold:
        return MarketRegime.TRENDING
    if adx <= adx_range_threshold:
        return MarketRegime.RANGING
    return MarketRegime.RANGING  # transitional → default to safer regime


# ── OHLCV helper ──────────────────────────────────────────────────────────────

class OHLCV:
    """Thin wrapper around raw Binance kline data."""

    def __init__(self, klines: List[List]):
        self.opens   = [float(k[1]) for k in klines]
        self.highs   = [float(k[2]) for k in klines]
        self.lows    = [float(k[3]) for k in klines]
        self.closes  = [float(k[4]) for k in klines]
        self.volumes = [float(k[5]) for k in klines]
        self.times   = [int(k[0])   for k in klines]

    @property
    def last_close(self) -> float:
        """CONFIRMED last close (penultimate candle — the one that is closed)."""
        # Always use index -2 to avoid reading an open/live candle.
        # The last element (index -1) is the currently open candle.
        return self.closes[-2] if len(self.closes) >= 2 else self.closes[-1]

    @property
    def last_time(self) -> int:
        return self.times[-2] if len(self.times) >= 2 else self.times[-1]

    @property
    def confirmed_closes(self) -> List[float]:
        """All confirmed (closed) candle closes — excludes the live candle."""
        return self.closes[:-1]

    @property
    def confirmed_highs(self) -> List[float]:
        return self.highs[:-1]

    @property
    def confirmed_lows(self) -> List[float]:
        return self.lows[:-1]

    @property
    def confirmed_volumes(self) -> List[float]:
        return self.volumes[:-1]

    def regime(self) -> MarketRegime:
        """Detect and cache market regime from confirmed candles."""
        return detect_regime(self.confirmed_highs, self.confirmed_lows, self.confirmed_closes)


# ── Base Strategy ─────────────────────────────────────────────────────────────

class BaseStrategy(abc.ABC):
    """Abstract base. Every strategy must implement `compute`."""

    def __init__(
        self,
        symbol: str,
        timeframe: str = "5m",
        market_mode: MarketMode = MarketMode.SPOT,
    ):
        self.symbol      = symbol
        self.timeframe   = timeframe
        self.market_mode = market_mode
        self.name        = self.__class__.__name__

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

    FIX 1: Uses ohlcv.confirmed_closes — no lookahead.
    FIX 3: Volume filter — skips signals when current volume < vol_min_mult * avg20.
           Prevents entering during dead/low-liquidity periods.
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
        vol_min_mult: float = 0.7,   # FIX 3: volume must be ≥ 70% of 20-bar avg
    ):
        super().__init__(symbol, timeframe, market_mode)
        self.fast         = fast
        self.slow         = slow
        self.atr_sl_mult  = atr_sl_mult
        self.atr_tp1_mult = atr_tp1_mult
        self.atr_tp2_mult = atr_tp2_mult
        self.vol_min_mult = vol_min_mult

    async def compute(self, ohlcv: OHLCV) -> Optional[StrategySignal]:
        # ── FIX 1: always use confirmed candles ──────────────────────────────
        closes  = ohlcv.confirmed_closes
        highs   = ohlcv.confirmed_highs
        lows    = ohlcv.confirmed_lows
        volumes = ohlcv.confirmed_volumes

        if len(closes) < self.slow + 5:
            return None

        # ── FIX 3: volume filter ─────────────────────────────────────────────
        avg_vol_20 = sum(volumes[-20:]) / min(len(volumes), 20)
        last_vol   = volumes[-1]
        if avg_vol_20 > 0 and last_vol < self.vol_min_mult * avg_vol_20:
            log.debug(
                "trend_skip_low_volume",
                symbol=self.symbol,
                last_vol=last_vol,
                avg_vol=avg_vol_20,
                ratio=round(last_vol / avg_vol_20, 2),
            )
            return None

        fast_now  = _ema(closes, self.fast)
        slow_now  = _ema(closes, self.slow)
        fast_prev = _ema(closes[:-1], self.fast)
        slow_prev = _ema(closes[:-1], self.slow)
        rsi       = _rsi(closes)
        atr       = _atr(highs, lows, closes)
        price     = closes[-1]  # confirmed close price

        bullish_cross = fast_prev <= slow_prev and fast_now > slow_now
        bearish_cross = fast_prev >= slow_prev and fast_now < slow_now

        if bullish_cross and rsi > 50:
            sl  = price - self.atr_sl_mult  * atr
            tp1 = price + self.atr_tp1_mult * atr
            tp2 = price + self.atr_tp2_mult * atr
            confidence = min(0.5 + (rsi - 50) / 100, 0.95)
            return self._make_signal(
                Action.BUY, price, sl, tp1, tp2, confidence,
                f"EMA({self.fast}/{self.slow}) bullish cross, RSI={rsi:.1f}, vol_ratio={last_vol/avg_vol_20:.2f}",
                metadata={"fast_ema": fast_now, "slow_ema": slow_now, "rsi": rsi, "atr": atr,
                          "vol_ratio": last_vol / avg_vol_20},
                candle_open_time=ohlcv.last_time,
            )

        if bearish_cross and rsi < 50 and self.market_mode == MarketMode.FUTURES:
            sl  = price + self.atr_sl_mult  * atr
            tp1 = price - self.atr_tp1_mult * atr
            tp2 = price - self.atr_tp2_mult * atr
            confidence = min(0.5 + (50 - rsi) / 100, 0.95)
            return self._make_signal(
                Action.SELL, price, sl, tp1, tp2, confidence,
                f"EMA({self.fast}/{self.slow}) bearish cross, RSI={rsi:.1f}, vol_ratio={last_vol/avg_vol_20:.2f}",
                metadata={"fast_ema": fast_now, "slow_ema": slow_now, "rsi": rsi, "atr": atr,
                          "vol_ratio": last_vol / avg_vol_20},
                candle_open_time=ohlcv.last_time,
            )

        return None


# ── Mean Reversion ────────────────────────────────────────────────────────────

class MeanReversionStrategy(BaseStrategy):
    """
    Bollinger Bands + RSI reversal.
    FIX 1: Uses ohlcv.confirmed_closes — no lookahead.
    Best used in RANGING regime (ADX < 20).
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
        self.bb_period  = bb_period
        self.bb_std     = bb_std
        self.oversold   = oversold
        self.overbought = overbought
        self.atr_sl_mult = atr_sl_mult

    async def compute(self, ohlcv: OHLCV) -> Optional[StrategySignal]:
        # ── FIX 1: confirmed candles only ────────────────────────────────────
        closes = ohlcv.confirmed_closes
        highs  = ohlcv.confirmed_highs
        lows   = ohlcv.confirmed_lows

        if len(closes) < self.bb_period + 5:
            return None

        upper, mid, lower = _bollinger(closes, self.bb_period, self.bb_std)
        rsi   = _rsi(closes)
        atr   = _atr(highs, lows, closes)
        price = closes[-1]

        if price <= lower and rsi < self.oversold:
            sl  = price - self.atr_sl_mult * atr
            tp1 = mid
            tp2 = upper
            confidence = min(0.45 + (self.oversold - rsi) / 60, 0.90)
            return self._make_signal(
                Action.BUY, price, sl, tp1, tp2, confidence,
                f"MeanRev: price@lower_BB({lower:.2f}), RSI={rsi:.1f}",
                metadata={"upper": upper, "mid": mid, "lower": lower, "rsi": rsi},
                candle_open_time=ohlcv.last_time,
            )

        if price >= upper and rsi > self.overbought and self.market_mode == MarketMode.FUTURES:
            sl  = price + self.atr_sl_mult * atr
            tp1 = mid
            tp2 = lower
            confidence = min(0.45 + (rsi - self.overbought) / 60, 0.90)
            return self._make_signal(
                Action.SELL, price, sl, tp1, tp2, confidence,
                f"MeanRev: price@upper_BB({upper:.2f}), RSI={rsi:.1f}",
                metadata={"upper": upper, "mid": mid, "lower": lower, "rsi": rsi},
                candle_open_time=ohlcv.last_time,
            )

        return None


# ── Breakout ──────────────────────────────────────────────────────────────────

class BreakoutStrategy(BaseStrategy):
    """
    N-candle high/low breakout with volume confirmation.
    FIX 1: Uses ohlcv.confirmed_closes — no lookahead.
    Best used in TRENDING regime (ADX > 25).
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
        self.lookback      = lookback
        self.vol_mult      = vol_mult
        self.atr_sl_mult   = atr_sl_mult
        self.atr_tp1_mult  = atr_tp1_mult
        self.atr_tp2_mult  = atr_tp2_mult

    async def compute(self, ohlcv: OHLCV) -> Optional[StrategySignal]:
        # ── FIX 1: confirmed candles only ────────────────────────────────────
        closes  = ohlcv.confirmed_closes
        highs   = ohlcv.confirmed_highs
        lows    = ohlcv.confirmed_lows
        volumes = ohlcv.confirmed_volumes

        if len(closes) < self.lookback + 5:
            return None

        resistance  = max(highs[-self.lookback - 1 : -1])
        support     = min(lows[-self.lookback - 1 : -1])
        avg_vol     = sum(volumes[-self.lookback:]) / self.lookback
        current_vol = volumes[-1]
        price       = closes[-1]
        atr         = _atr(highs, lows, closes)
        vol_confirm = current_vol > self.vol_mult * avg_vol

        if price > resistance and vol_confirm:
            sl  = resistance - self.atr_sl_mult * atr
            tp1 = price + self.atr_tp1_mult * atr
            tp2 = price + self.atr_tp2_mult * atr
            confidence = min(0.55 + (current_vol / avg_vol - self.vol_mult) * 0.1, 0.92)
            return self._make_signal(
                Action.BUY, price, sl, tp1, tp2, confidence,
                f"Breakout above resistance={resistance:.2f}, vol×{current_vol/avg_vol:.1f}",
                metadata={"resistance": resistance, "support": support,
                          "vol_ratio": current_vol / avg_vol},
                candle_open_time=ohlcv.last_time,
            )

        if price < support and vol_confirm and self.market_mode == MarketMode.FUTURES:
            sl  = support + self.atr_sl_mult * atr
            tp1 = price - self.atr_tp1_mult * atr
            tp2 = price - self.atr_tp2_mult * atr
            confidence = min(0.55 + (current_vol / avg_vol - self.vol_mult) * 0.1, 0.92)
            return self._make_signal(
                Action.SELL, price, sl, tp1, tp2, confidence,
                f"Breakdown below support={support:.2f}, vol×{current_vol/avg_vol:.1f}",
                metadata={"resistance": resistance, "support": support,
                          "vol_ratio": current_vol / avg_vol},
                candle_open_time=ohlcv.last_time,
            )

        return None


# ── Composite Strategy ────────────────────────────────────────────────────────

class CompositeStrategy(BaseStrategy):
    """
    Weighted voting across multiple child strategies.

    FIX 2: Regime-aware routing — before gathering signals, detects the
    current market regime (TRENDING / RANGING / VOLATILE) and skips
    child strategies that are not suited for that regime:

      TRENDING  → run TrendFollowingStrategy + BreakoutStrategy
                  skip MeanReversionStrategy (would fade the trend)
      RANGING   → run MeanReversionStrategy only
                  skip TrendFollowing + Breakout (would whipsaw)
      VOLATILE  → skip ALL strategies, return None (stay flat)
      UNKNOWN   → run all strategies with standard consensus filter

    Merges signals by action; applies conflict resolution:
    - If weighted net confidence < min_consensus → HOLD.
    - REVERSE action only when all child signals agree direction reversal.
    """

    # Maps strategy class names to the regimes where they are ALLOWED to trade
    _REGIME_WHITELIST: dict = {
        "TrendFollowingStrategy": {MarketRegime.TRENDING, MarketRegime.UNKNOWN},
        "BreakoutStrategy":       {MarketRegime.TRENDING, MarketRegime.UNKNOWN},
        "MeanReversionStrategy":  {MarketRegime.RANGING,  MarketRegime.UNKNOWN},
    }

    def __init__(
        self,
        strategies: List[tuple],   # [(strategy_instance, weight), ...]
        symbol: str,
        timeframe: str = "5m",
        market_mode: MarketMode = MarketMode.SPOT,
        min_consensus: float = 0.55,
    ):
        super().__init__(symbol, timeframe, market_mode)
        self.strategies    = strategies
        self.min_consensus = min_consensus

    async def compute(self, ohlcv: OHLCV) -> Optional[StrategySignal]:
        # ── FIX 2: detect regime from confirmed candles ──────────────────────
        regime = ohlcv.regime()
        log.info("composite_regime", symbol=self.symbol, regime=regime.value)

        if regime == MarketRegime.VOLATILE:
            log.warning("composite_skip_volatile", symbol=self.symbol)
            return None

        # Filter strategies allowed in this regime
        active_strategies = [
            (s, w) for s, w in self.strategies
            if regime == MarketRegime.UNKNOWN
            or self._REGIME_WHITELIST.get(s.__class__.__name__, {MarketRegime.UNKNOWN}).intersection({regime})
        ]

        if not active_strategies:
            log.info("composite_no_active_strategies", regime=regime.value)
            return None

        tasks   = [s.compute(ohlcv) for s, _ in active_strategies]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        votes: dict = {}
        for (strat, weight), result in zip(active_strategies, results):
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

        best_action          = max(votes, key=lambda a: votes[a][0])
        best_weight, best_sigs = votes[best_action]
        total_possible       = sum(w for _, w in active_strategies)
        net_confidence       = best_weight / total_possible if total_possible else 0.0

        if net_confidence < self.min_consensus or best_action == Action.HOLD:
            log.debug(
                "composite_consensus_not_met",
                action=best_action,
                net_confidence=net_confidence,
                min_consensus=self.min_consensus,
            )
            return None

        ref = best_sigs[0]
        sl  = sum(s.stop_loss      for s in best_sigs) / len(best_sigs)
        tp1 = sum(s.take_profit_1  for s in best_sigs) / len(best_sigs)
        tp2 = sum(s.take_profit_2  for s in best_sigs) / len(best_sigs)
        reason = (
            f"Composite[{regime.value}]({len(best_sigs)}/{len(self.strategies)}): "
            + "; ".join(s.reason for s in best_sigs)
        )

        return self._make_signal(
            best_action,
            ref.entry_price or ohlcv.last_close,
            sl, tp1, tp2,
            round(net_confidence, 4),
            reason,
            entry_type=ref.entry_type,
            trailing_stop=ref.trailing_stop,
            metadata={
                "regime": regime.value,
                "active_strategies": len(active_strategies),
                "votes": {str(k): v[0] for k, v in votes.items()},
            },
            candle_open_time=ohlcv.last_time,
        )
