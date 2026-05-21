"""
AutomationEngine — scheduler + event emitter pentru trading automat.

CHANGELOG:
  🔴 FIX A       : risk.update_equity() apelat dupa place_order() si dupa close pozitie
  🟠 FIX B       : dublu assignment 'order_timeout = cfg = get_settings()' eliminat.
  🔴 FIX #1 (prev): _placed_ids TTL-based (Dict[str, float] + monotonic())
  🔴 FIX #3 (prev): realized_pnl calculat corect la on_trade_closed()
  🔴 FIX #1 (curr): pos.side normalization — check 'SHORT'|'SELL' pentru Futures
  🟠 FIX #2 (prev): _manage_open_positions() foloseste portfolio.price_cache (property public)
  🟠 FIX #3 (curr): getattr(cfg, 'order_timeout_seconds', 15) → cfg.order_timeout_seconds
  🟡 FIX #4 (prev): _seen_candles cleanup periodic la fiecare 1000 ticks.
  🟡 FIX #5 (prev): _midnight_reset() face evict smart pe seen_candles (TTL-based)
  🟡 FIX #2 (curr): _midnight_reset() trim cap la 20 — previne acumulare la interval=60m
  🟡 FIX #5 (curr): _seen_candles init consistent cu deque(maxlen=_SEEN_CANDLES_MAXLEN)
  🟡 FIX #6 (prev): place_order() wrapped cu asyncio.wait_for(cfg.order_timeout_seconds)
  🔴 FIX REVIEW #1: klines fetched cu cfg.primary_timeframe in loc de "1m" hardcodat
  🟠 FIX REVIEW #4: on_position_opened() apelat INAINTE de place_order cu rollback pe esec
  🟡 REFACTOR     : rollback foloseste risk.rollback_position_opened() — encapsulare corecta
  🔴 FIX TRADE #1  : update_trailing_stop() apelat in _manage_open_positions() la fiecare tick
  🔴 FIX TRADE #2  : evaluate_exit() primeste opposite_signal generat in _process_symbol()
  🟠 FIX TRADE #3  : update_position_after_tp1() apelat si salvat in portfolio dupa TP1 hit
  🟠 FIX TRADE #4  : semnal curent per simbol pastrat in _latest_signals pentru opposite_signal
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable, Coroutine, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import get_settings
from backend.models import StrategySignal
from backend.core.trade_logic import ExitDecision, update_position_after_tp1, update_trailing_stop

logger = logging.getLogger(__name__)

_PLACED_TTL: float = 3600.0
_SEEN_CANDLES_MAXLEN = 200
_SEEN_CANDLES_KEEP_MAX = 20


class EventEmitter:
    """Simple async event emitter pentru lifecycle hooks."""

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable[..., Coroutine]]] = {}

    def on(self, event: str, handler: Callable[..., Coroutine]) -> None:
        self._handlers.setdefault(event, []).append(handler)

    async def emit(self, event: str, payload: Any = None) -> None:
        for handler in self._handlers.get(event, []):
            try:
                await handler(payload)
            except Exception as exc:
                logger.warning("EventEmitter[%s] handler error: %s", event, exc)


class AutomationEngine:
    """
    Ruleaza strategiile la intervale configurabile si gestioneaza ciclul
    complet semnal → validare risc → executie → monitorizare pozitie.
    """

    def __init__(
        self,
        strategy,
        risk_manager,
        execution_engine,
        portfolio_engine,
        binance_client,
        journal=None,
        telegram=None,
        ws_broadcast=None,
    ) -> None:
        self._strategy       = strategy
        self._risk           = risk_manager
        self._execution      = execution_engine
        self._portfolio      = portfolio_engine
        self._client         = binance_client
        self._journal        = journal
        self._telegram       = telegram
        self._ws_broadcast   = ws_broadcast

        cfg = get_settings()
        self._cfg                    = cfg
        self._symbols: List[str]     = cfg.symbol_whitelist
        self._interval_minutes       = cfg.automation_interval_minutes
        self._max_recent_signals     = 200

        self._scheduler      = AsyncIOScheduler()
        self._running        = False
        self._recent_signals: List[Dict[str, Any]] = []
        self._tick_count     = 0

        self._placed_ids: Dict[str, float] = {}
        self._seen_candles: Dict[str, deque] = {}

        # 🟠 FIX TRADE #4: ultimul semnal per simbol — folosit ca opposite_signal in _manage_open_positions()
        self._latest_signals: Dict[str, StrategySignal] = {}

        self._events = EventEmitter()

    # ─────────────────────────────────────────────────────── lifecycle

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._scheduler.add_job(
            self._tick,
            trigger="interval",
            minutes=self._interval_minutes,
            id="automation_tick",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            self._midnight_reset,
            trigger="cron",
            hour=0,
            minute=0,
            id="midnight_reset",
            replace_existing=True,
        )
        self._scheduler.start()
        self._running = True
        logger.info(
            "[automation] started — symbols=%s interval=%dm",
            self._symbols,
            self._interval_minutes,
        )

    async def stop(self) -> None:
        if not self._running:
            return
        self._scheduler.shutdown(wait=False)
        self._running = False
        logger.info("[automation] stopped")

    # ─────────────────────────────────────────────────────── main tick

    async def _tick(self) -> None:
        """Executat la fiecare interval. Proceseaza toate simbolurile."""
        self._tick_count += 1

        if not self._portfolio.is_ready:
            logger.debug("[automation] tick skipped — portfolio not reconciled")
            return
        if self._risk.is_paused:
            logger.debug("[automation] tick skipped — risk paused")
            return

        if self._tick_count % 1000 == 0:
            active = set(self._cfg.symbol_whitelist)
            stale = [s for s in list(self._seen_candles) if s not in active]
            for s in stale:
                del self._seen_candles[s]
            if stale:
                logger.debug("[automation] evicted stale seen_candles keys: %s", stale)

        for symbol in self._symbols:
            try:
                await self._process_symbol(symbol)
            except Exception as exc:
                logger.error("[automation] _process_symbol(%s) error: %s", symbol, exc)

        await self._manage_open_positions()

    async def _process_symbol(self, symbol: str) -> None:
        """Genereaza semnal, valideaza risc, executa daca OK."""
        timeframe = self._cfg.primary_timeframe
        try:
            klines = await self._client.get_klines(symbol, interval=timeframe, limit=100)
        except Exception as exc:
            logger.warning("[automation] klines fetch failed for %s: %s", symbol, exc)
            return

        signal: Optional[StrategySignal] = await asyncio.to_thread(
            self._strategy.compute, klines
        )

        # 🟠 FIX TRADE #4: salveaza cel mai recent semnal per simbol
        # Folosit de _manage_open_positions() ca potential opposite_signal
        if signal is not None and signal.action != "HOLD":
            self._latest_signals[symbol] = signal

        if signal is None or signal.action == "HOLD":
            return

        candle_key = str(getattr(signal, "candle_open_time", "") or "")
        if candle_key:
            if symbol not in self._seen_candles:
                self._seen_candles[symbol] = deque(maxlen=_SEEN_CANDLES_MAXLEN)
            if candle_key in self._seen_candles[symbol]:
                logger.debug(
                    "[automation] duplicate candle signal skipped: %s %s",
                    symbol,
                    candle_key,
                )
                return
            self._seen_candles[symbol].append(candle_key)

        veto = self._risk.check_signal(signal)
        if veto.value != "PASS":
            logger.info(
                "[automation] signal REJECTED: symbol=%s action=%s reason=%s",
                symbol,
                signal.action,
                veto.value,
            )
            self._add_recent_signal(signal, status=f"rejected:{veto.value}")
            await self._events.emit("signal_rejected", {"signal": signal, "reason": veto.value})
            return

        signal_id = f"{symbol}:{signal.action}:{candle_key}"
        if self._is_duplicate(signal_id):
            logger.debug("[automation] idempotency skip (TTL): %s", signal_id)
            return
        self._register_placed_id(signal_id)

        try:
            await self._execute_signal(signal)
            self._add_recent_signal(signal, status="accepted")
            await self._events.emit("signal_created", signal)
        except Exception as exc:
            logger.error(
                "[automation] execute_signal failed: symbol=%s err=%s", symbol, exc
            )
            self._add_recent_signal(signal, status=f"error:{exc}")

    async def _execute_signal(self, signal: StrategySignal) -> None:
        """Plaseaza ordinul si notifica risk manager."""
        cfg = get_settings()
        equity = self._portfolio.get_equity()
        qty = 0.0
        if hasattr(self._execution, "calc_position_size"):
            qty = self._execution.calc_position_size(
                equity=equity,
                entry_price=signal.entry_price or 0,
                stop_loss=signal.stop_loss,
                risk_pct=cfg.risk_per_trade,
            )

        if qty <= 0:
            logger.warning("[automation] calc_position_size returned 0 for %s", signal.symbol)
            return

        order_timeout = cfg.order_timeout_seconds

        self._risk.on_position_opened(signal.symbol)
        order_placed = False
        try:
            await asyncio.wait_for(
                self._execution.place_order(
                    symbol=signal.symbol,
                    side="BUY" if signal.action == "BUY" else "SELL",
                    quantity=qty,
                    order_type=signal.entry_type.upper() if signal.entry_type else "MARKET",
                    price=signal.entry_price,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit_1,
                ),
                timeout=order_timeout,
            )
            order_placed = True
        except asyncio.TimeoutError:
            logger.error(
                "[automation] place_order TIMEOUT (%ds) for %s — order may not have been placed!",
                order_timeout,
                signal.symbol,
            )
        finally:
            if not order_placed:
                self._risk.rollback_position_opened(signal.symbol)
                return

        equity_after = self._portfolio.get_equity()
        self._risk.update_equity(equity_after)
        logger.debug(
            "[automation] risk equity synced after entry: symbol=%s equity=%.2f",
            signal.symbol,
            equity_after,
        )

    async def _manage_open_positions(self) -> None:
        """Evalueaza exit logic pentru toate pozitiile deschise."""
        positions = self._portfolio.get_positions()
        if not positions:
            return

        for pos in positions:
            try:
                price = self._portfolio.price_cache.get(pos.symbol)
                if not price:
                    continue

                # 🔴 FIX TRADE #1: update trailing stop la fiecare tick, inainte de evaluate_exit()
                # Fara acest apel, trailing stop-ul era setat la intrare si nu se misca niciodata.
                pos = update_trailing_stop(pos, price)

                # 🟠 FIX TRADE #2: paseaza opposite_signal la evaluate_exit()
                # Anterior: evaluate_exit(pos, price) fara semnal opus → SIGNAL_CLOSE niciodata trigger.
                opposite_signal = self._latest_signals.get(pos.symbol)
                # Un semnal e "opus" doar daca directia e contrara pozitiei deschise
                if opposite_signal is not None:
                    from backend.models import Action
                    pos_is_long = pos.side.upper() in ("BUY", "LONG")
                    is_opposite = (
                        (pos_is_long and opposite_signal.action == Action.SELL) or
                        (not pos_is_long and opposite_signal.action == Action.BUY)
                    )
                    if not is_opposite:
                        opposite_signal = None

                exit_reason, close_fraction = (None, 0.0)
                if hasattr(self._execution, "evaluate_exit"):
                    exit_reason, close_fraction = self._execution.evaluate_exit(
                        position=pos, current_price=price, opposite_signal=opposite_signal
                    )

                if exit_reason and close_fraction > 0:
                    logger.info(
                        "[automation] exit triggered: %s reason=%s fraction=%.2f",
                        pos.symbol,
                        exit_reason,
                        close_fraction,
                    )
                    close_qty = round(pos.quantity * close_fraction, 8)
                    side = "SELL" if pos.side == "BUY" else "BUY"

                    cfg = get_settings()
                    order_timeout = cfg.order_timeout_seconds
                    try:
                        await asyncio.wait_for(
                            self._execution.place_order(
                                symbol=pos.symbol,
                                side=side,
                                quantity=close_qty,
                                order_type="MARKET",
                            ),
                            timeout=order_timeout,
                        )
                    except asyncio.TimeoutError:
                        logger.error(
                            "[automation] exit place_order TIMEOUT (%ds) for %s",
                            order_timeout,
                            pos.symbol,
                        )
                        continue

                    if exit_reason == ExitDecision.TP1:
                        # 🟠 FIX TRADE #3: TP1 → apeleaza update_position_after_tp1() si salveaza in portfolio
                        # Anterior: tp1_hit si SL breakeven nu erau niciodata persistate.
                        # La restart/reconciliere, sistemul incerca TP1 din nou pe aceeasi pozitie.
                        updated = update_position_after_tp1(pos, price)
                        self._portfolio.update_position(updated)
                        logger.info(
                            "[automation] TP1 hit — breakeven set: symbol=%s new_sl=%.4f",
                            pos.symbol, updated.stop_loss,
                        )
                        equity_after = self._portfolio.get_equity()
                        self._risk.update_equity(equity_after)
                        await self._events.emit(
                            "tp_hit",
                            {"symbol": pos.symbol, "reason": exit_reason, "fraction": close_fraction},
                        )

                    elif close_fraction >= 1.0:
                        self._portfolio.remove_position(pos.symbol)

                        is_short = pos.side.upper() in ("SELL", "SHORT")
                        realized_pnl = (price - pos.entry_price) * close_qty
                        if is_short:
                            realized_pnl *= -1

                        self._risk.on_trade_closed(pnl=realized_pnl, symbol=pos.symbol)

                        equity_after = self._portfolio.get_equity()
                        self._risk.update_equity(equity_after)
                        logger.info(
                            "[automation] position CLOSED: %s realized_pnl=%.4f reason=%s",
                            pos.symbol, realized_pnl, exit_reason,
                        )
                        await self._events.emit(
                            "position_closed",
                            {"symbol": pos.symbol, "pnl": realized_pnl},
                        )

                    else:
                        # TP2 sau alte close partiale (nu TP1 si nu full close)
                        updated = pos.model_copy(
                            update={"quantity": pos.quantity - close_qty}
                        )
                        self._portfolio.update_position(updated)

                        equity_after = self._portfolio.get_equity()
                        self._risk.update_equity(equity_after)

                        await self._events.emit(
                            "tp_hit",
                            {"symbol": pos.symbol, "reason": exit_reason, "fraction": close_fraction},
                        )

                else:
                    # Niciun exit — dar trailing stop-ul a fost modificat in memorie;
                    # salvam pozitia actualizata in portfolio pentru persistenta.
                    self._portfolio.update_position(pos)

            except Exception as exc:
                logger.error(
                    "[automation] _manage_open_positions error for %s: %s", pos.symbol, exc
                )

    async def _midnight_reset(self) -> None:
        self._risk.reset_daily()

        keep = min(max(2, self._interval_minutes * 2), _SEEN_CANDLES_KEEP_MAX)
        for symbol, dq in self._seen_candles.items():
            while len(dq) > keep:
                dq.popleft()

        now = monotonic()
        self._placed_ids = {
            k: t for k, t in self._placed_ids.items() if now - t <= _PLACED_TTL
        }
        logger.info(
            "[automation] midnight reset — seen_candles trimmed to last %d per symbol", keep
        )

    def _register_placed_id(self, signal_id: str) -> None:
        now = monotonic()
        expired = [k for k, t in self._placed_ids.items() if now - t > _PLACED_TTL]
        for k in expired:
            del self._placed_ids[k]
        self._placed_ids[signal_id] = now

    def _is_duplicate(self, signal_id: str) -> bool:
        t = self._placed_ids.get(signal_id)
        if t is None:
            return False
        if monotonic() - t > _PLACED_TTL:
            del self._placed_ids[signal_id]
            return False
        return True

    def _add_recent_signal(self, signal: StrategySignal, status: str) -> None:
        entry = {
            **signal.model_dump(),
            "signal_status": status,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._recent_signals.append(entry)
        if len(self._recent_signals) > self._max_recent_signals:
            self._recent_signals = self._recent_signals[-self._max_recent_signals :]

    def get_recent_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._recent_signals[-limit:]

    def on(self, event: str, handler: Callable[..., Coroutine]) -> None:
        self._events.on(event, handler)
