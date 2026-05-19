"""
Unit tests for ExecutionEngine — dry-run mode only, no real API calls.
Run: pytest tests/test_execution_engine.py -v
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.core.execution_engine import ExecutionEngine


@pytest.fixture
def engine():
    """ExecutionEngine in dry-run mode with mocked client + emitter."""
    client = MagicMock()
    client.get_exchange_info = AsyncMock(return_value={
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "filters": [
                    {"filterType": "LOT_SIZE", "stepSize": "0.00001000", "minQty": "0.00001", "maxQty": "9000"},
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01000000", "minPrice": "0.01", "maxPrice": "1000000"},
                    {"filterType": "MIN_NOTIONAL", "minNotional": "10.00000000"},
                ],
            }
        ]
    })
    emitter = MagicMock()
    emitter.emit = AsyncMock()
    return ExecutionEngine(client=client, emitter=emitter, dry_run=True)


@pytest.mark.asyncio
class TestNormalize:
    async def test_normalize_quantity_rounds_down(self, engine):
        await engine.load_exchange_info()
        qty = engine.normalize_quantity("BTCUSDT", 0.123456789)
        assert qty == pytest.approx(0.12345, abs=1e-8)

    async def test_normalize_price_rounds_to_tick(self, engine):
        await engine.load_exchange_info()
        price = engine.normalize_price("BTCUSDT", 30000.567)
        assert price == pytest.approx(30000.57, abs=0.001)

    async def test_check_min_notional_passes(self, engine):
        await engine.load_exchange_info()
        ok = engine.check_min_notional("BTCUSDT", qty=0.001, price=30000.0)
        assert ok is True  # 30 > 10

    async def test_check_min_notional_fails(self, engine):
        await engine.load_exchange_info()
        ok = engine.check_min_notional("BTCUSDT", qty=0.0001, price=30.0)
        assert ok is False  # 0.003 < 10


@pytest.mark.asyncio
class TestDryRunOrders:
    async def test_place_market_order_dry_run(self, engine):
        await engine.load_exchange_info()
        order = await engine.place_market_order(
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.001,
        )
        assert order is not None
        assert order.symbol == "BTCUSDT"
        assert order.status.value in ("FILLED", "DRY_RUN")
        # In dry-run, no real API call made
        engine._client.place_market_order.assert_not_called()

    async def test_place_limit_order_dry_run(self, engine):
        await engine.load_exchange_info()
        order = await engine.place_limit_order(
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.001,
            price=29000.0,
        )
        assert order is not None
        assert order.symbol == "BTCUSDT"
