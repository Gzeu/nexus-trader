"""
binance_client.py – Async Binance HTTP client (Spot + Futures).

Features:
- Separate base URLs for Spot / Futures (testnet + mainnet)
- HMAC-SHA256 request signing (_signed_get / _signed_post helpers)
- Async httpx session reuse (async context manager)
- ping() for health checks
- get_spot_account() / get_futures_account() for full balance snapshots
- get_spot_ticker_price() / get_all_ticker_prices() for price cache
- All existing order / market data methods preserved
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
import structlog

from backend.config import get_settings

log = structlog.get_logger(__name__)

_SPOT_MAINNET     = "https://api.binance.com"
_SPOT_TESTNET     = "https://testnet.binance.vision"
_FUTURES_MAINNET  = "https://fapi.binance.com"
_FUTURES_TESTNET  = "https://testnet.binancefuture.com"


class BinanceClient:
    """Async Binance REST client supporting SPOT and FUTURES modes."""

    def __init__(self, mode: str = "SPOT"):
        s = get_settings()
        self._api_key = s.binance_api_key
        self._secret  = s.binance_api_secret
        self._mode    = mode.upper()
        self._testnet = s.testnet
        self._client: Optional[httpx.AsyncClient] = None

        if self._mode == "FUTURES":
            self._base         = _FUTURES_TESTNET if self._testnet else _FUTURES_MAINNET
            self._futures_base = self._base
        else:
            self._base         = _SPOT_TESTNET if self._testnet else _SPOT_MAINNET
            self._futures_base = _FUTURES_TESTNET if self._testnet else _FUTURES_MAINNET

    # ── Session lifecycle ───────────────────────────────────────────────────────────

    async def __aenter__(self) -> "BinanceClient":
        self._client = httpx.AsyncClient(
            base_url=self._base,
            headers={"X-MBX-APIKEY": self._api_key},
            timeout=10.0,
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()

    # ── Signing ───────────────────────────────────────────────────────────────────

    def _sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add timestamp + HMAC-SHA256 signature to params dict."""
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        sig = hmac.new(
            self._secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = sig
        return params

    # ── Low-level HTTP helpers ──────────────────────────────────────────────────────

    async def _get(
        self,
        path: str,
        params: Optional[Dict] = None,
        signed: bool = False,
        base_url: Optional[str] = None,
    ) -> Any:
        p = dict(params or {})
        if signed:
            p = self._sign(p)
        if base_url:
            async with httpx.AsyncClient(
                base_url=base_url,
                headers={"X-MBX-APIKEY": self._api_key},
                timeout=10.0,
            ) as c:
                r = await c.get(path, params=p)
        else:
            r = await self._client.get(path, params=p)
        r.raise_for_status()
        return r.json()

    async def _post(
        self,
        path: str,
        params: Optional[Dict] = None,
        signed: bool = True,
        base_url: Optional[str] = None,
    ) -> Any:
        p = dict(params or {})
        if signed:
            p = self._sign(p)
        if base_url:
            async with httpx.AsyncClient(
                base_url=base_url,
                headers={"X-MBX-APIKEY": self._api_key},
                timeout=10.0,
            ) as c:
                r = await c.post(path, params=p)
        else:
            r = await self._client.post(path, params=p)
        r.raise_for_status()
        return r.json()

    async def _delete(
        self,
        path: str,
        params: Optional[Dict] = None,
        signed: bool = True,
    ) -> Any:
        p = dict(params or {})
        if signed:
            p = self._sign(p)
        r = await self._client.delete(path, params=p)
        r.raise_for_status()
        return r.json()

    # Convenience signed wrappers
    async def _signed_get(
        self, path: str, params: Optional[Dict] = None, base_url: Optional[str] = None
    ) -> Any:
        return await self._get(path, params, signed=True, base_url=base_url)

    async def _signed_post(
        self, path: str, params: Optional[Dict] = None, base_url: Optional[str] = None
    ) -> Any:
        return await self._post(path, params, signed=True, base_url=base_url)

    # ── Connectivity ──────────────────────────────────────────────────────────────

    async def ping(self) -> bool:
        """GET /api/v3/ping — returns True if Binance is reachable."""
        try:
            await self._get("/api/v3/ping")
            return True
        except Exception:
            return False

    # ── Market Data ──────────────────────────────────────────────────────────────

    async def get_exchange_info(self, symbol: Optional[str] = None) -> Dict:
        """Fetch symbol filters (stepSize, tickSize, minNotional)."""
        params = {"symbol": symbol} if symbol else {}
        path = "/fapi/v1/exchangeInfo" if self._mode == "FUTURES" else "/api/v3/exchangeInfo"
        return await self._get(path, params)

    async def get_klines(self, symbol: str, interval: str, limit: int = 200) -> List[List]:
        """Fetch OHLCV candlesticks."""
        path = "/fapi/v1/klines" if self._mode == "FUTURES" else "/api/v3/klines"
        return await self._get(path, {"symbol": symbol, "interval": interval, "limit": limit})

    async def get_ticker(self, symbol: str) -> Dict:
        """24hr ticker price change statistics."""
        path = "/fapi/v1/ticker/24hr" if self._mode == "FUTURES" else "/api/v3/ticker/24hr"
        return await self._get(path, {"symbol": symbol})

    async def get_book_ticker(self, symbol: str) -> Dict:
        """Best bid/ask price and quantity."""
        path = "/fapi/v1/ticker/bookTicker" if self._mode == "FUTURES" else "/api/v3/ticker/bookTicker"
        return await self._get(path, {"symbol": symbol})

    async def get_spot_ticker_price(self, symbol: str) -> float:
        """GET /api/v3/ticker/price — current price for one symbol."""
        data = await self._get("/api/v3/ticker/price", {"symbol": symbol})
        return float(data["price"])

    async def get_all_ticker_prices(self) -> Dict[str, float]:
        """GET /api/v3/ticker/price — returns {symbol: price} for all pairs."""
        data = await self._get("/api/v3/ticker/price")
        return {item["symbol"]: float(item["price"]) for item in data}

    # ── Account ─────────────────────────────────────────────────────────────────────

    async def get_account(self) -> Dict:
        """Fetch account balances (Spot) or account info (Futures).
        Used by reconcile() — returns raw Binance response."""
        if self._mode == "FUTURES":
            return await self._get("/fapi/v2/account", signed=True)
        return await self._get("/api/v3/account", signed=True)

    async def get_spot_account(self) -> Dict:
        """GET /api/v3/account — full spot balances snapshot (always Spot base URL)."""
        return await self._signed_get("/api/v3/account")

    async def get_futures_account(self) -> Dict:
        """GET /fapi/v2/account — full futures account snapshot."""
        return await self._signed_get("/fapi/v2/account", base_url=self._futures_base)

    async def get_positions(self) -> List[Dict]:
        """Futures only: fetch all position risk entries."""
        return await self._get("/fapi/v2/positionRisk", signed=True)

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Fetch open orders, optionally filtered by symbol."""
        params = {"symbol": symbol} if symbol else {}
        path = "/fapi/v1/openOrders" if self._mode == "FUTURES" else "/api/v3/openOrders"
        return await self._get(path, params, signed=True)

    # ── Order Placement ──────────────────────────────────────────────────────────────

    async def place_market_order(
        self, symbol: str, side: str, quantity: float, reduce_only: bool = False
    ) -> Dict:
        """Place a MARKET order."""
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": quantity,
        }
        if self._mode == "FUTURES" and reduce_only:
            params["reduceOnly"] = "true"
        path = "/fapi/v1/order" if self._mode == "FUTURES" else "/api/v3/order"
        log.info("binance_market_order", **params)
        return await self._post(path, params)

    async def place_limit_order(
        self, symbol: str, side: str, quantity: float, price: float,
        time_in_force: str = "GTC",
    ) -> Dict:
        """Place a LIMIT order."""
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "LIMIT",
            "quantity": quantity,
            "price": price,
            "timeInForce": time_in_force,
        }
        path = "/fapi/v1/order" if self._mode == "FUTURES" else "/api/v3/order"
        log.info("binance_limit_order", **params)
        return await self._post(path, params)

    async def place_oco_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        stop_price: float,
        stop_limit_price: float,
    ) -> Dict:
        """Place an OCO order (Spot only). Futures use separate SL/TP orders."""
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "quantity": quantity,
            "price": price,
            "stopPrice": stop_price,
            "stopLimitPrice": stop_limit_price,
            "stopLimitTimeInForce": "GTC",
        }
        log.info("binance_oco_order", symbol=symbol, side=side)
        return await self._post("/api/v3/orderList/oco", params)

    async def place_stop_market_order(
        self, symbol: str, side: str, quantity: float, stop_price: float,
        reduce_only: bool = True,
    ) -> Dict:
        """Futures: STOP_MARKET order for stop-loss."""
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "STOP_MARKET",
            "quantity": quantity,
            "stopPrice": stop_price,
            "reduceOnly": str(reduce_only).lower(),
        }
        return await self._post("/fapi/v1/order", params)

    async def place_take_profit_market(
        self, symbol: str, side: str, quantity: float, stop_price: float,
        reduce_only: bool = True,
    ) -> Dict:
        """Futures: TAKE_PROFIT_MARKET order."""
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "TAKE_PROFIT_MARKET",
            "quantity": quantity,
            "stopPrice": stop_price,
            "reduceOnly": str(reduce_only).lower(),
        }
        return await self._post("/fapi/v1/order", params)

    # ── Order Management ──────────────────────────────────────────────────────────────

    async def cancel_order(self, symbol: str, order_id: int) -> Dict:
        """Cancel a specific order by ID."""
        params = {"symbol": symbol, "orderId": order_id}
        path = "/fapi/v1/order" if self._mode == "FUTURES" else "/api/v3/order"
        return await self._delete(path, params)

    async def cancel_all_orders(self, symbol: str) -> Dict:
        """Cancel all open orders for a symbol."""
        params = {"symbol": symbol} if symbol else {}
        path = "/fapi/v1/allOpenOrders" if self._mode == "FUTURES" else "/api/v3/openOrders"
        return await self._delete(path, params)

    async def set_leverage(self, symbol: str, leverage: int) -> Dict:
        """Futures only: set leverage for a symbol."""
        return await self._post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})

    async def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> Dict:
        """Futures only: ISOLATED | CROSSED."""
        return await self._post("/fapi/v1/marginType", {"symbol": symbol, "marginType": margin_type})
