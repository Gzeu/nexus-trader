"""
PriceCache — async in-memory price cache cu refresh periodic din Binance.
Înlocuiește placeholder-ul _usdt_value() din models_extra.py.

Usage:
    cache = PriceCache(client)
    await cache.start()          # pornește refresh task
    price = cache.get("BTC")    # 0.0 dacă necunoscut
    await cache.stop()
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Simboluri stabile USDT — folosite ca fallback known prices
_STABLECOINS = {"USDT", "BUSD", "USDC", "TUSD", "DAI", "FDUSD"}


class PriceCache:
    """Thread-safe async price cache cu auto-refresh."""

    def __init__(self, client, refresh_interval: float = 30.0) -> None:
        self._client = client
        self._interval = refresh_interval
        self._prices: dict[str, float] = {}
        self._task: Optional[asyncio.Task] = None
        self._ready = asyncio.Event()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """Start background refresh loop. Awaits first fetch before returning."""
        await self._fetch()
        self._ready.set()
        self._task = asyncio.create_task(self._loop(), name="price-cache-refresh")
        logger.info("PriceCache started (%d symbols)", len(self._prices))

    async def stop(self) -> None:
        """Cancel the background task gracefully."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PriceCache stopped")

    def get(self, asset: str, fallback: float = 0.0) -> float:
        """Return USDT price for asset. Stablecoins always return 1.0."""
        if asset in _STABLECOINS:
            return 1.0
        return self._prices.get(f"{asset}USDT", self._prices.get(asset, fallback))

    def usdt_value(self, asset: str, amount: float) -> float:
        """Convert asset amount to USDT equivalent."""
        return amount * self.get(asset, 0.0)

    async def wait_ready(self, timeout: float = 10.0) -> bool:
        """Wait until the cache has been populated at least once."""
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def snapshot(self) -> dict[str, float]:
        """Return a copy of the current price map."""
        return dict(self._prices)

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self._fetch()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("PriceCache refresh error: %s", exc)

    async def _fetch(self) -> None:
        try:
            prices = await self._client.get_all_ticker_prices()
            self._prices = prices
        except Exception as exc:
            logger.error("PriceCache._fetch failed: %s", exc)
