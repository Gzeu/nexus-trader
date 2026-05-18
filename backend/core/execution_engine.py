"""
execution_engine.py – Symbol normalization, order placement, idempotency,
exponential backoff retry, OCO/bracket orders, partial close, dry-run mode.

Fixes applied:
- Added module-level set_exchange_info() (was missing → ImportError at startup)
- place_market_order / place_limit_order: dual-signature
    (signal, qty)  ← automation path
    (symbol, side, quantity[, price, market_mode])  ← routes path
- close_position(position) added (was missing → /close_all crash)
- idempotency_store bounded to 10k entries via OrderedDict FIFO
"""
from __future__ import annotations

import asyncio
import math
import random
import uuid
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Union

import structlog

from backend.config import get_settings
from backend.models import (
    MarketMode,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    StrategySignal,
)

log = structlog.get_logger(__name__)
settings = get_settings()

# Module-level exchange info cache populated at startup via set_exchange_info()
_exchange_info_cache: Dict[str, Any] = {}


def set_exchange_info(info: Dict[str, Any]) -> None:
    """
    Populate module-level exchange info from Binance /exchangeInfo response.
    Called once at startup from state.setup(); also callable for hot-reload.
    """
    global _exchange_info_cache
    for s in info.get("symbols", []):
        _exchange_info_cache[s["symbol"]] = s
    log.info("exchange_info_set", count=len(_exchange_info_cache))


class ExecutionEngine:
    """
    Handles all order placement: normalisation, idempotency, retry, dry-run.
    After any fill: calls self._emitter("order_filled", order) immediately.
    """

    def __init__(
        self,
        binance_client,
        futures_client=None,
        event_emitter: Optional[Callable] = None,
    ):
        self._spot = binance_client
        self._futures = futures_client
        self._emitter = event_emitter
        self._exchange_info: Dict[str, Any] = _exchange_info_cache
        # Bounded idempotency store — FIFO eviction at 10k entries
        self._idempotency_store: OrderedDict = OrderedDict()
        self._IDEM_MAX = 10_000

    def _client_for(self, market_mode: MarketMode):
        if market_mode == MarketMode.FUTURES and self._futures:
            return self._futures
        return self._spot

    async def load_exchange_info(self) -> None:
        """Reload exchange info from Binance and update module cache."""
        info = await self._spot.get_exchange_info()
        set_exchange_info(info)
        self._exchange_info = _exchange_info_cache
        log.info("exchange_info_reloaded", count=len(self._exchange_info))

    # ── Normalisation ─────────────────────────────────────────────────────────

    def normalize_quantity(self, symbol: str, qty: float) -> float:
        """Floor quantity to LOT_SIZE stepSize."""
        f = self._get_filters(symbol, "LOT_SIZE")
        step = float(f.get("stepSize", "0.001"))
        if step <= 0:
            return round(qty, 8)
        precision = max(0, int(round(-math.log10(step))))
        return round(math.floor(qty / step) * step, precision)

    def normalize_price(self, symbol: str, price: float) -> float:
        """Round price to PRICE_FILTER tickSize."""
        f = self._get_filters(symbol, "PRICE_FILTER")
        tick = float(f.get("tickSize", "0.01"))
        if tick <= 0:
            return round(price, 8)
        precision = max(0, int(round(-math.log10(tick))))
        return round(round(price / tick) * tick, precision)

    def check_min_notional(self, symbol: str, qty: float, price: float) -> bool:
        f = self._get_filters(symbol, "MIN_NOTIONAL")
        return qty * price >= float(f.get("minNotional", "10"))

    # ── Market Order ──────────────────────────────────────────────────────────

    async def place_market_order(
        self,
        signal_or_symbol: Union[StrategySignal, str],
        side_or_qty: Union[OrderSide, float] = None,
        quantity: float = None,
        *,
        market_mode: MarketMode = MarketMode.SPOT,
        idempotency_key: Optional[str] = None,
    ) -> Optional[Order]:
        """
        Dual-signature:
          place_market_order(signal, qty)
          place_market_order(symbol, side, quantity, market_mode=...)
        """
        if isinstance(signal_or_symbol, StrategySignal):
            signal = signal_or_symbol
            qty = float(side_or_qty)
            symbol = signal.symbol
            side = OrderSide.BUY if signal.action.value == "BUY" else OrderSide.SELL
            market_mode = getattr(signal, "market_mode", market_mode)
            ref_price = signal.entry_price or 0.0
        else:
            symbol = signal_or_symbol
            side = side_or_qty
            qty = float(quantity)
            ref_price = 0.0

        key = idempotency_key or str(uuid.uuid4())
        if key in self._idempotency_store:
            log.warning("duplicate_order_blocked", key=key, symbol=symbol)
            return None

        qty = self.normalize_quantity(symbol, qty)
        if qty <= 0:
            log.error("zero_qty_after_normalisation", symbol=symbol)
            return None
        if ref_price and not self.check_min_notional(symbol, qty, ref_price):
            log.warning("below_min_notional", symbol=symbol, qty=qty, price=ref_price)

        order = Order(
            client_order_id=key,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=qty,
            market_mode=market_mode,
        )

        if settings.dry_run:
            order.status = OrderStatus.FILLED
            order.executed_qty = qty
            order.avg_price = ref_price
            log.info("dry_run_market_order", symbol=symbol, side=side.value, qty=qty)
            self._add_idem(key)
            await self._post_fill(order)
            return order

        client = self._client_for(market_mode)
        result = await self._with_retry(
            client.place_market_order, symbol=symbol, side=side.value, quantity=qty
        )
        if result:
            order.exchange_order_id = str(result.get("orderId", ""))
            order.status = OrderStatus.FILLED
            order.avg_price = float(result.get("avgPrice") or result.get("price") or 0)
            order.executed_qty = float(result.get("executedQty", qty))
            self._add_idem(key)
            await self._post_fill(order)
        return order if result else None

    # ── Limit Order ───────────────────────────────────────────────────────────

    async def place_limit_order(
        self,
        signal_or_symbol: Union[StrategySignal, str],
        side_or_qty: Union[OrderSide, float] = None,
        quantity_or_price: float = None,
        price: float = None,
        *,
        market_mode: MarketMode = MarketMode.SPOT,
        idempotency_key: Optional[str] = None,
    ) -> Optional[Order]:
        """
        Dual-signature:
          place_limit_order(signal, qty, price)
          place_limit_order(symbol, side, quantity, price, market_mode=...)
        """
        if isinstance(signal_or_symbol, StrategySignal):
            signal = signal_or_symbol
            qty = float(side_or_qty)
            price = float(quantity_or_price)
            symbol = signal.symbol
            side = OrderSide.BUY if signal.action.value == "BUY" else OrderSide.SELL
            market_mode = getattr(signal, "market_mode", market_mode)
        else:
            symbol = signal_or_symbol
            side = side_or_qty
            qty = float(quantity_or_price)
            # price passed as 4th positional or kwarg

        key = idempotency_key or str(uuid.uuid4())
        if key in self._idempotency_store:
            log.warning("duplicate_order_blocked", key=key, symbol=symbol)
            return None

        qty = self.normalize_quantity(symbol, qty)
        price = self.normalize_price(symbol, price)

        order = Order(
            client_order_id=key,
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=qty,
            price=price,
            market_mode=market_mode,
        )

        if settings.dry_run:
            order.status = OrderStatus.NEW
            log.info("dry_run_limit_order", symbol=symbol, price=price, qty=qty)
            self._add_idem(key)
            return order

        client = self._client_for(market_mode)
        result = await self._with_retry(
            client.place_limit_order,
            symbol=symbol,
            side=side.value,
            quantity=qty,
            price=price,
        )
        if result:
            order.exchange_order_id = str(result.get("orderId", ""))
            order.status = OrderStatus.NEW
            self._add_idem(key)
        return order if result else None

    # ── OCO / Bracket ─────────────────────────────────────────────────────────

    async def place_oco_order(
        self,
        symbol: str,
        side: OrderSide,
        qty: float,
        stop_price: float,
        limit_price: float,
        take_profit: float,
        market_mode: MarketMode = MarketMode.SPOT,
    ) -> Optional[dict]:
        """OCO bracket for Spot."""
        qty = self.normalize_quantity(symbol, qty)
        stop_price = self.normalize_price(symbol, stop_price)
        limit_price = self.normalize_price(symbol, limit_price)
        take_profit = self.normalize_price(symbol, take_profit)

        if settings.dry_run:
            log.info("dry_run_oco", symbol=symbol, stop=stop_price, tp=take_profit, qty=qty)
            return {"orderId": "DRY_OCO", "stopPrice": stop_price, "price": take_profit}

        return await self._with_retry(
            self._spot.place_oco_order,
            symbol=symbol,
            side=side.value,
            quantity=qty,
            price=take_profit,
            stop_price=stop_price,
            stop_limit_price=limit_price,
        )

    async def place_bracket_futures(
        self,
        symbol: str,
        side: OrderSide,
        qty: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict:
        """Futures bracket: STOP_MARKET + TAKE_PROFIT_MARKET."""
        close_side = "SELL" if side == OrderSide.BUY else "BUY"
        qty = self.normalize_quantity(symbol, qty)
        stop_loss = self.normalize_price(symbol, stop_loss)
        take_profit = self.normalize_price(symbol, take_profit)

        if settings.dry_run:
            log.info("dry_run_futures_bracket", symbol=symbol, sl=stop_loss, tp=take_profit)
            return {"sl": "DRY_SL", "tp": "DRY_TP"}

        sl_order = await self._with_retry(
            self._futures.place_stop_market_order,
            symbol=symbol, side=close_side, quantity=qty, stop_price=stop_loss,
        )
        tp_order = await self._with_retry(
            self._futures.place_take_profit_market,
            symbol=symbol, side=close_side, quantity=qty, stop_price=take_profit,
        )
        return {"sl": sl_order, "tp": tp_order}

    # ── Close Position ────────────────────────────────────────────────────────

    async def close_position(self, position: Position) -> Optional[Order]:
        """Close entire position at market. Used by /close_all and exit logic."""
        close_side = OrderSide.SELL if position.side.value == "LONG" else OrderSide.BUY
        return await self.place_market_order(
            position.symbol,
            close_side,
            position.quantity,
            market_mode=position.market_mode,
        )

    # ── Cancel ────────────────────────────────────────────────────────────────

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        if settings.dry_run:
            log.info("dry_run_cancel", symbol=symbol, order_id=order_id)
            return True
        result = await self._with_retry(
            self._spot.cancel_order, symbol=symbol, order_id=order_id
        )
        return result is not None

    async def cancel_all_orders(self, symbol: str) -> bool:
        if settings.dry_run:
            log.info("dry_run_cancel_all", symbol=symbol)
            return True
        result = await self._with_retry(self._spot.cancel_all_orders, symbol=symbol)
        return result is not None

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _post_fill(self, order: Order) -> None:
        """Emit events immediately after fill → TradingView host notified."""
        if self._emitter:
            await self._emitter("order_filled", order.model_dump(mode="json"))
            await self._emitter("position_update_required", {"symbol": order.symbol})

    async def _with_retry(
        self,
        fn: Callable,
        max_attempts: int = 4,
        base_delay: float = 0.5,
        **kwargs,
    ) -> Optional[Any]:
        """Exponential backoff with jitter. Returns None after exhausting retries."""
        for attempt in range(1, max_attempts + 1):
            try:
                return await fn(**kwargs)
            except Exception as exc:
                if attempt == max_attempts:
                    log.error("retry_exhausted", fn=fn.__name__, error=str(exc))
                    return None
                delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
                log.warning(
                    "retry", fn=fn.__name__, attempt=attempt,
                    delay=round(delay, 2), error=str(exc),
                )
                await asyncio.sleep(delay)
        return None

    def _get_filters(self, symbol: str, filter_type: str = "LOT_SIZE") -> dict:
        info = self._exchange_info.get(symbol) or _exchange_info_cache.get(symbol, {})
        for f in info.get("filters", []):
            if f.get("filterType") == filter_type:
                return f
        return {}

    def _add_idem(self, key: str) -> None:
        self._idempotency_store[key] = True
        if len(self._idempotency_store) > self._IDEM_MAX:
            self._idempotency_store.popitem(last=False)
