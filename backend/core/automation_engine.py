"""
automation_engine.py – APScheduler-based signal loop, candle deduplication,
async EventEmitter, position management loop.

FIX D: _recent_signals se populeaza imediat dupa risk-check (status=accepted)
        si dupa fill (status=filled). Anterior era loggat DOAR la FILLED —
        deci pe cont gol apareau "No signals".
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import get_settings
from backend.core.trade_logic import (
    ExitDecision,
    calc_position_size,
    evaluate_exit,
    should_enter_long,
    should_enter_short,
    update_position_after_tp1,
)
from backend.models import Action, RiskVeto

log = structlog.get_logger(__name__)
settings = get_settings()


# ── Async EventEmitter ───────────────────────────────────────────────────────────────────────

class EventEmitter:
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)

    def on(self, event: str, handler: Callable) -> None:
        self._handlers[event].append(handler)

    async def emit(self, event: str, payload: Any = None) -> None:
        for handler in self._handlers.get(event, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(payload)
                else:
                    handler(payload)
            except Exception as exc:
                log.error("event_handler_error", event=event, error=str(exc))


# ── Automation Engine ──────────────────────────────────────────────────────────────

class AutomationEngine:
    """
    Scheduler care ruleaza strategy scans si position checks la intervale configurabile.
    Anti-duplicate: un singur semnal per simbol per candle_open_time.
    """

    def __init__(
        self,
        strategy,
        ohlcv,
        risk,
        execution,
        portfolio,
        journal=None,
        telegram=None,
        ws_broadcast=None,
    ):
        self._strategy  = strategy
        self._ohlcv     = ohlcv
        self._risk      = risk
        self._exec      = execution
        self._portfolio = portfolio
        self._journal   = journal
        self._telegram  = telegram
        self._ws        = ws_broadcast
        self.emitter    = EventEmitter()
        self._scheduler = AsyncIOScheduler()
        self._processed_candles: Dict[str, Set[int]] = defaultdict(set)
        self._recent_signals: List[Any] = []   # toate semnalele, cu status
        self.running    = False

    async def start(self) -> None:
        if self.running:
            return
        interval = settings.scan_interval_seconds
        self._scheduler.add_job(
            self._scan_loop, "interval", seconds=interval, id="scan_loop"
        )
        self._scheduler.add_job(
            self._position_loop, "interval",
            seconds=max(interval // 2, 5), id="pos_loop"
        )
        self._scheduler.add_job(
            self._reconcile_loop, "interval", seconds=300, id="reconcile_loop"
        )
        self._scheduler.start()
        self.running = True
        log.info("automation_started", interval_s=interval)

    async def stop(self) -> None:
        if not self.running:
            return
        self._scheduler.shutdown(wait=False)
        self.running = False
        log.info("automation_stopped")

    def get_recent_signals(self, limit: int = 50) -> List[Any]:
        """Ultimele N semnale (cel mai recent primul), indiferent de status."""
        return self._recent_signals[-limit:][::-1]

    # ── helpers ───────────────────────────────────────────────────────────────────────

    def _push_signal(self, signal: Any, status: str = "accepted") -> None:
        """Adauga un semnal in _recent_signals cu status atasat."""
        entry = signal.model_dump() if hasattr(signal, "model_dump") else dict(signal)
        entry["signal_status"] = status
        self._recent_signals.append(entry)
        if len(self._recent_signals) > 500:
            self._recent_signals = self._recent_signals[-500:]

    # ── Scan Loop ───────────────────────────────────────────────────────────────────────

    async def _scan_loop(self) -> None:
        if not self._portfolio.is_ready:
            log.warning("scan_skipped_not_ready")
            return

        for symbol in settings.symbol_whitelist:
            try:
                klines = await self._ohlcv.get(symbol, settings.primary_timeframe, limit=100)
                if not klines:
                    continue

                from backend.core.strategy_engine import OHLCV
                ohlcv = OHLCV(klines)
                signal = await self._strategy.compute(ohlcv)
                if signal is None:
                    continue

                # ── Anti-duplicate per candle ──────────────────────────────
                if self._is_duplicate(symbol, signal.candle_open_time):
                    log.debug("signal_duplicate_candle", symbol=symbol)
                    await self.emitter.emit("signal_rejected", {"reason": "duplicate_candle", "symbol": symbol})
                    continue

                # ── Risk check ────────────────────────────────────────────
                veto = self._risk.check_signal(signal)
                if veto != RiskVeto.OK:
                    log.info("signal_rejected_risk", symbol=symbol, veto=veto.value)
                    self._push_signal(signal, status=f"rejected:{veto.value}")
                    await self.emitter.emit("signal_rejected", {"reason": veto.value, "symbol": symbol})
                    if self._journal:
                        await self._journal.log_signal(signal)
                    continue

                # ── Trade logic filter ────────────────────────────────────
                equity = self._risk.equity
                price  = ohlcv.last_close

                if signal.action == Action.BUY:
                    ok, reason = should_enter_long(signal, price, equity)
                elif signal.action == Action.SELL:
                    ok, reason = should_enter_short(signal, price, equity)
                else:
                    ok, reason = False, "HOLD/CLOSE"

                if not ok:
                    log.info("signal_rejected_logic", symbol=symbol, reason=reason)
                    self._push_signal(signal, status=f"rejected:{reason}")
                    continue

                # ── Semnal acceptat — loggat IMEDIAT ────────────────────
                self._push_signal(signal, status="accepted")
                self._mark_processed(symbol, signal.candle_open_time)
                await self.emitter.emit("signal_created", signal.model_dump())
                if self._journal:
                    await self._journal.log_signal(signal)
                if self._telegram:
                    await self._telegram.alert_signal(signal)

                # ── Executie ──────────────────────────────────────────────
                qty = calc_position_size(
                    equity=equity,
                    entry=price,
                    stop_loss=signal.stop_loss,
                    market_mode=signal.market_mode,
                    leverage=settings.futures_leverage,
                )

                order = await self._exec.place_market_order(signal, qty)

                if order and order.status.value in ("FILLED", "PARTIALLY_FILLED"):
                    # Actualizeaza statusul semnalului la filled
                    for s in reversed(self._recent_signals):
                        if isinstance(s, dict) and s.get("symbol") == symbol:
                            s["signal_status"] = "filled"
                            s["filled_order_id"] = str(order.order_id)
                            break
                    await self.emitter.emit("order_filled", order.model_dump())

            except Exception as exc:
                log.error("scan_loop_error", symbol=symbol, error=str(exc))

    # ── Position Management Loop ─────────────────────────────────────────────────────

    async def _position_loop(self) -> None:
        positions = self._portfolio.get_positions()
        for position in positions:
            symbol = position.symbol
            try:
                klines = await self._ohlcv.get(symbol, settings.primary_timeframe, limit=5)
                if not klines:
                    continue
                price = float(klines[-2][4]) if len(klines) >= 2 else float(klines[-1][4])

                reason, fraction = evaluate_exit(position, price)
                if reason == ExitDecision.NONE:
                    continue

                if reason == ExitDecision.TP1:
                    updated = update_position_after_tp1(position, price)
                    self._portfolio.update_position(updated)
                    position = updated
                    await self.emitter.emit("tp1_hit", {"symbol": symbol, "price": price})

                close_qty  = position.quantity * fraction
                close_side = "SELL" if str(position.side).upper() in ("BUY", "LONG") else "BUY"
                close_qty  = self._exec.normalize_quantity(symbol, close_qty)

                if close_qty > 0:
                    if not settings.dry_run:
                        await self._ohlcv._client.place_market_order(
                            symbol=symbol, side=close_side, quantity=close_qty
                        )
                    else:
                        log.info(
                            "dry_run_close", symbol=symbol,
                            reason=str(reason), qty=close_qty, price=price,
                        )

                if fraction >= 1.0:
                    self._portfolio.remove_position(symbol)
                    self._risk.position_closed(symbol)
                    await self.emitter.emit(
                        "position_closed",
                        {"symbol": symbol, "reason": str(reason), "price": price},
                    )
                    if self._telegram:
                        await self._telegram.send_alert(
                            f"🔴 Position closed: {symbol} | {reason} @ {price}"
                        )
                else:
                    position.quantity -= close_qty
                    self._portfolio.update_position(position)

            except Exception as exc:
                log.error("position_loop_error", symbol=symbol, error=str(exc))

    async def _reconcile_loop(self) -> None:
        try:
            result = await self._portfolio.reconcile()
            if result.drift_detected:
                await self.emitter.emit("drift_detected", result.model_dump())
                if self._telegram:
                    await self._telegram.send_alert(
                        "⚠️ Drift detected during periodic reconciliation"
                    )
        except Exception as exc:
            log.error("reconcile_loop_error", error=str(exc))

    # ── Deduplication helpers ───────────────────────────────────────────────────────

    def _is_duplicate(self, symbol: str, candle_time: Optional[int]) -> bool:
        if candle_time is None:
            return False
        return candle_time in self._processed_candles[symbol]

    def _mark_processed(self, symbol: str, candle_time: Optional[int]) -> None:
        if candle_time is None:
            return
        cache = self._processed_candles[symbol]
        cache.add(candle_time)
        if len(cache) > 100:
            cache.discard(min(cache))
