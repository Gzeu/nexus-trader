"""
Unit tests for RiskManager.
Run: pytest tests/test_risk_manager.py -v
"""
from __future__ import annotations

import pytest

from backend.models import Action, StrategySignal
from backend.core.risk_manager import RiskManager, RiskVeto


def _make_signal(
    symbol: str = "BTCUSDT",
    action: Action = Action.BUY,
    confidence: float = 0.8,
    stop_loss: float = 29000.0,
    entry_price: float = 30000.0,
    take_profit_1: float = 31500.0,
    take_profit_2: float = 33000.0,
) -> StrategySignal:
    return StrategySignal(
        symbol=symbol,
        action=action,
        confidence=confidence,
        entry_type="market",
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        timeframe="5m",
        reason="test",
    )


@pytest.fixture
def rm():
    return RiskManager(equity=10_000.0)


class TestRiskManager:
    def test_valid_signal_passes(self, rm):
        signal = _make_signal()
        result = rm.check_signal(signal)
        assert result is None  # None = no veto

    def test_paused_blocks_all(self, rm):
        rm._paused = True
        result = rm.check_signal(_make_signal())
        assert result == RiskVeto.PAUSED

    def test_max_positions_blocks(self, rm):
        rm._open_positions = 5  # default MAX_POSITIONS = 5
        result = rm.check_signal(_make_signal())
        assert result == RiskVeto.MAX_POSITIONS

    def test_duplicate_symbol_blocks(self, rm):
        rm._positions_by_symbol["BTCUSDT"] = True
        result = rm.check_signal(_make_signal(symbol="BTCUSDT"))
        assert result == RiskVeto.DUPLICATE_SYMBOL

    def test_daily_loss_blocks(self, rm):
        # Simulate 3% daily loss
        rm._daily_start_equity = 10_000.0
        rm._equity = 9_700.0  # exactly -3%
        result = rm.check_signal(_make_signal())
        assert result == RiskVeto.DAILY_LOSS_LIMIT

    def test_max_drawdown_blocks(self, rm):
        rm._peak_equity = 10_000.0
        rm._equity = 8_750.0  # -12.5% > 12%
        result = rm.check_signal(_make_signal())
        assert result == RiskVeto.MAX_DRAWDOWN

    def test_min_rr_blocks(self, rm):
        # SL=29900, entry=30000, TP1=30100 → RR = 100/100 = 1.0 < 1.5
        signal = _make_signal(
            entry_price=30000,
            stop_loss=29900,
            take_profit_1=30100,
            take_profit_2=30200,
        )
        result = rm.check_signal(signal)
        assert result == RiskVeto.MIN_RR

    def test_hold_action_is_skipped(self, rm):
        signal = _make_signal(action=Action.HOLD)
        # HOLD signals should not be vetoed by position-limit rules
        # (risk manager returns None for non-entry actions)
        result = rm.check_signal(signal)
        assert result is None

    def test_update_equity(self, rm):
        rm.update_equity(11_000.0)
        assert rm._equity == 11_000.0
        assert rm._peak_equity == 11_000.0

    def test_record_loss_increments_consecutive(self, rm):
        rm.record_trade_result(pnl=-100.0)
        rm.record_trade_result(pnl=-200.0)
        assert rm._consecutive_losses == 2

    def test_record_win_resets_consecutive(self, rm):
        rm._consecutive_losses = 3
        rm.record_trade_result(pnl=500.0)
        assert rm._consecutive_losses == 0
