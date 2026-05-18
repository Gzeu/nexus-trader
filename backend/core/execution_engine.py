"""
execution_engine.py – Symbol normalization, order placement, idempotency,
exponential backoff retry, OCO/bracket orders, partial close, dry-run mode.
"""
from __future__ import annotations

import asyncio
import math
import random
import uuid
from typing import Any, Callable, Dict, Optional

import structlog

from backend.config import get_settings
from backend.models import (
    EntryType, MarketMode, Order, OrderSide, OrderStatus, OrderType, StrategySignal
)

log = structlog.get_logger(__name__)
settings = get_settings()


class ExecutionEngine:
    """
    Handles all order placement: normalisation, idempotency, retry, dry-run.
    After any fill: triggers post_fill_callback(order).
    """

    def __init__(self, binance_client, event_emitter=None):
        self._client = binance_client
        self._emitter = event_emitter
        self._exchange_info: Dict[str, Any] = {}
        self._idempotency_store: set = set()

    async def load_exchange_info(self) -> None:
        """Must be called at startup before placing any orders."""
        info = await self._client.get_exchange_info()
        for s in info.get("symbols", []):
            self._exchange_info[s["symbol"]] = s
        log.info("exchange_info_loaded", count=len(self._exchange_info))

    def normalize_quantity(self, symbol: str, qty: float) -> float:
        """Floor quantity to stepSize."""
        filters = self._get_filters(symbol)
        step = float(filters.get("stepSize", "0.001"))
        if step <= 0:
            return round(qty, 8)
        precision = int(round(-math.log10(step)))
        floored = math.floor(qty / step) * step
        return round(floored, precision)

    def normalize_price(self, symbol: str, price: float) -> float:
        """Round price to tickSize."""
        filters = self._get_filters(symbol, filter_type="PRICE_FILTER")
        tick = float(filters.get("tickSize", "0.01"))
        if tick <= 0:
            return round(price, 8)
        precision = int(round(-math.log10(tick)))
        rounded = round(price / tick) * tick
        return round(rounded, precision)

    def check_min_notional(self, symbol: str, qty: float, price: float) -> bool:
        """Return True if qty*price >= minNotional."""
        filters = self._get_filters(symbol, filter_type="MIN_NOTIONAL")
        min_notional = float(filters.get("minNotional", "10"))
        return qty * price >= min_notional

    async def place_market_order(
        self, signal: StrategySignal, qty: float, idempotency_key: Optional[str] = None
    ) -> Optional[Order]:
        """Place a market order. Dry-run aware."""
        key = idempotency_key or str(uuid.uuid4())
        if key in self._idempotency_store:
            log.warning("duplicate_order_blocked", key=key)
            return None

        qty = self.normalize_quantity(signal.symbol, qty)
        if qty <= 0:
            log.error("zero_qty_after_normalisation", symbol=signal.symbol)
            return None
        if not self.check_min_notional(signal.symbol, qty, signal.entry_price or 0):
            log.warning("below_min_notional", symbol=signal.symbol, qty=qty)

        side = OrderSide.BUY if signal.action.value == "BUY" else OrderSide.SELL
        order = Order(
            client_order_id=key,
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=qty,
            market_mode=signal.market_mode,
        )

        if settings.dry_run:
            order.status = OrderStatus.FILLED
            order.executed_qty = qty
            order.avg_price = signal.entry_price or 0
            log.info("dry_run_market_order", symbol=signal.symbol, side=side.value, qty=qty)
            self._idempotency_store.add(key)
            await self._post_fill(order)
            return order

        result = await self._with_retry(
            self._client.place_market_order,
            symbol=signal.symbol,
            side=side.value,
            quantity=qty,
            market_mode=signal.market_mode,
        )
        if result:
            order.exchange_order_id = str(result.get("orderId", ""))
            order.status = OrderStatus.FILLED
            order.avg_price = float(result.get("avgPrice", 0) or result.get("price", 0))
            order.executed_qty = float(result.get("executedQty", qty))
            self._idempotency_store.add(key)
            await self._post_fill(order)
        return order if result else None

    async def place_limit_order(
        self, signal: StrategySignal, qty: float, price: float, idempotency_key: Optional[str] = None
    ) -> Optional[Order]:
        key = idempotency_key or str(uuid.uuid4())
        if key in self._idempotency_store:
            log.warning("duplicate_order_blocked", key=key)
            return None

        qty = self.normalize_quantity(signal.symbol, qty)
        price = self.normalize_price(signal.symbol, price)
        side = OrderSide.BUY if signal.action.value == "BUY" else OrderSide.SELL

        order = Order(
            client_order_id=key,
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=qty,
            price=price,
            market_mode=signal.market_mode,
        )

        if settings.dry_run:
            order.status = OrderStatus.NEW
            log.info("dry_run_limit_order", symbol=signal.symbol, price=price, qty=qty)
            self._idempotency_store.add(key)
            return order

        result = await self._with_retry(
            self._client.place_limit_order,
            symbol=signal.symbol,
            side=side.value,
            quantity=qty,
            price=price,
            market_mode=signal.market_mode,
        )
        if result:
            order.exchange_order_id = str(result.get("orderId", ""))
            order.status = OrderStatus.NEW
            self._idempotency_store.add(key)
        return order if result else None

    async def place_oco_order(
        self, symbol: str, side: OrderSide, qty: float,
        stop_price: float, limit_price: float, take_profit: float,
        market_mode: MarketMode = MarketMode.SPOT,
    ) -> Optional[dict]:
        """OCO bracket order (Spot). Futures: use conditional orders."""
        qty = self.normalize_quantity(symbol, qty)
        stop_price = self.normalize_price(symbol, stop_price)
        limit_price = self.normalize_price(symbol, limit_price)
        take_profit = self.normalize_price(symbol, take_profit)

        if settings.dry_run:
            log.info("dry_run_oco", symbol=symbol, stop=stop_price, tp=take_profit, qty=qty)
            return {"orderId": "DRY_OCO", "stopPrice": stop_price, "price": take_profit}

        return await self._with_retry(
            self._client.place_oco_order,
            symbol=symbol,
            side=side.value,
            quantity=qty,
            stop_price=stop_price,
            stop_limit_price=limit_price,
            take_profit_price=take_profit,
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        if settings.dry_run:
            log.info("dry_run_cancel", symbol=symbol, order_id=order_id)
            return True
        result = await self._with_retry(self._client.cancel_order, symbol=symbol, order_id=order_id)
        return result is not None

    async def cancel_all_orders(self, symbol: str) -> bool:
        if settings.dry_run:
            log.info("dry_run_cancel_all", symbol=symbol)
            return True
        result = await self._with_retry(self._client.cancel_all_orders, symbol=symbol)
        return result is not None

    async def _post_fill(self, order: Order) -> None:
        """Emit events after fill so TradingView host is notified immediately."""
        if self._emitter:
            await self._emitter.emit("order_filled", order.model_dump())
            await self._emitter.emit("position_update_required", {"symbol": order.symbol})

    async def _with_retry(
        self,
        fn: Callable,
        max_attempts: int = 4,
        base_delay: float = 0.5,
        **kwargs,
    ) -> Optional[Any]:
        """Exponential backoff with jitter."""
        for attempt in range(1, max_attempts + 1):
            try:
                return await fn(**kwargs)
            except Exception as exc:
                if attempt == max_attempts:
                    log.error("retry_exhausted", fn=fn.__name__, error=str(exc))
                    return None
                delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
                log.warning("retry", fn=fn.__name__, attempt=attempt, delay=round(delay, 2), error=str(exc))
                await asyncio.sleep(delay)
        return None

    def _get_filters(self, symbol: str, filter_type: str = "LOT_SIZE") -> dict:
        info = self._exchange_info.get(symbol, {})
        for f in info.get("filters", []):
            if f.get("filterType") == filter_type:
                return f
        return {}
