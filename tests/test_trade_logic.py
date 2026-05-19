"""
Unit tests for TradeLogic.
Run: pytest tests/test_trade_logic.py -v
"""
from __future__ import annotations

import pytest

from backend.models import Action, StrategySignal
from backend.core.trade_logic import TradeLogic


def _sig(
    action=Action.BUY,
    entry_price=100.0,
    stop_loss=95.0,
    tp1=107.5,
    tp2=115.0,
    confidence=0.85,
) -> StrategySignal:
    return StrategySignal(
        symbol="BTCUSDT",
        action=action,
        confidence=confidence,
        entry_type="market",
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit_1=tp1,
        take_profit_2=tp2,
        timeframe="5m",
        reason="test",
    )


class TestCalcPositionSize:
    def test_basic(self):
        # equity=10000, risk=1% → risk_amount=100
        # sl_distance = 100-95 = 5
        # qty = 100/5 = 20
        qty = TradeLogic.calc_position_size(
            equity=10_000.0,
            entry_price=100.0,
            stop_loss=95.0,
            risk_pct=0.01,
        )
        assert qty == pytest.approx(20.0)

    def test_zero_sl_distance_returns_zero(self):
        qty = TradeLogic.calc_position_size(
            equity=10_000.0,
            entry_price=100.0,
            stop_loss=100.0,  # same as entry
            risk_pct=0.01,
        )
        assert qty == 0.0

    def test_respects_max_position_pct(self):
        # Very tight SL would produce huge qty — capped at max_position_pct=10%
        qty = TradeLogic.calc_position_size(
            equity=10_000.0,
            entry_price=100.0,
            stop_loss=99.99,
            risk_pct=0.01,
            max_position_pct=0.10,
        )
        max_qty = (10_000.0 * 0.10) / 100.0
        assert qty <= max_qty


class TestShouldEnterLong:
    def test_valid_long_passes(self):
        sig = _sig(action=Action.BUY, confidence=0.75)
        ok, reason = TradeLogic.should_enter_long(sig, current_price=100.0)
        assert ok is True
        assert reason == ""

    def test_low_confidence_blocked(self):
        sig = _sig(confidence=0.5)
        ok, reason = TradeLogic.should_enter_long(sig, current_price=100.0)
        assert ok is False
        assert "confidence" in reason.lower()

    def test_sell_action_blocked(self):
        sig = _sig(action=Action.SELL)
        ok, reason = TradeLogic.should_enter_long(sig, current_price=100.0)
        assert ok is False


class TestShouldEnterShort:
    def test_valid_short_passes(self):
        sig = _sig(
            action=Action.SELL,
            entry_price=100.0,
            stop_loss=105.0,  # SL above entry for short
            tp1=92.5,
            tp2=85.0,
            confidence=0.80,
        )
        ok, reason = TradeLogic.should_enter_short(sig, current_price=100.0)
        assert ok is True

    def test_buy_action_blocked(self):
        sig = _sig(action=Action.BUY)
        ok, reason = TradeLogic.should_enter_short(sig, current_price=100.0)
        assert ok is False
