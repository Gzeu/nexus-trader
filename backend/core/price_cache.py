"""
PriceCache — in-memory USDT price store cu refresh automat.

Utilizare:
    cache = PriceCache(binance_client)
    await cache.start()          # porneste loop-ul de refresh
    price = cache.get("BTC")     # 0.0 daca nu e inca gata
    await cache.wait_ready()     # blocheaza pana la primul fetch reusit
    await cache.stop()
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from backend.binance.binance_client import BinanceClient

logger = logging.getLogger(__name__)

# Active stablecoins returnate direct 1.0 (fara request)
_STABLECOINS = frozenset({"USDT", "BUSD", "USDC", "DAI", "TUSD", "FDUSD"})


class PriceCache:
    """Thread-safe in-memory cache pentru preturile USDT ale tuturor simbolurilor Binance."""

    def __init__(self, client: "BinanceClient", refresh_interval: float = 30.0) -> None:
        self._client = client
        self._interval = refresh_interval
        self._prices: Dict[str, float] = {}
        self._ready = asyncio.Event()
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    # ------------------------------------------------------------------ public

    async def start(self) -> None:
        """Porneste task-ul de refresh in background."""
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._refresh_loop(), name="price_cache_refresh")
        logger.info("PriceCache started (interval=%ss)", self._interval)

    async def stop(self) -> None:
        """Opreste task-ul de refresh."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PriceCache stopped")

    async def wait_ready(self, timeout: float = 15.0) -> bool:
        """Asteapta pana la primul fetch reusit. Returneaza False la timeout."""
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning("PriceCache wait_ready timeout after %ss", timeout)
            return False

    def get(self, asset: str, default: float = 0.0) -> float:
        """Returneaza pretul USDT al unui asset (ex: 'BTC' sau 'BTCUSDT')."""
        if asset in _STABLECOINS:
            return 1.0
        # accepta atat 'BTC' cat si 'BTCUSDT'
        key = asset if asset.endswith("USDT") else f"{asset}USDT"
        return self._prices.get(key, default)

    def usdt_value(self, asset: str, amount: float) -> float:
        """Calculeaza valoarea USDT a unui asset."""
        if amount == 0:
            return 0.0
        price = self.get(asset)
        return amount * price

    def snapshot(self) -> Dict[str, float]:
        """Returneaza o copie a intregului cache (pentru debug/logging)."""
        return dict(self._prices)

    @property
    def is_ready(self) -> bool:
        return self._ready.is_set()

    # ----------------------------------------------------------------- private

    async def _refresh_loop(self) -> None:
        """Loop infinit: fetch -> sleep -> repeat."""
        while True:
            try:
                prices = await self._client.get_all_ticker_prices()
                self._prices = prices
                if not self._ready.is_set():
                    self._ready.set()
                    logger.info("PriceCache ready — %d symbols loaded", len(prices))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("PriceCache refresh failed: %s", exc)
            await asyncio.sleep(self._interval)
