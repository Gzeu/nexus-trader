"""
New methods to append to BinanceClient in backend/binance/binance_client.py.
Copy-paste each method into the class body.
"""
from __future__ import annotations


async def get_spot_account(self) -> dict:
    """GET /api/v3/account — full spot balances snapshot."""
    return await self._signed_get("/api/v3/account")


async def get_futures_account(self) -> dict:
    """GET /fapi/v2/account — full futures account snapshot."""
    return await self._signed_get(
        "/fapi/v2/account",
        base_url=self._futures_base,
    )


async def get_spot_ticker_price(self, symbol: str) -> float:
    """GET /api/v3/ticker/price — current mark price for a symbol."""
    data = await self._get("/api/v3/ticker/price", params={"symbol": symbol})
    return float(data["price"])


async def get_all_ticker_prices(self) -> dict[str, float]:
    """GET /api/v3/ticker/price (all) — returns {symbol: price}."""
    data = await self._get("/api/v3/ticker/price")
    return {item["symbol"]: float(item["price"]) for item in data}
