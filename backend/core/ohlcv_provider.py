"""
ohlcv_provider.py – Async OHLCV provider with 60-second in-memory cache.

Completion 1: required by automation_engine to feed strategies.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from loguru import logger

from backend.config import get_settings
from backend.models import MarketMode

TF_MAP: Dict[str, str] = {
    "1m":  "1m",
    "5m":  "5m",
    "15m": "15m",
    "1h":  "1h",
    "4h":  "4h",
    "1d":  "1d",
}

MIN_CANDLES_HARD = 20   # raise ValueError below this
MIN_CANDLES_WARN = 50   # log warning below this


@dataclass
class OHLCV:
    """Container for OHLCV data arrays (same length)."""
    opens:      List[float]
    highs:      List[float]
    lows:       List[float]
    closes:     List[float]
    volumes:    List[float]
    timestamps: List[int]   # milliseconds UTC

    def __len__(self) -> int:
        return len(self.closes)


@dataclass
class _CacheEntry:
    ohlcv:      OHLCV
    fetched_at: float   # time.monotonic()


class OHLCVProvider:
    """
    Fetches OHLCV candles from Binance Spot or Futures REST API.
    Results are cached in-memory for 60 seconds per (symbol, timeframe, mode).
    """

    CACHE_TTL_SECONDS = 60

    def __init__(self, binance_client: "BinanceClient") -> None:  # type: ignore[name-defined]
        self._client = binance_client
        self._cache: Dict[Tuple[str, str, str], _CacheEntry] = {}
        self._lock = asyncio.Lock()

    # ─── Public API ──────────────────────────────────────────────────────────

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        market_mode: Optional[MarketMode] = None,
    ) -> OHLCV:
        """
        Return OHLCV for (symbol, timeframe, mode).
        Uses cache; fetches from Binance if stale or missing.

        Raises:
            ValueError: if the exchange returns fewer than MIN_CANDLES_HARD candles.
        """
        settings = get_settings()
        mode = market_mode or MarketMode(settings.market_mode)
        tf = TF_MAP.get(timeframe, timeframe)
        cache_key = (symbol.upper(), tf, mode.value)

        async with self._lock:
            entry = self._cache.get(cache_key)
            if entry and (time.monotonic() - entry.fetched_at) < self.CACHE_TTL_SECONDS:
                logger.debug("ohlcv_cache_hit", symbol=symbol, tf=tf, mode=mode.value)
                return entry.ohlcv

        # Cache miss — fetch from Binance
        logger.debug("ohlcv_fetch", symbol=symbol, tf=tf, mode=mode.value, limit=limit)
        raw = await self._client.get_klines(
            symbol=symbol.upper(),
            interval=tf,
            limit=limit,
            futures=(mode == MarketMode.FUTURES),
        )

        ohlcv = self._parse(raw)
        n = len(ohlcv)

        if n < MIN_CANDLES_HARD:
            raise ValueError(
                f"Insufficient candles for {symbol} {tf}: got {n}, need {MIN_CANDLES_HARD}"
            )
        if n < MIN_CANDLES_WARN:
            logger.warning(
                "ohlcv_low_candle_count",
                symbol=symbol,
                tf=tf,
                count=n,
                warn_threshold=MIN_CANDLES_WARN,
            )

        async with self._lock:
            self._cache[cache_key] = _CacheEntry(ohlcv=ohlcv, fetched_at=time.monotonic())

        return ohlcv

    def invalidate(self, symbol: str, timeframe: str, mode: MarketMode) -> None:
        """Force-expire a cache entry (e.g. after a trade fill)."""
        tf = TF_MAP.get(timeframe, timeframe)
        self._cache.pop((symbol.upper(), tf, mode.value), None)

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._cache.clear()

    # ─── Internal ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse(raw: List[List]) -> OHLCV:
        """
        Parse Binance kline response.
        Each element: [open_time, open, high, low, close, volume, ...]
        """
        timestamps, opens, highs, lows, closes, volumes = [], [], [], [], [], []
        for k in raw:
            timestamps.append(int(k[0]))
            opens.append(float(k[1]))
            highs.append(float(k[2]))
            lows.append(float(k[3]))
            closes.append(float(k[4]))
            volumes.append(float(k[5]))
        return OHLCV(
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            volumes=volumes,
            timestamps=timestamps,
        )
