"""
RiskManager — gatekeeper pentru toate ordinele.

CHANGELOG:
  🟡 peak_equity, consecutive_losses, daily_pnl, max_drawdown_seen expuse
     ca properties publice (folosite de /metrics in routes.py).
     Anterior erau atribute private cu prefix _ accesate cu getattr() fragil.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from backend.config import get_settings
from backend.models import RiskVeto, StrategySignal

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Verifica fiecare semnal inainte de executie.
    Toate regulile de risc sunt configurabile din Settings.
    """

    def __init__(self) -> None:
        cfg = get_settings()

        # Stare interna
        self._paused: bool = False
        self._pause_reason: str = ""
        self._equity: float = 0.0
        self._peak_equity: float = 0.0
        self._daily_start_equity: float = 0.0
        self._daily_pnl: float = 0.0
        self._consecutive_losses: int = 0
        self._last_loss_time: Optional[datetime] = None
        self._max_drawdown_seen: float = 0.0
        self._open_position_count: int = 0
        self._open_symbols: set[str] = set()

        # Configuratie
        self._max_positions       = cfg.max_open_positions
        self._risk_per_trade      = cfg.risk_per_trade
        self._max_daily_loss      = cfg.max_daily_loss_pct
        self._max_drawdown        = cfg.max_drawdown_pct
        self._min_rr              = cfg.min_risk_reward
        self._cooldown_minutes    = cfg.sl_cooldown_minutes
        self._max_consec_losses   = cfg.max_consecutive_losses

    # ─────────────────────────────────────────────────────── public properties

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def peak_equity(self) -> float:
        """🟡 Cel mai mare nivel de equity atins — pentru drawdown calc in /metrics."""
        return self._peak_equity

    @property
    def consecutive_losses(self) -> int:
        """🟡 Nr. de pierderi consecutive curente."""
        return self._consecutive_losses

    @property
    def daily_pnl(self) -> float:
        """🟡 PnL realizat azi (pozitiv = profit, negativ = pierdere)."""
        return self._daily_pnl

    @property
    def max_drawdown_seen(self) -> float:
        """🟡 Cel mai mare drawdown observat (fractie, ex: 0.05 = 5%)."""
        return self._max_drawdown_seen

    # ─────────────────────────────────────────────────────────── equity sync

    def update_equity(self, equity: float) -> None:
        """Apelat de PortfolioEngine dupa fiecare reconciliere sau fill."""
        self._equity = equity
        if equity > self._peak_equity:
            self._peak_equity = equity

        # Actualizeaza daily PnL
        if self._daily_start_equity > 0:
            self._daily_pnl = equity - self._daily_start_equity
        else:
            self._daily_start_equity = equity

        # Calculeaza si track-uieste drawdown
        if self._peak_equity > 0:
            current_dd = 1.0 - (equity / self._peak_equity)
            if current_dd > self._max_drawdown_seen:
                self._max_drawdown_seen = current_dd

            # Emergency stop la drawdown maxim
            if current_dd >= self._max_drawdown:
                if not self._paused:
                    self.pause(
                        reason=f"max_drawdown_breach: {current_dd:.2%} >= {self._max_drawdown:.2%}"
                    )

        # Daily loss stop
        if self._daily_start_equity > 0:
            daily_loss_pct = -self._daily_pnl / self._daily_start_equity
            if daily_loss_pct >= self._max_daily_loss and not self._paused:
                self.pause(
                    reason=f"daily_loss_breach: {daily_loss_pct:.2%} >= {self._max_daily_loss:.2%}"
                )

    # ─────────────────────────────────────────────────────── signal gating

    def check_signal(self, signal: StrategySignal) -> RiskVeto:
        """
        Verifica un semnal inainte de executie.
        Returneaza RiskVeto cu motivul blocarii, sau RiskVeto.PASS daca OK.
        """
        if self._paused:
            return RiskVeto.PAUSED

        # Drawdown emergency (double-check, update_equity poate fi intarziat)
        if self._peak_equity > 0:
            current_dd = 1.0 - (self._equity / self._peak_equity)
            if current_dd >= self._max_drawdown:
                return RiskVeto.MAX_DRAWDOWN

        # Daily loss
        if self._daily_start_equity > 0:
            daily_loss_pct = -self._daily_pnl / self._daily_start_equity
            if daily_loss_pct >= self._max_daily_loss:
                return RiskVeto.DAILY_LOSS

        # Max pozitii
        if self._open_position_count >= self._max_positions:
            return RiskVeto.MAX_POSITIONS

        # One per symbol
        if signal.symbol in self._open_symbols:
            return RiskVeto.SYMBOL_ALREADY_OPEN

        # Cooldown dupa SL
        if self._last_loss_time is not None:
            elapsed = (
                datetime.now(timezone.utc) - self._last_loss_time
            ).total_seconds() / 60
            if elapsed < self._cooldown_minutes:
                return RiskVeto.COOLDOWN

        # Consecutive losses
        if self._consecutive_losses >= self._max_consec_losses:
            return RiskVeto.CONSECUTIVE_LOSSES

        # Min RR check
        if signal.stop_loss and signal.take_profit_1 and signal.entry_price:
            risk   = abs(signal.entry_price - signal.stop_loss)
            reward = abs(signal.take_profit_1 - signal.entry_price)
            if risk > 0 and (reward / risk) < self._min_rr:
                return RiskVeto.MIN_RR

        return RiskVeto.PASS

    # ──────────────────────────────────────────────────── trade outcome sync

    def on_trade_closed(self, pnl: float, symbol: str) -> None:
        """Apelat de ExecutionEngine/AutomationEngine la inchiderea unui trade."""
        self._open_position_count = max(0, self._open_position_count - 1)
        self._open_symbols.discard(symbol)

        if pnl < 0:
            self._consecutive_losses += 1
            self._last_loss_time = datetime.now(timezone.utc)
        else:
            self._consecutive_losses = 0

    def on_position_opened(self, symbol: str) -> None:
        self._open_position_count += 1
        self._open_symbols.add(symbol)

    # ────────────────────────────────────────────────────────── pause / resume

    def pause(self, reason: str = "") -> None:
        self._paused = True
        self._pause_reason = reason
        logger.warning("[risk] PAUSED — reason: %s", reason)

    def resume(self) -> None:
        self._paused = False
        self._pause_reason = ""
        logger.info("[risk] RESUMED")

    def reset_daily(self) -> None:
        """Apelat la midnight reset de AutomationEngine."""
        self._daily_start_equity = self._equity
        self._daily_pnl = 0.0
        logger.info("[risk] Daily counters reset")
