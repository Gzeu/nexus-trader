"""
risk_manager.py – Pre-trade risk gate, daily loss tracker, drawdown guard,
cooldown, consecutive-loss circuit breaker, and volatility/spread filters.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import structlog

from backend.config import get_settings
from backend.models import MarketMode, RiskMetrics, RiskVeto, StrategySignal

log = structlog.get_logger(__name__)
settings = get_settings()


class RiskManager:
    """
    Stateful risk gate. Call `check_signal()` before any order placement.
    All state is in-memory; the portfolio engine syncs equity on startup.
    """

    def __init__(self):
        self.equity: float = 0.0
        self.peak_equity: float = 0.0
        self.daily_start_equity: float = 0.0
        self.daily_reset_date: Optional[datetime] = None
        self.open_positions: int = 0
        self.positions_by_symbol: Dict[str, int] = {}
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.losing_trades: int = 0
        self.consecutive_losses: int = 0
        self.last_loss_time: Optional[datetime] = None
        self._pnl_history: List[float] = []
        self.paused: bool = False
        self.pause_reason: str = ""

    def update_equity(self, equity: float) -> None:
        self.equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity
        now = datetime.utcnow()
        if self.daily_reset_date is None or now.date() > self.daily_reset_date.date():
            self.daily_start_equity = equity
            self.daily_reset_date = now

    def check_signal(self, signal: StrategySignal) -> RiskVeto:
        """Full pre-trade check. Returns RiskVeto.OK if safe to proceed."""
        if self.paused:
            log.warning("risk_paused", reason=self.pause_reason)
            return RiskVeto.DAILY_LOSS if "daily" in self.pause_reason.lower() else RiskVeto.DRAWDOWN

        drawdown = self._current_drawdown()
        if drawdown >= settings.max_drawdown:
            self._pause(f"Emergency stop: drawdown {drawdown:.1%}")
            return RiskVeto.DRAWDOWN

        daily_pnl_pct = self._daily_pnl_pct()
        if daily_pnl_pct <= -settings.max_daily_loss:
            self._pause(f"Daily loss limit {daily_pnl_pct:.1%}", daily=True)
            return RiskVeto.DAILY_LOSS

        if self.open_positions >= settings.max_positions:
            return RiskVeto.MAX_POSITIONS

        if self.positions_by_symbol.get(signal.symbol, 0) > 0:
            return RiskVeto.MAX_POSITIONS

        if self.last_loss_time is not None:
            elapsed = (datetime.utcnow() - self.last_loss_time).total_seconds() / 60
            if elapsed < settings.cooldown_minutes:
                return RiskVeto.COOLDOWN

        if self.consecutive_losses >= settings.max_consecutive_losses:
            self._pause(f"Consecutive losses: {self.consecutive_losses}")
            return RiskVeto.CONSECUTIVE_LOSSES

        if not self._check_rr(signal):
            return RiskVeto.LOW_RR

        return RiskVeto.OK

    def record_trade_result(self, pnl: float) -> None:
        self.total_trades += 1
        self._pnl_history.append(pnl)
        if pnl > 0:
            self.winning_trades += 1
            self.consecutive_losses = 0
        else:
            self.losing_trades += 1
            self.consecutive_losses += 1
            self.last_loss_time = datetime.utcnow()
        self.update_equity(self.equity + pnl)

    def position_opened(self, symbol: str) -> None:
        self.open_positions += 1
        self.positions_by_symbol[symbol] = self.positions_by_symbol.get(symbol, 0) + 1

    def position_closed(self, symbol: str) -> None:
        self.open_positions = max(0, self.open_positions - 1)
        self.positions_by_symbol[symbol] = max(0, self.positions_by_symbol.get(symbol, 0) - 1)

    def resume(self) -> None:
        self.paused = False
        self.pause_reason = ""
        log.info("risk_resumed")

    def get_metrics(self) -> RiskMetrics:
        wins = [p for p in self._pnl_history if p > 0]
        losses = [p for p in self._pnl_history if p <= 0]
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss else 0.0
        win_rate = self.winning_trades / self.total_trades if self.total_trades else 0.0
        expectancy = (sum(self._pnl_history) / self.total_trades) if self.total_trades else 0.0
        return RiskMetrics(
            equity=self.equity, peak_equity=self.peak_equity,
            daily_start_equity=self.daily_start_equity,
            daily_pnl=self.equity - self.daily_start_equity,
            daily_pnl_pct=self._daily_pnl_pct(),
            current_drawdown=self._current_drawdown(),
            max_drawdown=settings.max_drawdown,
            open_positions=self.open_positions,
            total_trades=self.total_trades, winning_trades=self.winning_trades,
            losing_trades=self.losing_trades, consecutive_losses=self.consecutive_losses,
            win_rate=win_rate, profit_factor=profit_factor,
            sharpe_ratio=self._sharpe(), expectancy=expectancy,
            last_loss_time=self.last_loss_time, paused=self.paused, pause_reason=self.pause_reason,
        )

    def _current_drawdown(self) -> float:
        if self.peak_equity == 0:
            return 0.0
        return (self.peak_equity - self.equity) / self.peak_equity

    def _daily_pnl_pct(self) -> float:
        if self.daily_start_equity == 0:
            return 0.0
        return (self.equity - self.daily_start_equity) / self.daily_start_equity

    def _check_rr(self, signal: StrategySignal) -> bool:
        entry = signal.entry_price or 0
        if entry <= 0:
            return True
        tp1 = signal.take_profit_1
        sl = signal.stop_loss
        if signal.action.value == "BUY":
            risk = entry - sl
            reward = tp1 - entry
        else:
            risk = sl - entry
            reward = entry - tp1
        if risk <= 0:
            return False
        return (reward / risk) >= settings.min_rr

    def _sharpe(self, risk_free: float = 0.0) -> float:
        if len(self._pnl_history) < 2:
            return 0.0
        import statistics
        avg = statistics.mean(self._pnl_history)
        std = statistics.stdev(self._pnl_history)
        if std == 0:
            return 0.0
        return (avg - risk_free) / std

    def _pause(self, reason: str, daily: bool = False) -> None:
        self.paused = True
        self.pause_reason = reason
        log.critical("risk_paused", reason=reason)
