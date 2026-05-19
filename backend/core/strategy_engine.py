"""
strategy_engine.py – BaseStrategy ABC + TrendFollowing, MeanReversion,
Breakout, and CompositeStrategy implementations.

FIX 2: _merge_signals() now uses conservative min/max for SL/TP instead of
        arithmetic average — prevents averaged SL from invalidating RR check.
FIX 5: detect_regime() called ONCE in CompositeStrategy.compute(), result
        passed to sub-strategies to avoid 3-4x redundant ADX recalculation.
"""
from __future__ import annotations

import math
import statistics
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import structlog

from backend.config import get_settings
from backend.models import Action, MarketMode, StrategySignal

log = structlog.get_logger(__name__)
settings = get_settings()


# ── OHLCV Wrapper ─────────────────────────────────────────────────────────────

class OHLCV:
    """
    Immutable wrapper around raw Binance klines.
    All accessors return confirmed closed candles (index -2) to avoid
    lookahead bias on the still-forming current candle.

    Kline format (Binance): [
        open_time, open, high, low, close, volume,
        close_time, quote_vol, trades, taker_buy_base, taker_buy_quote, ignore
    ]
    """

    def __init__(self, klines: List):
        if len(klines) < 20:
            raise ValueError(f"Insufficient candles: {len(klines)} (min 20)")
        self._k = klines

    @property
    def opens(self) -> List[float]:   return [float(k[1]) for k in self._k]
    @property
    def highs(self) -> List[float]:   return [float(k[2]) for k in self._k]
    @property
    def lows(self) -> List[float]:    return [float(k[3]) for k in self._k]
    @property
    def closes(self) -> List[float]:  return [float(k[4]) for k in self._k]
    @property
    def volumes(self) -> List[float]: return [float(k[5]) for k in self._k]

    @property
    def confirmed_closes(self) -> List[float]:
        """All closed candles except the forming one."""
        return self.closes[:-1]

    @property
    def confirmed_highs(self) -> List[float]:
        return self.highs[:-1]

    @property
    def confirmed_lows(self) -> List[float]:
        return self.lows[:-1]

    @property
    def last_close(self) -> float:
        """Most recent confirmed close (second-to-last candle)."""
        closes = self.closes
        return closes[-2] if len(closes) >= 2 else closes[-1]

    @property
    def candle_open_time(self) -> Optional[int]:
        """Open timestamp of the last confirmed candle (ms epoch)."""
        if len(self._k) >= 2:
            return int(self._k[-2][0])
        return None


# ── Market Regime ─────────────────────────────────────────────────────────────

class MarketRegime:
    TRENDING   = "TRENDING"
    RANGING    = "RANGING"
    VOLATILE   = "VOLATILE"


def detect_regime(ohlcv: OHLCV, adx_period: int = 14) -> str:
    """
    Classify market regime based on ADX + ATR%.
    Used by CompositeStrategy to filter sub-strategy signals.

    Returns: MarketRegime.TRENDING | RANGING | VOLATILE
    """
    closes = ohlcv.confirmed_closes
    highs  = ohlcv.confirmed_highs
    lows   = ohlcv.confirmed_lows

    if len(closes) < adx_period + 5:
        return MarketRegime.RANGING

    adx_val = _adx(highs, lows, closes, adx_period)
    atr_val = _atr(highs, lows, closes, adx_period)
    atr_pct = atr_val / closes[-1] if closes[-1] > 0 else 0

    if atr_pct > 0.035:
        return MarketRegime.VOLATILE
    if adx_val > 25:
        return MarketRegime.TRENDING
    return MarketRegime.RANGING


# ── Base Strategy ─────────────────────────────────────────────────────────────

class BaseStrategy(ABC):
    """
    Abstract base for all strategy implementations.
    Subclasses implement compute() and may accept an optional pre-computed regime.
    """

    def __init__(self, symbol: str = "", timeframe: str = "15m",
                 market_mode: MarketMode = MarketMode.SPOT):
        self.symbol      = symbol
        self.timeframe   = timeframe
        self.market_mode = market_mode

    @abstractmethod
    async def compute(
        self, ohlcv: OHLCV, regime: Optional[str] = None
    ) -> Optional[StrategySignal]:
        """
        Analyse OHLCV and return a signal or None.
        regime: pre-computed MarketRegime string (FIX 5 — avoid redundant ADX).
        """
        ...

    def _make_signal(
        self,
        action: Action,
        confidence: float,
        entry_price: Optional[float],
        stop_loss: float,
        take_profit_1: float,
        take_profit_2: float,
        reason: str,
        ohlcv: OHLCV,
        trailing_stop: Optional[float] = None,
        metadata: Optional[Dict] = None,
    ) -> StrategySignal:
        """Helper to construct a fully-populated StrategySignal."""
        return StrategySignal(
            symbol=self.symbol,
            action=action,
            confidence=round(confidence, 4),
            entry_type="market" if entry_price is None else "limit",
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            trailing_stop=trailing_stop,
            timeframe=self.timeframe,
            reason=reason,
            market_mode=self.market_mode,
            candle_open_time=ohlcv.candle_open_time,
            metadata={"last_close": ohlcv.last_close, **(metadata or {})},
        )


# ── Trend Following Strategy ──────────────────────────────────────────────────

class TrendFollowingStrategy(BaseStrategy):
    """
    EMA crossover (fast/slow) + RSI filter + ATR-based SL/TP.
    Only trades in TRENDING regime.
    """

    def __init__(self, fast: int = 9, slow: int = 21, rsi_period: int = 14,
                 atr_period: int = 14, **kwargs):
        super().__init__(**kwargs)
        self.fast       = fast
        self.slow       = slow
        self.rsi_period = rsi_period
        self.atr_period = atr_period

    async def compute(
        self, ohlcv: OHLCV, regime: Optional[str] = None
    ) -> Optional[StrategySignal]:
        # FIX 5: use pre-computed regime if provided
        r = regime if regime is not None else detect_regime(ohlcv)
        if r != MarketRegime.TRENDING:
            return None

        closes = ohlcv.confirmed_closes
        highs  = ohlcv.confirmed_highs
        lows   = ohlcv.confirmed_lows

        if len(closes) < self.slow + 5:
            return None

        ema_fast = _ema(closes, self.fast)
        ema_slow = _ema(closes, self.slow)
        rsi      = _rsi(closes, self.rsi_period)
        atr      = _atr(highs, lows, closes, self.atr_period)
        price    = closes[-1]

        prev_fast = _ema(closes[:-1], self.fast)
        prev_slow = _ema(closes[:-1], self.slow)

        bullish_cross = prev_fast <= prev_slow and ema_fast > ema_slow
        bearish_cross = prev_fast >= prev_slow and ema_fast < ema_slow

        if bullish_cross and 40 < rsi < 70:
            sl  = price - atr * 1.5
            tp1 = price + atr * 2.5
            tp2 = price + atr * 4.0
            conf = min(0.95, 0.60 + (ema_fast - ema_slow) / price * 10)
            return self._make_signal(
                Action.BUY, conf, None, sl, tp1, tp2,
                f"EMA{self.fast}/{self.slow} bullish cross, RSI={rsi:.1f}",
                ohlcv, metadata={"ema_fast": ema_fast, "ema_slow": ema_slow, "atr": atr},
            )

        if bearish_cross and self.market_mode == MarketMode.FUTURES and 30 < rsi < 60:
            sl  = price + atr * 1.5
            tp1 = price - atr * 2.5
            tp2 = price - atr * 4.0
            conf = min(0.95, 0.60 + (ema_slow - ema_fast) / price * 10)
            return self._make_signal(
                Action.SELL, conf, None, sl, tp1, tp2,
                f"EMA{self.fast}/{self.slow} bearish cross, RSI={rsi:.1f}",
                ohlcv, metadata={"ema_fast": ema_fast, "ema_slow": ema_slow, "atr": atr},
            )

        return None


# ── Mean Reversion Strategy ───────────────────────────────────────────────────

class MeanReversionStrategy(BaseStrategy):
    """
    Bollinger Bands + RSI extremes. Only trades in RANGING regime.
    """

    def __init__(self, bb_period: int = 20, bb_std: float = 2.0,
                 rsi_period: int = 14, **kwargs):
        super().__init__(**kwargs)
        self.bb_period  = bb_period
        self.bb_std     = bb_std
        self.rsi_period = rsi_period

    async def compute(
        self, ohlcv: OHLCV, regime: Optional[str] = None
    ) -> Optional[StrategySignal]:
        r = regime if regime is not None else detect_regime(ohlcv)
        if r != MarketRegime.RANGING:
            return None

        closes = ohlcv.confirmed_closes
        if len(closes) < self.bb_period + 5:
            return None

        upper, mid, lower = _bollinger(closes, self.bb_period, self.bb_std)
        rsi   = _rsi(closes, self.rsi_period)
        price = closes[-1]
        atr   = _atr(ohlcv.confirmed_highs, ohlcv.confirmed_lows, closes, 14)

        if price <= lower and rsi < 35:
            sl  = lower - atr * 0.5
            tp1 = mid
            tp2 = upper
            conf = min(0.90, 0.55 + (lower - price) / (upper - lower) * 0.5)
            return self._make_signal(
                Action.BUY, conf, None, sl, tp1, tp2,
                f"BB lower touch, RSI={rsi:.1f}",
                ohlcv, metadata={"bb_upper": upper, "bb_mid": mid, "bb_lower": lower},
            )

        if price >= upper and rsi > 65 and self.market_mode == MarketMode.FUTURES:
            sl  = upper + atr * 0.5
            tp1 = mid
            tp2 = lower
            conf = min(0.90, 0.55 + (price - upper) / (upper - lower) * 0.5)
            return self._make_signal(
                Action.SELL, conf, None, sl, tp1, tp2,
                f"BB upper touch, RSI={rsi:.1f}",
                ohlcv, metadata={"bb_upper": upper, "bb_mid": mid, "bb_lower": lower},
            )

        return None


# ── Breakout Strategy ─────────────────────────────────────────────────────────

class BreakoutStrategy(BaseStrategy):
    """
    N-candle high/low breakout with volume confirmation.
    Trades in both TRENDING and RANGING regimes (not VOLATILE).
    """

    def __init__(self, lookback: int = 20, volume_factor: float = 1.5, **kwargs):
        super().__init__(**kwargs)
        self.lookback       = lookback
        self.volume_factor  = volume_factor

    async def compute(
        self, ohlcv: OHLCV, regime: Optional[str] = None
    ) -> Optional[StrategySignal]:
        r = regime if regime is not None else detect_regime(ohlcv)
        if r == MarketRegime.VOLATILE:
            return None

        closes  = ohlcv.confirmed_closes
        highs   = ohlcv.confirmed_highs
        lows    = ohlcv.confirmed_lows
        volumes = ohlcv.volumes[:-1]

        if len(closes) < self.lookback + 2:
            return None

        window_highs  = highs[-(self.lookback + 1):-1]
        window_lows   = lows[-(self.lookback + 1):-1]
        window_vols   = volumes[-(self.lookback + 1):-1]
        price         = closes[-1]
        prev_price    = closes[-2]
        current_vol   = volumes[-1]
        avg_vol       = sum(window_vols) / len(window_vols) if window_vols else 1
        atr           = _atr(highs, lows, closes, 14)

        highest = max(window_highs)
        lowest  = min(window_lows)
        vol_ok  = current_vol > avg_vol * self.volume_factor

        if prev_price <= highest and price > highest and vol_ok:
            sl  = highest - atr * 0.5
            tp1 = price + atr * 2.0
            tp2 = price + atr * 3.5
            conf = min(0.92, 0.65 + (current_vol / avg_vol - 1) * 0.1)
            return self._make_signal(
                Action.BUY, conf, None, sl, tp1, tp2,
                f"Breakout above {self.lookback}-candle high={highest:.2f}, vol={vol_ok}",
                ohlcv, metadata={"breakout_level": highest, "volume_ratio": current_vol / avg_vol},
            )

        if prev_price >= lowest and price < lowest and vol_ok and self.market_mode == MarketMode.FUTURES:
            sl  = lowest + atr * 0.5
            tp1 = price - atr * 2.0
            tp2 = price - atr * 3.5
            conf = min(0.92, 0.65 + (current_vol / avg_vol - 1) * 0.1)
            return self._make_signal(
                Action.SELL, conf, None, sl, tp1, tp2,
                f"Breakdown below {self.lookback}-candle low={lowest:.2f}, vol={vol_ok}",
                ohlcv, metadata={"breakout_level": lowest, "volume_ratio": current_vol / avg_vol},
            )

        return None


# ── Composite Strategy ────────────────────────────────────────────────────────

class CompositeStrategy(BaseStrategy):
    """
    Weighted voting across sub-strategies with regime-aware conflict resolution.

    FIX 5: detect_regime() called ONCE here, result forwarded to all sub-strategies
           so ADX is not recalculated 3-4 times per tick.

    FIX 2: _merge_signals() uses conservative min/max for SL/TP instead of
           arithmetic average to preserve valid RR on merged signal.
    """

    # Regimes where each strategy is valid
    _REGIME_WHITELIST: Dict[str, List[str]] = {
        "TrendFollowing":  [MarketRegime.TRENDING],
        "MeanReversion":   [MarketRegime.RANGING],
        "Breakout":        [MarketRegime.TRENDING, MarketRegime.RANGING],
    }

    def __init__(
        self,
        strategies: Optional[List[BaseStrategy]] = None,
        weights: Optional[Dict[str, float]] = None,
        min_consensus: float = 0.55,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._strategies   = strategies or []
        self._weights      = weights or {}
        self.min_consensus = min_consensus

    async def compute(
        self, ohlcv: OHLCV, regime: Optional[str] = None
    ) -> Optional[StrategySignal]:
        """
        FIX 5: Compute regime ONCE, pass to all sub-strategies.
        """
        # Single regime detection for the entire composite tick
        active_regime = regime if regime is not None else detect_regime(ohlcv)

        signals: List[Tuple[StrategySignal, float]] = []
        for strat in self._strategies:
            try:
                # Pass pre-computed regime — sub-strategies skip their own detect_regime()
                sig = await strat.compute(ohlcv, regime=active_regime)
                if sig is None:
                    continue
                weight = self._weights.get(type(strat).__name__, 1.0)
                signals.append((sig, weight))
            except Exception as exc:
                log.warning("sub_strategy_error", strategy=type(strat).__name__, error=str(exc))

        if not signals:
            return None

        return self._merge_signals(signals, active_regime, ohlcv)

    def _merge_signals(
        self,
        signals: List[Tuple[StrategySignal, float]],
        regime: str,
        ohlcv: OHLCV,
    ) -> Optional[StrategySignal]:
        """
        FIX 2: Use conservative SL/TP (min/max) not arithmetic average.
        This prevents averaged SL from invalidating risk-reward and causing
        frequent LOW_RR vetos in RiskManager.
        """
        buy_weight  = sum(w for s, w in signals if s.action == Action.BUY)
        sell_weight = sum(w for s, w in signals if s.action == Action.SELL)
        total_weight = buy_weight + sell_weight

        if total_weight == 0:
            return None

        buy_consensus  = buy_weight  / total_weight
        sell_consensus = sell_weight / total_weight

        if buy_consensus >= self.min_consensus:
            best_action = Action.BUY
            best_consensus = buy_consensus
            best_sigs = [s for s, _ in signals if s.action == Action.BUY]
        elif sell_consensus >= self.min_consensus:
            best_action = Action.SELL
            best_consensus = sell_consensus
            best_sigs = [s for s, _ in signals if s.action == Action.SELL]
        else:
            log.debug(
                "composite_no_consensus",
                buy=round(buy_consensus, 3),
                sell=round(sell_consensus, 3),
                min=self.min_consensus,
            )
            return None

        if not best_sigs:
            return None

        # FIX 2: Conservative SL/TP — NOT arithmetic average
        # BUY: SL as low as possible (most protective), TP1/TP2 conservative (closest)
        # SELL: SL as high as possible (most protective), TP1/TP2 conservative (highest = closest)
        if best_action == Action.BUY:
            sl  = min(s.stop_loss     for s in best_sigs)   # lowest SL = furthest from entry
            tp1 = min(s.take_profit_1 for s in best_sigs)   # closest TP1 = most conservative
            tp2 = min(s.take_profit_2 for s in best_sigs)   # closest TP2
        else:  # SELL
            sl  = max(s.stop_loss     for s in best_sigs)   # highest SL = furthest from entry
            tp1 = max(s.take_profit_1 for s in best_sigs)   # closest TP1 for short
            tp2 = max(s.take_profit_2 for s in best_sigs)   # closest TP2 for short

        # Weighted average confidence
        conf = sum(
            s.confidence * self._weights.get(type(s).__class__.__name__, 1.0)
            for s in best_sigs
        ) / sum(self._weights.get(type(s).__class__.__name__, 1.0) for s in best_sigs)

        # Best reason from highest-confidence signal
        best_reason_sig = max(best_sigs, key=lambda s: s.confidence)

        return self._make_signal(
            best_action,
            min(conf, 0.98),
            None,  # market order — entry_price from metadata.last_close
            sl, tp1, tp2,
            f"Composite [{regime}]: {best_reason_sig.reason} | consensus={best_consensus:.2f}",
            ohlcv,
            metadata={
                "regime": regime,
                "consensus": round(best_consensus, 4),
                "strategies_voted": len(best_sigs),
                "last_close": ohlcv.last_close,
            },
        )


# ── Technical Indicators ──────────────────────────────────────────────────────

def _ema(prices: List[float], period: int) -> float:
    """Exponential Moving Average."""
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def _rsi(prices: List[float], period: int = 14) -> float:
    """RSI using Wilder smoothing (consistent with TradingView)."""
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains  = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]
    # Initial averages (simple mean over first period)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    # Wilder smoothing for the rest
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))


def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Average True Range with Wilder smoothing."""
    if len(highs) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """ADX with Wilder smoothing (same algorithm as TradingView)."""
    if len(highs) < period * 2:
        return 0.0
    dm_plus, dm_minus, trs = [], [], []
    for i in range(1, len(highs)):
        up   = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        dm_plus.append(up   if up > down and up > 0 else 0.0)
        dm_minus.append(down if down > up and down > 0 else 0.0)
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    # Wilder smoothing
    smooth_tr = sum(trs[:period])
    smooth_dp = sum(dm_plus[:period])
    smooth_dm = sum(dm_minus[:period])
    dx_list   = []
    for i in range(period, len(trs)):
        smooth_tr = smooth_tr - smooth_tr / period + trs[i]
        smooth_dp = smooth_dp - smooth_dp / period + dm_plus[i]
        smooth_dm = smooth_dm - smooth_dm / period + dm_minus[i]
        di_plus  = 100 * smooth_dp / smooth_tr if smooth_tr else 0
        di_minus = 100 * smooth_dm / smooth_tr if smooth_tr else 0
        di_sum   = di_plus + di_minus
        dx_list.append(100 * abs(di_plus - di_minus) / di_sum if di_sum else 0)
    if not dx_list:
        return 0.0
    adx = sum(dx_list[:period]) / period
    for dx in dx_list[period:]:
        adx = (adx * (period - 1) + dx) / period
    return adx


def _bollinger(prices: List[float], period: int = 20, std_mult: float = 2.0) -> Tuple[float, float, float]:
    """Bollinger Bands. Returns (upper, mid, lower)."""
    if len(prices) < period:
        p = prices[-1]
        return p, p, p
    window = prices[-period:]
    mid  = sum(window) / period
    var  = sum((p - mid) ** 2 for p in window) / period
    std  = math.sqrt(var)
    return mid + std_mult * std, mid, mid - std_mult * std
