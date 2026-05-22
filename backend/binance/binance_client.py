"""
BinanceClient — async HTTP client (Spot + Futures, Testnet/Mainnet).

CHANGELOG:
  🔴 FIX #1 : get_open_orders() accepta futures=bool — rutare corecta Spot vs Futures.
  🔴 FIX #9 : cancel_all_orders() accepta futures=bool — anuleaza si ordinele Futures.
  🟡 FIX #7 : hmac.new() cu keyword args (Python 3.13+ safe, fara deprecation warnings).
  🟢 FEAT   : listenKey management complet (create / keepalive / delete / background task).
               Compatibil cu BinanceWebSocket.user_data_stream() din binance_ws.py.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

from backend.config import get_settings

logger = logging.getLogger(__name__)

_SPOT_LIVE = "https://api.binance.com"
_SPOT_TEST = "https://testnet.binance.vision"
_FUTS_LIVE = "https://fapi.binance.com"
_FUTS_TEST = "https://testnet.binancefuture.com"

# listenKey expira dupa 60 min; trimitem keepalive la fiecare 30 min
_LISTEN_KEY_KEEPALIVE_INTERVAL = 30 * 60


class BinanceClient:
    """
    Client async pentru Binance REST API.
    Suporta Spot + Futures, Testnet + Mainnet, DRY_RUN.
    """

    def __init__(self) -> None:
        cfg = get_settings()
        self._api_key      = cfg.binance_api_key
        self._api_secret   = cfg.binance_api_secret
        self._testnet      = cfg.testnet
        self._dry_run      = cfg.dry_run

        self._spot_base    = _SPOT_TEST if self._testnet else _SPOT_LIVE
        self._futures_base = _FUTS_TEST if self._testnet else _FUTS_LIVE

        self._client: Optional[httpx.AsyncClient] = None
        self._keepalive_task: Optional[asyncio.Task] = None

    # ----------------------------------------------------------------- lifecycle

    async def __aenter__(self) -> "BinanceClient":
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            headers={"X-MBX-APIKEY": self._api_key},
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            headers={"X-MBX-APIKEY": self._api_key},
        )

    async def stop(self) -> None:
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()

    # ----------------------------------------------------------------- signing

    def _sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        params["timestamp"] = int(time.time() * 1000)
        query = urllib.parse.urlencode(params)
        # 🟡 FIX #7: keyword args pentru Python 3.13+ compatibilitate
        sig = hmac.new(
            key=self._api_secret.encode(),
            msg=query.encode(),
            digestmod=hashlib.sha256,
        ).hexdigest()
        params["signature"] = sig
        return params

    # ----------------------------------------------------------------- low-level

    async def _get(
        self, path: str, params: Optional[Dict] = None, base_url: Optional[str] = None
    ) -> Any:
        url = (base_url or self._spot_base) + path
        r = await self._client.get(url, params=params or {})  # type: ignore
        r.raise_for_status()
        return r.json()

    async def _signed_get(
        self, path: str, params: Optional[Dict] = None, base_url: Optional[str] = None
    ) -> Any:
        p = self._sign(params or {})
        return await self._get(path, p, base_url)

    async def _signed_post(
        self, path: str, data: Optional[Dict] = None, base_url: Optional[str] = None
    ) -> Any:
        url = (base_url or self._spot_base) + path
        body = self._sign(data or {})
        r = await self._client.post(url, data=body)  # type: ignore
        r.raise_for_status()
        return r.json()

    async def _signed_delete(
        self, path: str, params: Optional[Dict] = None, base_url: Optional[str] = None
    ) -> Any:
        url = (base_url or self._spot_base) + path
        p = self._sign(params or {})
        r = await self._client.delete(url, params=p)  # type: ignore
        r.raise_for_status()
        return r.json()

    # ----------------------------------------------------------------- market data

    async def get_exchange_info(self, symbol: Optional[str] = None) -> Dict:
        """GET /api/v3/exchangeInfo — filtere lot size, tick size, min notional."""
        params = {"symbol": symbol} if symbol else {}
        return await self._get("/api/v3/exchangeInfo", params)

    async def get_klines(
        self,
        symbol: str,
        interval: str = "5m",
        limit: int = 200,
    ) -> List[List]:
        """GET /api/v3/klines — OHLCV candlestick data."""
        return await self._get(
            "/api/v3/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
        )

    async def get_spot_ticker_price(self, symbol: str) -> float:
        """GET /api/v3/ticker/price — single symbol."""
        data = await self._get("/api/v3/ticker/price", {"symbol": symbol})
        return float(data["price"])

    async def get_all_ticker_prices(self) -> Dict[str, float]:
        """GET /api/v3/ticker/price (all) — returneaza {symbol: price}."""
        data = await self._get("/api/v3/ticker/price")
        return {item["symbol"]: float(item["price"]) for item in data}

    async def get_futures_mark_price(self, symbol: str) -> float:
        """GET /fapi/v1/premiumIndex — mark price pentru futures."""
        data = await self._get(
            "/fapi/v1/premiumIndex",
            {"symbol": symbol},
            base_url=self._futures_base,
        )
        return float(data["markPrice"])

    # ----------------------------------------------------------------- account

    async def get_spot_account(self) -> Dict:
        """GET /api/v3/account — full spot balances snapshot."""
        return await self._signed_get("/api/v3/account")

    async def get_futures_account(self) -> Dict:
        """GET /fapi/v2/account — full futures account snapshot."""
        return await self._signed_get("/fapi/v2/account", base_url=self._futures_base)

    async def get_positions(self) -> List[Dict]:
        """GET /fapi/v2/positionRisk — pozitii futures deschise."""
        return await self._signed_get("/fapi/v2/positionRisk", base_url=self._futures_base)

    async def get_open_orders(
        self, symbol: Optional[str] = None, futures: bool = False
    ) -> List[Dict]:
        """
        🔴 FIX #1: Rutare corecta Spot vs Futures.

        Args:
            symbol: Filtreaza dupa simbol (optional).
            futures: Daca True, apeleaza /fapi/v1/openOrders (Futures).
                     Daca False (default), apeleaza /api/v3/openOrders (Spot).

        Returns:
            Lista de ordine deschise de la exchange.
        """
        params = {"symbol": symbol} if symbol else {}
        if futures:
            return await self._signed_get(
                "/fapi/v1/openOrders", params, base_url=self._futures_base
            )
        return await self._signed_get("/api/v3/openOrders", params)

    # ----------------------------------------------------------------- orders

    async def place_market_order(
        self, symbol: str, side: str, quantity: float
    ) -> Dict:
        """POST /api/v3/order — market order spot."""
        if self._dry_run:
            logger.info("[DRY_RUN] MARKET %s %s qty=%s", side, symbol, quantity)
            return {"orderId": "DRY_RUN", "status": "FILLED", "symbol": symbol}
        return await self._signed_post(
            "/api/v3/order",
            {"symbol": symbol, "side": side, "type": "MARKET", "quantity": quantity},
        )

    async def place_limit_order(
        self, symbol: str, side: str, quantity: float, price: float
    ) -> Dict:
        """POST /api/v3/order — limit order spot (GTC)."""
        if self._dry_run:
            logger.info("[DRY_RUN] LIMIT %s %s qty=%s price=%s", side, symbol, quantity, price)
            return {"orderId": "DRY_RUN", "status": "NEW", "symbol": symbol}
        return await self._signed_post(
            "/api/v3/order",
            {
                "symbol": symbol,
                "side": side,
                "type": "LIMIT",
                "timeInForce": "GTC",
                "quantity": quantity,
                "price": price,
            },
        )

    async def place_oco_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        stop_price: float,
        stop_limit_price: float,
    ) -> Dict:
        """POST /api/v3/order/oco — bracket order (TP + SL)."""
        if self._dry_run:
            logger.info("[DRY_RUN] OCO %s %s qty=%s tp=%s sl=%s", side, symbol, quantity, price, stop_price)
            return {"orderListId": "DRY_RUN", "symbol": symbol}
        return await self._signed_post(
            "/api/v3/order/oco",
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "stopPrice": stop_price,
                "stopLimitPrice": stop_limit_price,
                "stopLimitTimeInForce": "GTC",
            },
        )

    async def cancel_order(self, symbol: str, order_id: str) -> Dict:
        """DELETE /api/v3/order."""
        if self._dry_run:
            return {"orderId": order_id, "status": "CANCELED"}
        return await self._signed_delete(
            "/api/v3/order", {"symbol": symbol, "orderId": order_id}
        )

    async def cancel_all_orders(
        self, symbol: str, futures: bool = False
    ) -> List[Dict]:
        """
        🔴 FIX #9: Suport complet Spot + Futures.

        Args:
            symbol: Simbolul pentru care se anuleaza ordinele.
            futures: Daca True, apeleaza /fapi/v1/allOpenOrders (Futures).
                     Daca False (default), apeleaza /api/v3/openOrders (Spot DELETE).

        Returns:
            Lista ordinelor anulate (poate fi goala in DRY_RUN).
        """
        if self._dry_run:
            logger.info("[DRY_RUN] cancel_all_orders %s (futures=%s)", symbol, futures)
            return []
        if futures:
            return await self._signed_delete(
                "/fapi/v1/allOpenOrders",
                {"symbol": symbol},
                base_url=self._futures_base,
            )
        return await self._signed_delete("/api/v3/openOrders", {"symbol": symbol})

    async def set_leverage(
        self, symbol: str, leverage: int
    ) -> Dict:
        """POST /fapi/v1/leverage — seteaza leverage futures."""
        if self._dry_run:
            return {"leverage": leverage, "symbol": symbol}
        return await self._signed_post(
            "/fapi/v1/leverage",
            {"symbol": symbol, "leverage": leverage},
            base_url=self._futures_base,
        )

    async def place_futures_market_order(
        self, symbol: str, side: str, quantity: float
    ) -> Dict:
        """POST /fapi/v1/order — market order futures."""
        if self._dry_run:
            logger.info("[DRY_RUN] FUTURES MARKET %s %s qty=%s", side, symbol, quantity)
            return {"orderId": "DRY_RUN", "status": "FILLED", "symbol": symbol}
        return await self._signed_post(
            "/fapi/v1/order",
            {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": quantity,
                "positionSide": "BOTH",
            },
            base_url=self._futures_base,
        )

    # ----------------------------------------------------------------- listenKey (User Data Stream)

    async def create_listen_key(self, futures: bool = False) -> str:
        """
        Creeaza un listenKey pentru WebSocket User Data Stream.

        Spot:    POST /api/v3/userDataStream  — NU necesita semnatura HMAC
        Futures: POST /fapi/v1/listenKey      — necesita header X-MBX-APIKEY

        Args:
            futures: Daca True, creeaza listenKey pentru Futures stream.

        Returns:
            listenKey string (valabil 60 minute; mentine-l activ cu keepalive_listen_key).

        Exemplu de utilizare cu BinanceWebSocket:
            listen_key = await client.create_listen_key()
            await client.start_listen_key_keepalive(listen_key)
            await ws.user_data_stream(listen_key, my_callback)
        """
        if futures:
            url = self._futures_base + "/fapi/v1/listenKey"
            r = await self._client.post(url)  # type: ignore
        else:
            url = self._spot_base + "/api/v3/userDataStream"
            r = await self._client.post(url)  # type: ignore
        r.raise_for_status()
        data = r.json()
        listen_key: str = data["listenKey"]
        logger.info("listenKey creat (%s): %s...", "futures" if futures else "spot", listen_key[:12])
        return listen_key

    async def keepalive_listen_key(self, listen_key: str, futures: bool = False) -> None:
        """
        Trimite keepalive pentru a preveni expirarea listenKey (expira dupa 60 min).

        Spot:    PUT /api/v3/userDataStream?listenKey=...
        Futures: PUT /fapi/v1/listenKey?listenKey=...

        Apeleaza la fiecare ~30 minute sau foloseste start_listen_key_keepalive().

        Args:
            listen_key: listenKey obtinut din create_listen_key().
            futures:    Daca True, face keepalive pe Futures endpoint.
        """
        params = {"listenKey": listen_key}
        if futures:
            url = self._futures_base + "/fapi/v1/listenKey"
        else:
            url = self._spot_base + "/api/v3/userDataStream"
        r = await self._client.put(url, params=params)  # type: ignore
        r.raise_for_status()
        logger.debug("listenKey keepalive OK: %s...", listen_key[:12])

    async def delete_listen_key(self, listen_key: str, futures: bool = False) -> None:
        """
        Sterge explicit listenKey la shutdown (buna practica pentru a nu lasa sesiuni zombie).

        Spot:    DELETE /api/v3/userDataStream?listenKey=...
        Futures: DELETE /fapi/v1/listenKey?listenKey=...

        Args:
            listen_key: listenKey de sters.
            futures:    Daca True, sterge pe Futures endpoint.
        """
        params = {"listenKey": listen_key}
        if futures:
            url = self._futures_base + "/fapi/v1/listenKey"
        else:
            url = self._spot_base + "/api/v3/userDataStream"
        r = await self._client.delete(url, params=params)  # type: ignore
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError:
            logger.warning("delete_listen_key: status %s (ignorat la shutdown)", r.status_code)
        logger.info("listenKey sters: %s...", listen_key[:12])

    async def start_listen_key_keepalive(
        self,
        listen_key: str,
        futures: bool = False,
        interval: int = _LISTEN_KEY_KEEPALIVE_INTERVAL,
    ) -> asyncio.Task:
        """
        Porneste un background task asyncio care face keepalive automat.

        Task-ul se opreste automat la stop() sau poate fi anulat manual.
        Un singur task keepalive activ per client (task anterior anulat automat).

        Args:
            listen_key: listenKey activ.
            futures:    Daca True, face keepalive pe Futures endpoint.
            interval:   Interval in secunde intre keepalive-uri. Default 30 min.

        Returns:
            asyncio.Task — poti await-a sau cancel() manual daca e nevoie.

        Exemplu complet:
            async with BinanceClient() as client:
                key = await client.create_listen_key()
                await client.start_listen_key_keepalive(key)
                # porneste WS stream in paralel
                ws = BinanceWebSocket()
                await ws.user_data_stream(key, handle_fill)
        """
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            logger.debug("Task keepalive anterior anulat.")

        async def _loop() -> None:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self.keepalive_listen_key(listen_key, futures=futures)
                except Exception as e:
                    logger.error("listenKey keepalive FAILED: %s", e)

        self._keepalive_task = asyncio.create_task(_loop(), name="binance_listen_key_keepalive")
        logger.info(
            "listenKey keepalive task pornit (interval=%ds, futures=%s)",
            interval,
            futures,
        )
        return self._keepalive_task
