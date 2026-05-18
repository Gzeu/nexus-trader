"""
automation_engine.py – APScheduler signal loop, candle deduplication,
async EventEmitter, position management loop.

Fixes applied:
- start() / stop() are SYNCHRONOUS — APScheduler is not async-aware.
  Callers must NOT await these methods.
- strategy accepts Union[BaseStrategy, Dict[str, BaseStrategy]]
  Dict keys are symbol names; "*" is the fallback for all symbols.
- _position_loop selects correct Binance client based on position.market_mode
- _mark_processed evicts oldest 10% when cache exceeds 100 entries
  (was only evicting 1 entry → O(n) performance degradation)
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Union

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import get_settings
from backend.core.trade_logic import ExitDecision, evaluate_exit, update_position_after_tp1
from backend.models import Action, MarketMode, OrderSide, RiskVeto

log = structlog.get_logger(__name__)
settings = get_settings()


# ── Async EventEmitter ──────────────────────────────────────────────

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


# ── Automation Engine ─────────────────────────────────────────────

class AutomationEngine:
    """
    Scheduler that runs strategy scans and position checks on configurable intervals.

    strategy:
      - Single BaseStrategy instance → applied to ALL symbols in whitelist
      - Dict[str, BaseStrategy] → per-symbol strategy; use key "*" as fallback

    Anti-duplicate: one signal per symbol per candle_open_time.
    """

    def __init__(
        self,
        strategy: Union[Any, Dict[str, Any]],
        portfolio_engine,
        risk_manager,
        execution_engine,
        spot_client,
        futures_client=None,
        ws_broadcast=None,
        journal=None,
        telegram=None,
    ):
        self._strategy = strategy
        self._portfolio = portfolio_engine
        self._risk = risk_manager
        self._exec = execution_engine
        self._spot = spot_client
        self._futures = futures_client
        self._ws = ws_broadcast
        self._journal = journal
        self._telegram = telegram
        self.emitter = EventEmitter()
        self._scheduler = AsyncIOScheduler()
        self._processed_candles: Dict[str, Set[int]] = defaultdict(set)
        self.running = False

    # ── Lifecycle (SYNCHRONOUS — do NOT await) ──────────────────────────

    def start(self) -> None:
        """
        Start the APScheduler. Synchronous — APScheduler.start() is NOT a coroutine.
        Call as: state.automation.start()  (NO await)
        """
        interval = settings.scan_interval_seconds
        self._scheduler.add_job(
            self._scan_loop, "interval", seconds=interval,
            id="scan_loop", max_instances=1, coalesce=True,
        )
        self._scheduler.add_job(
            self._position_loop, "interval", seconds=max(interval // 2, 5),
            id="pos_loop", max_instances=1, coalesce=True,
        )
        self._scheduler.add_job(
            self._reconcile_loop, "interval", seconds=300,
            id="reconcile_loop", max_instances=1, coalesce=True,
        )
        self._scheduler.start()   # synchronous
        self.running = True
        log.info("automation_started", interval_s=interval)

    def stop(self) -> None:
        """Stop the scheduler. Synchronous — do NOT await."""
        self._scheduler.shutdown(wait=False)
        self.running = False
        log.info("automation_stopped")

    # ── Strategy resolution ────────────────────────────────────────────

    def _get_strategy(self, symbol: str):
        """Return strategy for symbol. Falls back to '*' key or single instance."""
        if isinstance(self._strategy, dict):
            return self._strategy.get(symbol) or self._strategy.get("*")
        return self._strategy

    def _client_for_mode(self, market_mode: MarketMode):
        """Select correct Binance client based on market mode."""
        if market_mode == MarketMode.FUTURES and self._futures:
            return self._futures
        return self._spot

    # ── Scan Loop ──────────────────────────────────────────────────────────

    async def _scan_loop(self) -> None:
        if not self._portfolio.is_ready:
            log.warning("scan_skipped_not_ready")
            return

        for symbol in settings.symbol_whitelist:
            strategy = self._get_strategy(symbol)
            if strategy is None:
                log.warning("no_strategy_for_symbol", symbol=symbol)
                continue
            try:
                from backend.core.strategy_engine import OHLCV
                klines = await self._spot.get_klines(
                    symbol, settings.primary_timeframe, limit=100
                )
                if not klines:
                    continue

                ohlcv = OHLCV(klines)
                signal = await strategy.compute(ohlcv)
                if signal is None:
                    continue

                if self._is_duplicate(symbol, signal.candle_open_time):
                    log.debug("signal_duplicate_candle", symbol=symbol, time=signal.candle_open_time)
                    await self.emitter.emit(
                        "signal_rejected", {"reason": "duplicate_candle", "symbol": symbol}
                    )
                    continue

                veto = self._risk.check_signal(signal)
                if veto != RiskVeto.OK:
                    log.info("signal_rejected_risk", symbol=symbol, veto=veto.value)
                    await self.emitter.emit(
                        "signal_rejected", {"reason": veto.value, "symbol": symbol}
                    )
                    continue

                from backend.core.trade_logic import (
                    calc_position_size,
                    should_enter_long,
                    should_enter_short,
                )

                equity = self._risk.equity
                price = ohlcv.last_close

                if signal.action == Action.BUY:
                    ok, reason = should_enter_long(signal, price, equity)
                elif signal.action == Action.SELL:
                    ok, reason = should_enter_short(signal, price, equity)
                else:
                    ok, reason = False, "HOLD/CLOSE"

                if not ok:
                    log.info("signal_rejected_logic", symbol=symbol, reason=reason)
                    continue

                qty = calc_position_size(equity, price, signal.stop_loss)
                order = await self._exec.place_market_order(signal, qty)

                if order and order.status.value in ("FILLED", "PARTIALLY_FILLED"):
                    self._mark_processed(symbol, signal.candle_open_time)
                    await self.emitter.emit("signal_created", signal.model_dump())
                    if self._journal:
                        await self._journal.log_signal(signal)
                    if self._telegram:
                        await self._telegram.alert_signal(signal)

            except Exception as exc:
                log.error("scan_loop_error", symbol=symbol, error=str(exc))

    # ── Position Management Loop ─────────────────────────────────────────

    async def _position_loop(self) -> None:
        for symbol, position in list(self._portfolio.positions.items()):
            try:
                # Use correct client for this position's market mode
                client = self._client_for_mode(position.market_mode)
                klines = await client.get_klines(
                    symbol, settings.primary_timeframe, limit=5
                )
                if not klines:
                    continue

                price = float(klines[-1][4])
                reason, fraction = evaluate_exit(position, price)
                if reason == ExitDecision.NONE:
                    continue

                if reason == ExitDecision.TP1:
                    position = update_position_after_tp1(position, price)
                    self._portfolio.positions[symbol] = position
                    await self.emitter.emit("tp1_hit", {"symbol": symbol, "price": price})

                close_side = OrderSide.SELL if position.side.value == "LONG" else OrderSide.BUY
                close_qty = self._exec.normalize_quantity(symbol, position.quantity * fraction)

                if close_qty > 0:
                    if settings.dry_run:
                        log.info("dry_run_close", symbol=symbol, reason=reason, qty=close_qty)
                    else:
                        await client.place_market_order(
                            symbol=symbol,
                            side=close_side.value,
                            quantity=close_qty,
                        )

                if fraction >= 1.0:
                    self._portfolio.remove_position(symbol)
                    self._risk.position_closed(symbol)
                    await self.emitter.emit(
                        "position_closed", {"symbol": symbol, "reason": reason}
                    )
                    if self._telegram:
                        await self._telegram.send_alert(
                            f"🔴 Position closed: {symbol} | {reason}"
                        )
                else:
                    position.quantity = max(0.0, position.quantity - close_qty)
                    self._portfolio.positions[symbol] = position

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

    # ── Deduplication ────────────────────────────────────────────────────────

    def _is_duplicate(self, symbol: str, candle_time: Optional[int]) -> bool:
        if candle_time is None:
            return False
        return candle_time in self._processed_candles[symbol]

    def _mark_processed(self, symbol: str, candle_time: Optional[int]) -> None:
        if candle_time is None:
            return
        cache = self._processed_candles[symbol]
        cache.add(candle_time)
        # When over 100, evict oldest 10% to amortize cost over many insertions
        if len(cache) > 100:
            to_remove = sorted(cache)[:10]
            for ts in to_remove:
                cache.discard(ts)
