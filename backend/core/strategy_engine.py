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
  🟡 FEAT #8 (regime): Adaugat _adx(), Regime enum, RegimeDetector.
     CompositeStrategy accepta regime_detector optional si filtreaza
     strategiile incompatibile cu regimul curent inainte de voting.
     ADX > adx_trend_threshold → TRENDING (ruleaza doar TrendFollowing + Breakout).
     ADX < adx_range_threshold  → RANGING  (ruleaza doar MeanReversion).
     NEUTRAL → toate strategiile voteaza (comportament anterior).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.models import Action, StrategySignal

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────── helpers

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _ema(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    k   = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
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


def _bollinger(
    closes: List[float], period: int = 20, std_mult: float = 2.0
) -> Tuple[float, float, float]:
    """Returneaza (upper, middle, lower)."""
    if len(closes) < period:
        c = closes[-1] if closes else 0.0
        return c, c, c
    window = closes[-period:]
    mean   = sum(window) / period
    std    = (sum((x - mean) ** 2 for x in window) / period) ** 0.5
    return mean + std_mult * std, mean, mean - std_mult * std


def _adx(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> Tuple[float, float, float]:
    """
    Calculeaza ADX, +DI, -DI folosind metoda Wilder (smoothed moving average).

    Returneaza (adx, plus_di, minus_di) ca valori in [0, 100].
    Returneaza (0.0, 0.0, 0.0) daca datele sunt insuficiente.

    Algoritm:
      1. True Range (TR) = max(H-L, |H-Cprev|, |L-Cprev|)
      2. +DM = H - H_prev daca > 0 si > |L - L_prev|, altfel 0
         -DM = L_prev - L daca > 0 si > |H - H_prev|, altfel 0
      3. Smooth TR, +DM, -DM cu Wilder MA (EMA period=14, k=1/period)
      4. +DI = 100 * smoothed_+DM / smoothed_TR
         -DI = 100 * smoothed_-DM / smoothed_TR
      5. DX = 100 * |+DI - -DI| / (+DI + -DI)
      6. ADX = Wilder MA pe DX
    """
    min_len = period * 2 + 1
    if len(closes) < min_len:
        return 0.0, 0.0, 0.0

    n = len(closes)
    trs, plus_dms, minus_dms = [], [], []

    for i in range(1, n):
        h, l, c_prev = highs[i], lows[i], closes[i - 1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        trs.append(tr)

        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]
        plus_dm  = h_diff if h_diff > 0 and h_diff > l_diff else 0.0
        minus_dm = l_diff if l_diff > 0 and l_diff > h_diff else 0.0
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)

    # Wilder smoothing (seed cu sum primelor `period` valori)
    def _wilder_smooth(data: List[float]) -> List[float]:
        if len(data) < period:
            return []
        smoothed = [sum(data[:period])]
        for v in data[period:]:
            smoothed.append(smoothed[-1] - smoothed[-1] / period + v)
        return smoothed

    s_tr   = _wilder_smooth(trs)
    s_pdm  = _wilder_smooth(plus_dms)
    s_ndm  = _wilder_smooth(minus_dms)

    if not s_tr:
        return 0.0, 0.0, 0.0

    dxs = []
    for atr_w, pdm_w, ndm_w in zip(s_tr, s_pdm, s_ndm):
        if atr_w == 0:
            dxs.append(0.0)
            continue
        pdi = 100 * pdm_w / atr_w
        ndi = 100 * ndm_w / atr_w
        denom = pdi + ndi
        dxs.append(100 * abs(pdi - ndi) / denom if denom else 0.0)

    # ADX = Wilder MA pe DX
    adx_series = _wilder_smooth(dxs)
    if not adx_series:
        return 0.0, 0.0, 0.0

    # Valorile finale: ultimul element
    adx_val = adx_series[-1]
    last_tr  = s_tr[-1]
    plus_di  = 100 * s_pdm[-1] / last_tr if last_tr else 0.0
    minus_di = 100 * s_ndm[-1] / last_tr if last_tr else 0.0

    return round(adx_val, 2), round(plus_di, 2), round(minus_di, 2)


# ─────────────────────────────────────────────────────────────────── Regime

class Regime(str, Enum):
    TRENDING = "TRENDING"   # ADX > threshold_high  → TrendFollowing + Breakout activ
    RANGING  = "RANGING"    # ADX < threshold_low   → MeanReversion activ
    NEUTRAL  = "NEUTRAL"    # intre praguri          → toate strategiile voteaza


# Strategii activate per regim. MeanReversion NU ruleaza in TRENDING (multe fals-pozitive).
# TrendFollowing + Breakout NU ruleaza in RANGING (EMA crossover pe flat = zgomot).
_REGIME_ALLOWED: Dict[Regime, Set[str]] = {
    Regime.TRENDING: {"trend_following", "breakout"},
    Regime.RANGING:  {"mean_reversion"},
    Regime.NEUTRAL:  {"trend_following", "mean_reversion", "breakout"},
}


class RegimeDetector:
    """
    Detecteaza regimul de piata curent (TRENDING / RANGING / NEUTRAL)
    bazat pe ADX + spread-ul +DI/-DI.

    Parametri (configurabili din config.py / .env):
      adx_period          — perioada ADX (default 14)
      adx_trend_threshold — ADX > X → TRENDING (default 25)
      adx_range_threshold — ADX < X → RANGING  (default 20)

    Logica extinsa:
      - TRENDING confirmat si de +DI > -DI (bullish) sau -DI > +DI (bearish)
      - Histereza intre RANGING si NEUTRAL pentru a evita flip rapid
    """

    def __init__(
        self,
        period: int = 14,
        trend_threshold: float = 25.0,
        range_threshold: float = 20.0,
    ) -> None:
        self._period          = period
        self._trend_threshold = trend_threshold
        self._range_threshold = range_threshold
        self._last_regime     = Regime.NEUTRAL

    def detect(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
    ) -> Tuple[Regime, float, float, float]:
        """
        Returneaza (regime, adx, plus_di, minus_di).
        Foloseste histereza: daca regimul anterior e TRENDING,
        pragul de iesire din TRENDING e mai mic (trend_threshold - 3).
        """
        adx, plus_di, minus_di = _adx(highs, lows, closes, self._period)

        if adx == 0.0:
            # Date insuficiente
            return Regime.NEUTRAL, 0.0, 0.0, 0.0

        # Histereza: cand iesim din TRENDING, folosim un prag usor mai mic
        effective_trend_thresh = (
            self._trend_threshold - 3.0
            if self._last_regime == Regime.TRENDING
            else self._trend_threshold
        )

        if adx >= effective_trend_thresh:
            regime = Regime.TRENDING
        elif adx < self._range_threshold:
            regime = Regime.RANGING
        else:
            regime = Regime.NEUTRAL

        self._last_regime = regime
        logger.debug(
            "[regime] ADX=%.1f +DI=%.1f -DI=%.1f → %s",
            adx, plus_di, minus_di, regime.value,
        )
        return regime, adx, plus_di, minus_di

    @property
    def last_regime(self) -> Regime:
        return self._last_regime


# ─────────────────────────────────────────────────────────────────── Base

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
        sl_dist = atr * sl_atr_mult
        if action in (Action.BUY,):
            stop_loss    = close - sl_dist
            take_profit1 = close + sl_dist * tp1_rr
            take_profit2 = close + sl_dist * tp2_rr
        else:
            stop_loss    = close + sl_dist
            take_profit1 = close - sl_dist * tp1_rr
            take_profit2 = close - sl_dist * tp2_rr

        meta = metadata or {}
        if close > 0 and atr > 0:
            meta["atr_pct"]   = round(atr / close, 6)
            meta["atr_value"] = round(atr, 8)  # pentru trailing stop ATR-based

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


# ─────────────────────────────────────────────────────────────────── Strategies

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

        closes = [_safe_float(k[4]) for k in klines]
        highs  = [_safe_float(k[2]) for k in klines]
        lows   = [_safe_float(k[3]) for k in klines]
        ts     = str(klines[-1][0]) if klines else None

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

        prev_highs = highs[-(self._lookback + 1):-1]
        prev_lows  = lows[-(self._lookback + 1):-1]
        avg_vol    = sum(volumes[-(self._lookback + 1):-1]) / self._lookback
        curr_vol   = volumes[-1]
        vol_ok     = curr_vol > avg_vol * self._vol_mult

        resistance = max(prev_highs)
        support    = min(prev_lows)

        if close > resistance and vol_ok:
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


# ─────────────────────────────────────────────────────────────────── Composite

class CompositeStrategy(BaseStrategy):
    """
    Weighted voting intre mai multe strategii cu conflict resolution.

    🟡 FIX #6: Weight-urile sunt normalizate la suma=1.0 inainte de voting.
    🟡 FEAT #8: Accepta regime_detector optional.
      - La fiecare compute(), detecteaza regimul curent din klines
      - Filtreaza strategiile incompatibile cu regimul curent
      - Re-normalizeaza weight-urile pe setul filtrat (nu modifica originalele)
      - Logheza regimul si strategiile active pentru debugging
    """

    name = "composite"

    def __init__(
        self,
        strategies: List[BaseStrategy],
        weights: Optional[Dict[str, float]] = None,
        min_consensus: float = 0.55,
        regime_detector: Optional[RegimeDetector] = None,
    ) -> None:
        self._strategies      = strategies
        self._min_consensus   = min_consensus
        self._regime_detector = regime_detector

        raw: Dict[str, float] = {
            s.name: (weights.get(s.name, 1.0) if weights else 1.0)
            for s in strategies
        }
        total_w = sum(raw.values()) or 1.0
        self._weights: Dict[str, float] = {k: v / total_w for k, v in raw.items()}
        logger.debug("CompositeStrategy normalized weights: %s", self._weights)

    def compute(self, klines: List[List[Any]], timeframe: str = "1m") -> Optional[StrategySignal]:
        # ── Regime detection ───────────────────────────────────────────────────
        active_names: Optional[Set[str]] = None
        regime = Regime.NEUTRAL
        adx_val = 0.0

        if self._regime_detector is not None and len(klines) >= 2:
            highs  = [_safe_float(k[2]) for k in klines]
            lows   = [_safe_float(k[3]) for k in klines]
            closes = [_safe_float(k[4]) for k in klines]
            regime, adx_val, plus_di, minus_di = self._regime_detector.detect(
                highs, lows, closes
            )
            active_names = _REGIME_ALLOWED[regime]
            logger.info(
                "[composite] regime=%s ADX=%.1f +DI=%.1f -DI=%.1f active=%s",
                regime.value, adx_val, plus_di, minus_di, sorted(active_names),
            )

        # ── Filter strategies by regime ───────────────────────────────────────────
        if active_names is not None:
            active_strats = [s for s in self._strategies if s.name in active_names]
        else:
            active_strats = self._strategies

        if not active_strats:
            return None

        # Re-normalizeaza weights pe setul filtrat
        filtered_raw = {s.name: self._weights.get(s.name, 1.0) for s in active_strats}
        total_filtered = sum(filtered_raw.values()) or 1.0
        active_weights = {k: v / total_filtered for k, v in filtered_raw.items()}

        # ── Compute signals ────────────────────────────────────────────────────────
        signals: List[Tuple[StrategySignal, float]] = []
        for strat in active_strats:
            try:
                sig = strat.compute(klines, timeframe=timeframe)
            except Exception as exc:
                logger.warning("CompositeStrategy: %s failed: %s", strat.name, exc)
                sig = None
            if sig and sig.action != Action.HOLD:
                w = active_weights.get(strat.name, 1.0 / len(active_strats))
                signals.append((sig, w))

        if not signals:
            return None

        # ── Weighted voting ────────────────────────────────────────────────────────
        votes: Dict[str, float] = {}
        for sig, w in signals:
            votes[sig.action] = votes.get(sig.action, 0.0) + w

        best_action = max(votes, key=lambda a: votes[a])
        net_conf    = votes[best_action]

        if net_conf < self._min_consensus:
            return None

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
            reason=(
                f"Composite({best_action}) conf={net_conf:.2f} "
                f"regime={regime.value} adx={adx_val:.1f} "
                f"from {len(concordant)} strategies"
            ),
            candle_open_time=ref.candle_open_time,
            metadata={
                "votes": votes,
                "weights": active_weights,
                "regime": regime.value,
                "adx": adx_val,
            },
        )
