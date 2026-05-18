"""
risk_manager.py – Pre-trade risk gate, daily loss tracker, drawdown guard,
cooldown, consecutive-loss circuit breaker.

Fixes applied:
- _pause_type field added: "daily_loss" | "drawdown" | "consecutive" | "manual"
- check_signal() returns semantically correct RiskVeto when paused
  (was always returning DRAWDOWN or DAILY_LOSS for manual emergency stop)
- _pause() accepts pause_type param
- RiskVeto.PAUSED must be added to models.py enum (see patch note in PR)
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import structlog

from backend.config import get_settings
from backend.models import RiskMetrics, RiskVeto, StrategySignal

log = structlog.get_logger(__name__)
settings = get_settings()


class RiskManager:
    """
    Stateful risk gate. Call check_signal() before any order placement.
    All state is in-memory; PortfolioEngine calls update_equity() on reconcile.
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
        self._pause_type: str = ""   # "daily_loss" | "drawdown" | "consecutive" | "manual"

    def update_equity(self, equity: float) -> None:
        """Update equity + peak; reset daily baseline on new UTC day."""
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
            log.warning("risk_paused", reason=self.pause_reason, type=self._pause_type)
            # Return semantically correct veto based on why we paused
            return {
                "daily_loss": RiskVeto.DAILY_LOSS,
                "drawdown": RiskVeto.DRAWDOWN,
                "consecutive": RiskVeto.CONSECUTIVE_LOSSES,
                "manual": RiskVeto.PAUSED,
            }.get(self._pause_type, RiskVeto.PAUSED)

        drawdown = self._current_drawdown()
        if drawdown >= settings.max_drawdown:
            self._pause(
                f"Emergency stop: drawdown {drawdown:.1%} >= {settings.max_drawdown:.1%}",
                pause_type="drawdown",
            )
            return RiskVeto.DRAWDOWN

        daily_pnl_pct = self._daily_pnl_pct()
        if daily_pnl_pct <= -settings.max_daily_loss:
            self._pause(
                f"Daily loss limit: {daily_pnl_pct:.1%} <= -{settings.max_daily_loss:.1%}",
                pause_type="daily_loss",
            )
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
            self._pause(
                f"Consecutive losses: {self.consecutive_losses}",
                pause_type="consecutive",
            )
            return RiskVeto.CONSECUTIVE_LOSSES

        if not self._check_rr(signal):
            return RiskVeto.LOW_RR

        return RiskVeto.OK

    def record_trade_result(self, pnl: float) -> None:
        """Update stats after a trade closes."""
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
        self.positions_by_symbol[symbol] = max(
            0, self.positions_by_symbol.get(symbol, 0) - 1
        )

    def resume(self) -> None:
        """Manually resume trading after any pause."""
        self.paused = False
        self.pause_reason = ""
        self._pause_type = ""
        log.info("risk_resumed")

    def get_metrics(self) -> RiskMetrics:
        wins = [p for p in self._pnl_history if p > 0]
        losses = [p for p in self._pnl_history if p <= 0]
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        return RiskMetrics(
            equity=self.equity,
            peak_equity=self.peak_equity,
            daily_start_equity=self.daily_start_equity,
            daily_pnl=self.equity - self.daily_start_equity,
            daily_pnl_pct=self._daily_pnl_pct(),
            current_drawdown=self._current_drawdown(),
            max_drawdown=settings.max_drawdown,
            open_positions=self.open_positions,
            total_trades=self.total_trades,
            winning_trades=self.winning_trades,
            losing_trades=self.losing_trades,
            consecutive_losses=self.consecutive_losses,
            win_rate=self.winning_trades / self.total_trades if self.total_trades else 0.0,
            profit_factor=gross_profit / gross_loss if gross_loss else 0.0,
            sharpe_ratio=self._sharpe(),
            expectancy=sum(self._pnl_history) / self.total_trades if self.total_trades else 0.0,
            last_loss_time=self.last_loss_time,
            paused=self.paused,
            pause_reason=self.pause_reason,
        )

    # ── Internals ─────────────────────────────────────────────────────────────

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
        """Trade-by-trade Sharpe ratio (NOT annualized)."""
        if len(self._pnl_history) < 2:
            return 0.0
        import statistics
        avg = statistics.mean(self._pnl_history)
        std = statistics.stdev(self._pnl_history)
        return (avg - risk_free) / std if std else 0.0

    def _pause(self, reason: str, pause_type: str = "manual") -> None:
        self.paused = True
        self.pause_reason = reason
        self._pause_type = pause_type
        log.critical("risk_paused", reason=reason, type=pause_type)
