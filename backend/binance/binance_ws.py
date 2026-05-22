"""
binance_ws.py — Binance WebSocket streams (async, auto-reconnect).

Streams disponibile:
  - kline_stream       : OHLCV candle updates live
  - book_ticker_stream : Best bid/ask real-time
  - user_data_stream   : Order fills / executionReport (necesita listenKey)

Reconectare automata la drop cu delay configurabil din Settings.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import websockets
from websockets.exceptions import ConnectionClosed

from backend.config import get_settings

logger = logging.getLogger(__name__)

_WS_SPOT_BASE = "wss://stream.binance.com:9443/ws"
_WS_SPOT_TEST = "wss://testnet.binance.vision/ws"
_WS_FUTS_BASE = "wss://fstream.binance.com/ws"
_WS_FUTS_TEST = "wss://stream.binancefuture.com/ws"

Callback = Callable[[dict], Awaitable[None]]


class BinanceWebSocket:
    """
    WebSocket client async pentru Binance.
    Suporta Spot + Futures, Testnet + Mainnet, auto-reconnect.
    """

    def __init__(self) -> None:
        cfg = get_settings()
        self._testnet = cfg.testnet
        self._reconnect_delay = cfg.ws_reconnect_delay
        self._ping_interval = cfg.ws_ping_interval

        self._spot_ws = _WS_SPOT_TEST if self._testnet else _WS_SPOT_BASE
        self._futs_ws = _WS_FUTS_TEST if self._testnet else _WS_FUTS_BASE

    # ─────────────────────────────────────────────── internal

    async def _listen(self, uri: str, callback: Callback, stream_name: str) -> None:
        """Loop cu auto-reconnect. Apeleaza callback(dict) pentru fiecare mesaj."""
        while True:
            try:
                async with websockets.connect(
                    uri,
                    ping_interval=self._ping_interval,
                    ping_timeout=10,
                ) as ws:
                    logger.info("WS connected: %s", stream_name)
                    async for raw in ws:
                        try:
                            await callback(json.loads(raw))
                        except Exception as cb_err:
                            logger.error("WS callback error [%s]: %s", stream_name, cb_err)
            except ConnectionClosed as e:
                logger.warning("WS closed [%s]: %s — reconectare in %ds", stream_name, e, self._reconnect_delay)
            except Exception as e:
                logger.error("WS error [%s]: %s — reconectare in %ds", stream_name, e, self._reconnect_delay)
            await asyncio.sleep(self._reconnect_delay)

    # ─────────────────────────────────────────────── public streams

    async def kline_stream(
        self,
        symbol: str,
        interval: str,
        callback: Callback,
        futures: bool = False,
    ) -> None:
        """
        Stream kline/candlestick live.

        Args:
            symbol:   ex: "BTCUSDT"
            interval: ex: "1m", "5m", "15m", "1h"
            callback: async fn(dict) apelata la fiecare candle update
            futures:  daca True, foloseste Futures WebSocket
        """
        stream = f"{symbol.lower()}@kline_{interval}"
        base = self._futs_ws if futures else self._spot_ws
        await self._listen(f"{base}/{stream}", callback, stream)

    async def book_ticker_stream(
        self,
        symbol: str,
        callback: Callback,
        futures: bool = False,
    ) -> None:
        """
        Stream best bid/ask real-time (bookTicker).

        Args:
            symbol:  ex: "BTCUSDT"
            callback: async fn(dict) cu campurile: b (bid), B (bidQty), a (ask), A (askQty)
            futures: daca True, foloseste Futures WebSocket
        """
        stream = f"{symbol.lower()}@bookTicker"
        base = self._futs_ws if futures else self._spot_ws
        await self._listen(f"{base}/{stream}", callback, stream)

    async def mark_price_stream(
        self,
        symbol: str,
        callback: Callback,
        update_speed: str = "1s",
    ) -> None:
        """
        Stream mark price Futures (1s sau 3s).

        Args:
            symbol:       ex: "BTCUSDT"
            callback:     async fn(dict)
            update_speed: "1s" sau "3s"
        """
        stream = f"{symbol.lower()}@markPrice@{update_speed}"
        await self._listen(f"{self._futs_ws}/{stream}", callback, stream)

    async def user_data_stream(
        self,
        listen_key: str,
        callback: Callback,
        futures: bool = False,
        fills_only: bool = True,
    ) -> None:
        """
        Stream user data (order fills, balance updates).

        Args:
            listen_key: obtinut din BinanceClient.create_listen_key()
            callback:   async fn(dict) apelata la fiecare event
            futures:    daca True, foloseste Futures stream
            fills_only: daca True, filtreaza doar evenimentele executionReport (order fills)
        """
        base = self._futs_ws if futures else self._spot_ws
        uri = f"{base}/{listen_key}"

        async def _filtered(data: dict) -> None:
            if fills_only and data.get("e") not in ("executionReport", "ORDER_TRADE_UPDATE"):
                return
            await callback(data)

        await self._listen(uri, _filtered, f"userData/{listen_key[:8]}...")

    async def multi_stream(
        self,
        streams: list[str],
        callback: Callback,
        futures: bool = False,
    ) -> None:
        """
        Combined stream — mai multe streams intr-o singura conexiune WS.

        Args:
            streams:  lista de stream names, ex: ["btcusdt@kline_1m", "ethusdt@bookTicker"]
            callback: async fn(dict) — data.stream contine numele stream-ului
            futures:  daca True, foloseste Futures WebSocket

        Exemplu:
            await ws.multi_stream(
                ["btcusdt@kline_1m", "ethusdt@kline_1m"],
                my_callback
            )
        """
        combined = "/".join(streams)
        if futures:
            base = _WS_FUTS_TEST if self._testnet else _WS_FUTS_BASE.replace("/ws", "/stream")
        else:
            base = _WS_SPOT_TEST.replace("/ws", "/stream") if self._testnet else _WS_SPOT_BASE.replace("/ws", "/stream")
        uri = f"{base}?streams={combined}"
        await self._listen(uri, callback, f"multi/{len(streams)} streams")
