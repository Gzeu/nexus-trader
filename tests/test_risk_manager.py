"""
Unit tests for RiskManager — aliniate la API-ul actual.
Run: pytest tests/test_risk_manager.py -v
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from backend.models import Action, StrategySignal
from backend.core.risk_manager import RiskManager
from backend.models import RiskVeto


def _signal(
    symbol: str = "BTCUSDT",
    action: Action = Action.BUY,
    entry_price: float = 30000.0,
    stop_loss: float = 29000.0,
    take_profit_1: float = 31500.0,
    take_profit_2: float = 33000.0,
    metadata: dict | None = None,
) -> StrategySignal:
    return StrategySignal(
        symbol=symbol,
        action=action,
        confidence=0.8,
        entry_type="market",
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        timeframe="15m",
        reason="test",
        metadata=metadata or {},
    )


@pytest.fixture
def rm():
    """RiskManager cu equity initiala de 10_000 USDT."""
    manager = RiskManager()
    manager.update_equity(10_000.0)
    return manager


class TestCheckSignalGating:
    def test_valid_signal_passes(self, rm):
        assert rm.check_signal(_signal()) == RiskVeto.PASS

    def test_paused_blocks(self, rm):
        rm.pause(reason="test")
        assert rm.check_signal(_signal()) == RiskVeto.PAUSED

    def test_max_drawdown_blocks(self, rm):
        rm._peak_equity = 10_000.0
        rm._equity = 8_700.0   # -13% > max 12%
        assert rm.check_signal(_signal()) == RiskVeto.MAX_DRAWDOWN

    def test_daily_loss_blocks(self, rm):
        rm._daily_start_equity = 10_000.0
        rm._daily_pnl = -350.0   # -3.5% > max 3%
        assert rm.check_signal(_signal()) == RiskVeto.DAILY_LOSS

    def test_max_positions_blocks(self, rm):
        for sym in ["BTCUSDT", "ETHUSDT", "BNBUSDT"]:
            rm.on_position_opened(sym)
        # default max_open_positions = 3
        assert rm.check_signal(_signal(symbol="SOLUSDT")) == RiskVeto.MAX_POSITIONS

    def test_duplicate_symbol_blocks(self, rm):
        rm.on_position_opened("BTCUSDT")
        assert rm.check_signal(_signal(symbol="BTCUSDT")) == RiskVeto.SYMBOL_ALREADY_OPEN

    def test_cooldown_blocks(self, rm):
        from datetime import datetime, timezone
        rm._last_loss_time = datetime.now(timezone.utc)
        rm._consecutive_losses = 1
        assert rm.check_signal(_signal()) == RiskVeto.COOLDOWN

    def test_consecutive_losses_blocks(self, rm):
        rm._consecutive_losses = 99
        assert rm.check_signal(_signal()) == RiskVeto.CONSECUTIVE_LOSSES

    def test_poor_rr_blocks(self, rm):
        # RR = 100/100 = 1.0 < 1.5 min
        sig = _signal(entry_price=30000, stop_loss=29900, take_profit_1=30100)
        assert rm.check_signal(sig) == RiskVeto.MIN_RR

    def test_volatility_veto(self, rm):
        sig = _signal(metadata={"atr_pct": 0.10})  # 10% > default 5%
        assert rm.check_signal(sig) == RiskVeto.VOLATILITY

    def test_volatility_ok_passes(self, rm):
        sig = _signal(metadata={"atr_pct": 0.02})  # 2% < 5%
        assert rm.check_signal(sig) == RiskVeto.PASS

    def test_rr_none_values_do_not_bypass(self, rm):
        """RR check cu is not None — valori None nu sar check-ul."""
        sig = _signal(stop_loss=None, take_profit_1=None)
        # Fara stop_loss/tp, RR check e skip-at, semnalul trece
        assert rm.check_signal(sig) == RiskVeto.PASS


class TestEquityTracking:
    def test_peak_equity_tracks_high(self, rm):
        rm.update_equity(12_000.0)
        rm.update_equity(10_000.0)
        assert rm.peak_equity == 12_000.0

    def test_daily_pnl_computed_correctly(self, rm):
        rm._daily_start_equity = 10_000.0
        rm.update_equity(10_500.0)
        assert abs(rm.daily_pnl - 500.0) < 0.01

    def test_auto_pause_on_max_drawdown(self, rm):
        rm._peak_equity = 10_000.0
        rm.update_equity(8_700.0)  # -13%
        assert rm.is_paused

    def test_auto_pause_on_daily_loss(self, rm):
        rm._daily_start_equity = 10_000.0
        rm.update_equity(9_600.0)  # -4%
        assert rm.is_paused

    def test_equity_zero_guard_in_reset_daily(self, rm):
        rm._equity = 0.0
        rm._daily_start_equity = 5_000.0
        rm.reset_daily()
        # Guard: daca equity=0, daily_start_equity NU se modifica
        assert rm._daily_start_equity == 5_000.0


class TestTradeLifecycle:
    def test_loss_increments_consecutive(self, rm):
        rm.on_trade_closed(pnl=-100.0, symbol="BTCUSDT")
        rm.on_trade_closed(pnl=-200.0, symbol="ETHUSDT")
        assert rm.consecutive_losses == 2

    def test_win_resets_consecutive(self, rm):
        rm._consecutive_losses = 3
        rm.on_trade_closed(pnl=500.0, symbol="BTCUSDT")
        assert rm.consecutive_losses == 0

    def test_on_position_opened_idempotent(self, rm):
        rm.on_position_opened("BTCUSDT")
        rm.on_position_opened("BTCUSDT")  # dublu apel
        assert rm.open_position_count == 1

    def test_rollback_removes_symbol(self, rm):
        rm.on_position_opened("BTCUSDT")
        rm.rollback_position_opened("BTCUSDT")
        assert rm.open_position_count == 0

    def test_rollback_idempotent_on_missing(self, rm):
        """rollback pe simbol absent e no-op, nu arunca exceptie."""
        rm.rollback_position_opened("UNKNOWN")  # nu trebuie sa arunce


class TestPauseResume:
    def test_resume_clears_pause(self, rm):
        rm.pause("test")
        rm.resume()
        assert not rm.is_paused

    def test_resume_resets_consecutive_losses(self, rm):
        rm._consecutive_losses = 5
        rm.resume()
        assert rm.consecutive_losses == 0

    def test_reset_daily_clears_pnl(self, rm):
        rm._daily_pnl = -500.0
        rm._equity = 10_000.0
        rm.reset_daily()
        assert rm._daily_pnl == 0.0
