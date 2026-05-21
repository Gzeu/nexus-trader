"""
RiskManager — gatekeeper pentru toate ordinele.

CHANGELOG:
  🟡 FIX #4 (prev) : peak_equity, consecutive_losses, daily_pnl, max_drawdown_seen expuse
                     ca properties publice.
  🟡 FIX #4 (curr) : reset_daily() are guard explicit — nu reseteaza daily_start_equity
                     daca equity == 0 (ex: Binance offline la midnight).
  🟡 FIX D         : _open_position_count derivat autoritar din len(_open_symbols).
                     Anterior: count += 1 independent de set.add() → count=2 pe acelasi simbol
                     daca on_position_opened() era apelat dublu.
                     Acum: count = len(set) in ambele metode — sursa unica de adevar.
  🟠 FIX REVIEW #3 : resume() reseteaza consecutive_losses la 0.
                     Anterior: dupa pause/resume, consecutive_losses pastra valoarea veche
                     → system raman blocat imediat dupa resume.
  🟡 FIX REVIEW #6 : VETO_VOLATILITY implementat in check_signal() folosind atr_pct din
                     metadata semnalului. Configurat prin MAX_ATR_PCT in settings.
  🟡 REFACTOR      : rollback_position_opened() adaugat ca method public.
                     Inlocuieste accesul direct la _open_symbols din AutomationEngine.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from backend.config import get_settings
from backend.models import RiskVeto, StrategySignal

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Verifica fiecare semnal inainte de executie.
    Toate regulile de risc sunt configurabile din Settings.
    """

    def __init__(self) -> None:
        cfg = get_settings()

        self._paused: bool = False
        self._pause_reason: str = ""
        self._equity: float = 0.0
        self._peak_equity: float = 0.0
        self._daily_start_equity: float = 0.0
        self._daily_pnl: float = 0.0
        self._consecutive_losses: int = 0
        self._last_loss_time: Optional[datetime] = None
        self._max_drawdown_seen: float = 0.0
        self._open_symbols: set[str] = set()

        self._max_positions       = cfg.max_open_positions
        self._risk_per_trade      = cfg.risk_per_trade
        self._max_daily_loss      = cfg.max_daily_loss_pct
        self._max_drawdown        = cfg.max_drawdown_pct
        self._min_rr              = cfg.min_risk_reward
        self._cooldown_minutes    = cfg.sl_cooldown_minutes
        self._max_consec_losses   = cfg.max_consecutive_losses
        # 🟡 FIX REVIEW #6: prag ATR% pentru veto volatilitate (default 5%)
        self._max_atr_pct: float  = getattr(cfg, "max_atr_pct", 0.05)

    # ─────────────────────────────────────────────────────── public properties

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def open_position_count(self) -> int:
        """🟡 FIX D: sursa unica de adevar — derivat din set, nu mentinut separat."""
        return len(self._open_symbols)

    @property
    def peak_equity(self) -> float:
        return self._peak_equity

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def max_drawdown_seen(self) -> float:
        return self._max_drawdown_seen

    # ─────────────────────────────────────────────────────────── equity sync

    def update_equity(self, equity: float) -> None:
        """Apelat de AutomationEngine dupa fiecare order fill sau reconciliere."""
        self._equity = equity
        if equity > self._peak_equity:
            self._peak_equity = equity

        if self._daily_start_equity > 0:
            self._daily_pnl = equity - self._daily_start_equity
        else:
            self._daily_start_equity = equity

        if self._peak_equity > 0:
            current_dd = 1.0 - (equity / self._peak_equity)
            if current_dd > self._max_drawdown_seen:
                self._max_drawdown_seen = current_dd
            if current_dd >= self._max_drawdown:
                if not self._paused:
                    self.pause(
                        reason=f"max_drawdown_breach: {current_dd:.2%} >= {self._max_drawdown:.2%}"
                    )

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

        if self._peak_equity > 0:
            current_dd = 1.0 - (self._equity / self._peak_equity)
            if current_dd >= self._max_drawdown:
                return RiskVeto.MAX_DRAWDOWN

        if self._daily_start_equity > 0:
            daily_loss_pct = -self._daily_pnl / self._daily_start_equity
            if daily_loss_pct >= self._max_daily_loss:
                return RiskVeto.DAILY_LOSS

        if self.open_position_count >= self._max_positions:
            return RiskVeto.MAX_POSITIONS

        if signal.symbol in self._open_symbols:
            return RiskVeto.SYMBOL_ALREADY_OPEN

        if self._last_loss_time is not None:
            elapsed = (
                datetime.now(timezone.utc) - self._last_loss_time
            ).total_seconds() / 60
            if elapsed < self._cooldown_minutes:
                return RiskVeto.COOLDOWN

        if self._consecutive_losses >= self._max_consec_losses:
            return RiskVeto.CONSECUTIVE_LOSSES

        if signal.stop_loss is not None and signal.take_profit_1 is not None and signal.entry_price is not None:
            risk   = abs(signal.entry_price - signal.stop_loss)
            reward = abs(signal.take_profit_1 - signal.entry_price)
            if risk > 0 and (reward / risk) < self._min_rr:
                return RiskVeto.MIN_RR

        # 🟡 FIX REVIEW #6: VETO_VOLATILITY — atr_pct injectat de _make_signal() in metadata
        atr_pct = signal.metadata.get("atr_pct") if signal.metadata else None
        if atr_pct is not None and self._max_atr_pct > 0 and atr_pct > self._max_atr_pct:
            logger.info(
                "[risk] VETO_VOLATILITY: symbol=%s atr_pct=%.4f > max=%.4f",
                signal.symbol, atr_pct, self._max_atr_pct,
            )
            return RiskVeto.VOLATILITY

        return RiskVeto.PASS

    # ──────────────────────────────────────────────────── trade outcome sync

    def on_trade_closed(self, pnl: float, symbol: str) -> None:
        """Apelat de AutomationEngine la inchiderea unui trade cu realized_pnl."""
        self._open_symbols.discard(symbol)

        if pnl < 0:
            self._consecutive_losses += 1
            self._last_loss_time = datetime.now(timezone.utc)
            logger.info(
                "[risk] trade closed LOSS: symbol=%s pnl=%.4f consecutive_losses=%d open=%d",
                symbol, pnl, self._consecutive_losses, self.open_position_count,
            )
        else:
            self._consecutive_losses = 0
            logger.info(
                "[risk] trade closed WIN: symbol=%s pnl=%.4f open=%d",
                symbol, pnl, self.open_position_count,
            )

    def on_position_opened(self, symbol: str) -> None:
        """🟡 FIX D: set.add() e idempotent — count e derivat din len(set), nu incrementat."""
        self._open_symbols.add(symbol)
        logger.debug(
            "[risk] position opened: symbol=%s open_count=%d",
            symbol, self.open_position_count,
        )

    def rollback_position_opened(self, symbol: str) -> None:
        """
        🟡 REFACTOR: Rollback explicit daca place_order a esuat dupa on_position_opened().

        Inlocuieste accesul direct la _open_symbols din apelatori externi (AutomationEngine).
        Metoda e idempotenta — discard() pe un simbol absent e no-op.
        """
        self._open_symbols.discard(symbol)
        logger.warning(
            "[risk] rollback_position_opened: symbol=%s open_count=%d",
            symbol, self.open_position_count,
        )

    # ────────────────────────────────────────────────────────── pause / resume

    def pause(self, reason: str = "") -> None:
        self._paused = True
        self._pause_reason = reason
        logger.warning("[risk] PAUSED — reason: %s", reason)

    def resume(self) -> None:
        self._paused = False
        self._pause_reason = ""
        # 🟠 FIX REVIEW #3: reseteaza consecutive_losses la resume.
        # Anterior: consecutive_losses pastra valoarea veche dupa pause/resume
        # → sistem blocat imediat dupa resume daca max_consecutive_losses era deja atins.
        self._consecutive_losses = 0
        logger.info("[risk] RESUMED — consecutive_losses reset to 0")

    def reset_daily(self) -> None:
        """
        Apelat la midnight reset de AutomationEngine.

        🟡 FIX #4: Guard explicit — nu reseteaza daily_start_equity
        daca equity == 0 (ex: Binance offline, update_equity() nu a fost apelat).
        """
        if self._equity > 0:
            self._daily_start_equity = self._equity
        else:
            logger.warning(
                "[risk] reset_daily: equity=0, _daily_start_equity NOT updated "
                "(Binance offline?). Keeping previous value=%.2f",
                self._daily_start_equity,
            )
        self._daily_pnl = 0.0
        logger.info(
            "[risk] Daily counters reset — equity=%.2f daily_start=%.2f",
            self._equity,
            self._daily_start_equity,
        )
