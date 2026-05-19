"""
ohlcv_provider.py – Async OHLCV fetcher with in-memory TTL cache.

Provides a single OHLCVProvider class that:
- Fetches klines from Binance Spot or Futures
- Caches results for 60 seconds per (symbol, timeframe, market_mode)
- Validates minimum candle count before returning
- Accepts a BinanceClient injected at construction

Usage:
    provider = OHLCVProvider(spot_client=spot, futures_client=futures)
    ohlcv = await provider.get_ohlcv("BTCUSDT", "15m", market_mode=MarketMode.SPOT)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import structlog

from backend.config import get_settings
from backend.models import MarketMode
from backend.core.strategy_engine import OHLCV

log = structlog.get_logger(__name__)
settings = get_settings()

# Minimum candle counts
MIN_CANDLES_HARD = 20    # ValueError raised below this
MIN_CANDLES_WARN = 50    # Warning logged below this

# Supported timeframe aliases (Binance accepts these directly)
VALID_TIMEFRAMES = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"}

# User-friendly aliases → Binance format
TIMEFRAME_MAP: Dict[str, str] = {
    "1min": "1m",
    "5min": "5m",
    "15min": "15m",
    "30min": "30m",
    "1hour": "1h",
    "4hour": "4h",
    "1day": "1d",
}


class _CacheEntry:
    __slots__ = ("ohlcv", "expires_at")

    def __init__(self, ohlcv: OHLCV, ttl_seconds: int = 60):
        self.ohlcv      = ohlcv
        self.expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)

    @property
    def is_fresh(self) -> bool:
        return datetime.utcnow() < self.expires_at


class OHLCVProvider:
    """
    Async OHLCV provider with 60-second TTL cache.

    Args:
        spot_client:    Binance Spot client (required)
        futures_client: Binance Futures client (optional)
        cache_ttl:      Cache TTL in seconds (default 60)
    """

    def __init__(self, spot_client, futures_client=None, cache_ttl: int = 60):
        self._spot     = spot_client
        self._futures  = futures_client
        self._cache:   Dict[Tuple[str, str, str], _CacheEntry] = {}
        self._ttl      = cache_ttl
        self._lock     = asyncio.Lock()

    async def get_ohlcv(
        self,
        symbol:      str,
        timeframe:   str,
        limit:       int = 200,
        market_mode: MarketMode = MarketMode.SPOT,
    ) -> OHLCV:
        """
        Fetch OHLCV data, serving from cache when fresh.

        Args:
            symbol:      Trading pair, e.g. "BTCUSDT"
            timeframe:   Interval string, e.g. "15m", "1h"
            limit:       Number of candles to fetch (default 200)
            market_mode: SPOT or FUTURES

        Returns:
            OHLCV wrapper with confirmed-close accessors

        Raises:
            ValueError: If fewer than MIN_CANDLES_HARD candles returned
        """
        tf = self._normalize_timeframe(timeframe)
        cache_key = (symbol, tf, market_mode.value if hasattr(market_mode, "value") else str(market_mode))

        async with self._lock:
            entry = self._cache.get(cache_key)
            if entry and entry.is_fresh:
                log.debug("ohlcv_cache_hit", symbol=symbol, tf=tf)
                return entry.ohlcv

        # Fetch outside lock to allow concurrent fetches on different symbols
        ohlcv = await self._fetch(symbol, tf, limit, market_mode)

        async with self._lock:
            self._cache[cache_key] = _CacheEntry(ohlcv, ttl_seconds=self._ttl)

        return ohlcv

    async def invalidate(self, symbol: str, timeframe: str, market_mode: MarketMode) -> None:
        """Force cache invalidation for a specific key (e.g. after a fill)."""
        tf = self._normalize_timeframe(timeframe)
        key = (symbol, tf, market_mode.value if hasattr(market_mode, "value") else str(market_mode))
        async with self._lock:
            self._cache.pop(key, None)
        log.debug("ohlcv_cache_invalidated", symbol=symbol, tf=tf)

    def cache_size(self) -> int:
        """Number of cached OHLCV entries."""
        return len(self._cache)

    # ── Private ──────────────────────────────────────────────────────────────

    async def _fetch(
        self,
        symbol:      str,
        timeframe:   str,
        limit:       int,
        market_mode: MarketMode,
    ) -> OHLCV:
        """Fetch raw klines from exchange and wrap in OHLCV."""
        client = self._client(market_mode)
        try:
            klines = await client.get_klines(symbol, timeframe, limit=limit)
        except Exception as exc:
            log.error("ohlcv_fetch_failed", symbol=symbol, tf=timeframe, error=str(exc))
            raise

        count = len(klines) if klines else 0

        if count < MIN_CANDLES_HARD:
            raise ValueError(
                f"Insufficient candles for {symbol}/{timeframe}: "
                f"got {count}, need at least {MIN_CANDLES_HARD}"
            )

        if count < MIN_CANDLES_WARN:
            log.warning(
                "ohlcv_low_candle_count",
                symbol=symbol,
                tf=timeframe,
                count=count,
                warn_threshold=MIN_CANDLES_WARN,
            )

        log.debug("ohlcv_fetched", symbol=symbol, tf=timeframe, candles=count)
        return OHLCV(klines)

    def _client(self, market_mode: MarketMode):
        mode = market_mode.value if hasattr(market_mode, "value") else str(market_mode)
        if mode == "FUTURES" and self._futures:
            return self._futures
        return self._spot

    @staticmethod
    def _normalize_timeframe(tf: str) -> str:
        """Normalize timeframe string to Binance format."""
        normalized = TIMEFRAME_MAP.get(tf, tf)
        if normalized not in VALID_TIMEFRAMES:
            raise ValueError(
                f"Invalid timeframe: '{tf}'. Valid options: {sorted(VALID_TIMEFRAMES)}"
            )
        return normalized
