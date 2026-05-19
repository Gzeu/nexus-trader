"""
OHLCVProvider — fetches and caches OHLCV candles from Binance.
Used by StrategyEngine to supply numpy arrays to each strategy.

Features:
- LRU-style in-memory cache per (symbol, interval)
- Deduplicated requests via asyncio locks
- Returns np.ndarray shape (N, 6): [ts, open, high, low, close, volume]
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Cache TTL per timeframe (seconds)
_TTL: dict[str, float] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}
_DEFAULT_TTL = 300
_LIMIT = 200  # candles per request


class OHLCVProvider:
    """Async OHLCV cache with per-key locks to prevent thundering herd."""

    def __init__(self, client) -> None:
        self._client = client
        # {(symbol, interval): (timestamp_fetched, np.ndarray)}
        self._cache: dict[tuple[str, str], tuple[float, np.ndarray]] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def get(
        self,
        symbol: str,
        interval: str = "5m",
        limit: int = _LIMIT,
        force_refresh: bool = False,
    ) -> np.ndarray:
        """
        Return OHLCV array for symbol/interval.
        Columns: [open_time_ms, open, high, low, close, volume]
        """
        key = (symbol, interval)
        ttl = _TTL.get(interval, _DEFAULT_TTL)

        if not force_refresh:
            cached = self._cache.get(key)
            if cached and (time.monotonic() - cached[0]) < ttl:
                return cached[1]

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Double-check after acquiring lock
            cached = self._cache.get(key)
            if not force_refresh and cached and (time.monotonic() - cached[0]) < ttl:
                return cached[1]

            arr = await self._fetch(symbol, interval, limit)
            self._cache[key] = (time.monotonic(), arr)
            return arr

    async def invalidate(self, symbol: str, interval: Optional[str] = None) -> None:
        """Remove cache entries for symbol (optionally specific interval)."""
        keys = (
            [(symbol, interval)]
            if interval
            else [k for k in self._cache if k[0] == symbol]
        )
        for k in keys:
            self._cache.pop(k, None)

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    async def _fetch(self, symbol: str, interval: str, limit: int) -> np.ndarray:
        try:
            raw = await self._client.get_klines(symbol, interval, limit=limit)
            # Binance kline: [open_time, open, high, low, close, volume, ...]
            arr = np.array(
                [[float(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])] for c in raw],
                dtype=np.float64,
            )
            logger.debug("OHLCVProvider fetched %s %s — %d candles", symbol, interval, len(arr))
            return arr
        except Exception as exc:
            logger.error("OHLCVProvider._fetch %s %s failed: %s", symbol, interval, exc)
            return np.empty((0, 6), dtype=np.float64)
