"""
Unit tests pentru AutomationEngine — focus pe logica critica:
- rollback on_position_opened daca place_order esueaza
- skip tick daca portfolio not ready sau risk paused
- anti-duplicate candle signal
Run: pytest tests/test_automation_engine.py -v
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.automation_engine import AutomationEngine
from backend.models import Action, StrategySignal


def _make_signal(
    symbol: str = "BTCUSDT",
    action: Action = Action.BUY,
    candle_open_time: str = "1716000000000",
) -> StrategySignal:
    return StrategySignal(
        symbol=symbol,
        action=action,
        confidence=0.8,
        entry_type="market",
        entry_price=30000.0,
        stop_loss=29000.0,
        take_profit_1=31500.0,
        take_profit_2=33000.0,
        timeframe="15m",
        reason="test",
        candle_open_time=candle_open_time,
        metadata={},
    )


@pytest.fixture
def engine():
    """AutomationEngine cu toate dependintele mock-uite."""
    strategy      = MagicMock()
    risk          = MagicMock()
    execution     = MagicMock()
    portfolio     = MagicMock()
    binance       = MagicMock()

    risk.is_paused         = False
    risk.check_signal      = MagicMock()
    risk.on_position_opened = MagicMock()
    risk.rollback_position_opened = MagicMock()
    risk.update_equity     = MagicMock()

    portfolio.is_ready     = True
    portfolio.get_equity   = MagicMock(return_value=10_000.0)
    portfolio.get_positions = MagicMock(return_value=[])

    execution.calc_position_size = MagicMock(return_value=0.1)
    execution.place_order        = AsyncMock(return_value={"orderId": "123"})

    binance.get_klines = AsyncMock(return_value=[[i, 100, 101, 99, 100, 1000] for i in range(60)])

    with patch("backend.core.automation_engine.get_settings") as mock_cfg:
        cfg = MagicMock()
        cfg.symbol_whitelist        = ["BTCUSDT"]
        cfg.automation_interval_minutes = 1
        cfg.primary_timeframe       = "15m"
        cfg.order_timeout_seconds   = 5
        cfg.risk_per_trade          = 0.01
        mock_cfg.return_value       = cfg

        eng = AutomationEngine(
            strategy=strategy,
            risk_manager=risk,
            execution_engine=execution,
            portfolio_engine=portfolio,
            binance_client=binance,
        )
        eng._cfg = cfg
        yield eng


class TestTickSkipConditions:
    @pytest.mark.asyncio
    async def test_tick_skipped_when_portfolio_not_ready(self, engine):
        engine._portfolio.is_ready = False
        engine._tick_count = 0
        await engine._tick()
        engine._client.get_klines.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_skipped_when_risk_paused(self, engine):
        engine._risk.is_paused = True
        engine._tick_count = 0
        await engine._tick()
        engine._client.get_klines.assert_not_called()


class TestAntiDuplicate:
    @pytest.mark.asyncio
    async def test_same_candle_key_skipped_on_second_call(self, engine):
        from collections import deque
        from backend.core.automation_engine import _SEEN_CANDLES_MAXLEN

        signal = _make_signal(candle_open_time="abc123")
        engine._strategy.compute = MagicMock(return_value=signal)
        engine._risk.check_signal.return_value = MagicMock(value="PASS")

        # Prima procesare
        await engine._process_symbol("BTCUSDT")
        first_call_count = engine._execution.place_order.call_count

        # A doua procesare cu aceeasi lumanare
        await engine._process_symbol("BTCUSDT")
        second_call_count = engine._execution.place_order.call_count

        # Ordinul nu trebuie plasat de doua ori
        assert second_call_count == first_call_count


class TestRollbackOnFailure:
    @pytest.mark.asyncio
    async def test_rollback_called_when_place_order_raises(self, engine):
        """Daca place_order arunca exceptie, rollback_position_opened trebuie apelat."""
        engine._execution.place_order = AsyncMock(side_effect=RuntimeError("exchange down"))
        signal = _make_signal()

        await engine._execute_signal(signal)

        engine._risk.on_position_opened.assert_called_once_with("BTCUSDT")
        engine._risk.rollback_position_opened.assert_called_once_with("BTCUSDT")
        # update_equity NU trebuie apelat daca ordinul a esuat
        engine._risk.update_equity.assert_not_called()

    @pytest.mark.asyncio
    async def test_rollback_called_on_timeout(self, engine):
        """Timeout pe place_order trebuie sa triggere rollback."""
        async def slow_order(**kwargs):
            await asyncio.sleep(10)  # mai lung decat order_timeout=5

        engine._execution.place_order = AsyncMock(side_effect=asyncio.TimeoutError())
        signal = _make_signal()

        await engine._execute_signal(signal)

        engine._risk.rollback_position_opened.assert_called_once_with("BTCUSDT")

    @pytest.mark.asyncio
    async def test_no_rollback_on_success(self, engine):
        """Daca place_order reuseste, rollback NU trebuie apelat."""
        signal = _make_signal()
        await engine._execute_signal(signal)

        engine._risk.on_position_opened.assert_called_once_with("BTCUSDT")
        engine._risk.rollback_position_opened.assert_not_called()
        engine._risk.update_equity.assert_called_once()

    @pytest.mark.asyncio
    async def test_zero_qty_returns_early(self, engine):
        """Daca calc_position_size returneaza 0, nu se plaseaza ordin si nu se apeleaza rollback."""
        engine._execution.calc_position_size = MagicMock(return_value=0.0)
        signal = _make_signal()

        await engine._execute_signal(signal)

        engine._risk.on_position_opened.assert_not_called()
        engine._execution.place_order.assert_not_called()
