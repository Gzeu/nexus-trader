"""
AutomationEngine — scheduler + event emitter pentru trading automat.

CHANGELOG:
  🟠 _placed_ids: inlocuit set() cu OrderedDict — evict automat la >500 entries.
     Rezolva memory leak daca serverul ruleaza zile fara restart.
     Nu necesita Redis: solutie in-memory FIFO cu garantii suficiente pentru
     deduplicare intra-sesiune (fereastra de 500 ordine recente).
  🟡 _seen_candles: fiecare symbol are deque(maxlen=200) in loc de set() nelimitat.
     La 4 simboluri x 1440 candele/zi = 5760 entries/zi fara fix.
     Cu maxlen=200: maxim 800 entries totale, auto-evict oldest.
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import get_settings
from backend.models import StrategySignal

logger = logging.getLogger(__name__)

# Nr. maxim de placed_ids pastrate in memorie (FIFO evict la depasire)
_PLACED_IDS_MAXLEN = 500
# Nr. maxim de candle timestamps pastrate per simbol
_SEEN_CANDLES_MAXLEN = 200


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
        self._strategy        = strategy
        self._risk            = risk_manager
        self._execution       = execution_engine
        self._portfolio       = portfolio_engine
        self._client          = binance_client
        self._journal         = journal
        self._telegram        = telegram
        self._ws_broadcast    = ws_broadcast

        cfg = get_settings()
        self._symbols: List[str]  = cfg.symbol_whitelist
        self._interval_minutes    = cfg.automation_interval_minutes
        self._max_recent_signals  = 200

        self._scheduler       = AsyncIOScheduler()
        self._running         = False
        self._recent_signals: List[Dict[str, Any]] = []

        # 🟠 FIX: OrderedDict cu evict FIFO la >_PLACED_IDS_MAXLEN entries.
        # Garanteaza ca memoria nu creste nelimitat in sesiuni lungi.
        self._placed_ids: OrderedDict[str, bool] = OrderedDict()

        # 🟡 FIX: deque(maxlen=200) per simbol — auto-evict oldest candle timestamp.
        # Dict[symbol -> deque[candle_open_time_str]]
        self._seen_candles: Dict[str, deque] = {}

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
        # Midnight reset pentru daily risk counters
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
        if not self._portfolio.is_ready:
            logger.debug("[automation] tick skipped — portfolio not reconciled")
            return
        if self._risk.is_paused:
            logger.debug("[automation] tick skipped — risk paused")
            return

        for symbol in self._symbols:
            try:
                await self._process_symbol(symbol)
            except Exception as exc:
                logger.error("[automation] _process_symbol(%s) error: %s", symbol, exc)

    async def _process_symbol(self, symbol: str) -> None:
        """Genereaza semnal, valideaza risc, executa daca OK."""
        # 1. Fetch OHLCV
        try:
            klines = await self._client.get_klines(symbol, interval="1m", limit=100)
        except Exception as exc:
            logger.warning("[automation] klines fetch failed for %s: %s", symbol, exc)
            return

        # 2. Genereaza semnal
        signal: Optional[StrategySignal] = await asyncio.to_thread(
            self._strategy.compute, klines
        )
        if signal is None or signal.action == "HOLD":
            return

        # 3. Anti-duplicate per candle (🟡 FIX: deque bounded per simbol)
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

        # 4. Risk check
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

        # 5. Idempotency check (🟠 FIX: OrderedDict cu FIFO evict)
        signal_id = f"{symbol}:{signal.action}:{candle_key}"
        if signal_id in self._placed_ids:
            logger.debug("[automation] idempotency skip: %s", signal_id)
            return
        self._record_placed_id(signal_id)

        # 6. Executa
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
        equity = self._portfolio.get_equity()
        qty = self._execution.calc_position_size(
            equity=equity,
            entry_price=signal.entry_price or 0,
            stop_loss=signal.stop_loss,
            risk_pct=get_settings().risk_per_trade,
        ) if hasattr(self._execution, "calc_position_size") else 0.0

        if qty <= 0:
            logger.warning("[automation] calc_position_size returned 0 for %s", signal.symbol)
            return

        await self._execution.place_order(
            symbol=signal.symbol,
            side="BUY" if signal.action == "BUY" else "SELL",
            quantity=qty,
            order_type=signal.entry_type.upper() if signal.entry_type else "MARKET",
            price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit_1,
        )
        self._risk.on_position_opened(signal.symbol)

    async def _manage_open_positions(self) -> None:
        """Evalueaza exit logic pentru toate pozitiile deschise."""
        positions = self._portfolio.get_positions()
        if not positions:
            return

        for pos in positions:
            try:
                price = self._portfolio._price_cache.get(pos.symbol)
                if not price:
                    continue

                exit_reason, close_fraction = self._execution.evaluate_exit(
                    position=pos, current_price=price
                ) if hasattr(self._execution, "evaluate_exit") else (None, 0.0)

                if exit_reason and close_fraction > 0:
                    logger.info(
                        "[automation] exit triggered: %s reason=%s fraction=%.2f",
                        pos.symbol,
                        exit_reason,
                        close_fraction,
                    )
                    # Partial sau full close
                    close_qty = round(pos.quantity * close_fraction, 8)
                    side = "SELL" if pos.side == "BUY" else "BUY"

                    await self._execution.place_order(
                        symbol=pos.symbol,
                        side=side,
                        quantity=close_qty,
                        order_type="MARKET",
                    )

                    if close_fraction >= 1.0:
                        self._portfolio.remove_position(pos.symbol)
                        self._risk.on_trade_closed(
                            pnl=getattr(pos, "unrealized_pnl", 0.0),
                            symbol=pos.symbol,
                        )
                        await self._events.emit("position_closed", {"symbol": pos.symbol})
                    else:
                        # Partial close — update_position() acum exista (🔴 fix portfolio_engine)
                        updated = pos.model_copy(
                            update={"quantity": pos.quantity - close_qty}
                        )
                        self._portfolio.update_position(updated)
                        await self._events.emit(
                            "tp_hit",
                            {"symbol": pos.symbol, "reason": exit_reason, "fraction": close_fraction},
                        )
            except Exception as exc:
                logger.error("[automation] _manage_open_positions error for %s: %s", pos.symbol, exc)

    async def _midnight_reset(self) -> None:
        """Reset daily risk counters la 00:00 UTC."""
        self._risk.reset_daily()
        # Curata seen_candles complet la midnight (oricum expirate)
        self._seen_candles.clear()
        logger.info("[automation] midnight reset done")

    # ──────────────────────────────────────────────── idempotency helpers

    def _record_placed_id(self, signal_id: str) -> None:
        """
        🟠 Inregistreaza un signal_id in OrderedDict cu evict FIFO.
        Garanteaza ca _placed_ids nu depaseste _PLACED_IDS_MAXLEN entries.
        """
        if signal_id in self._placed_ids:
            return
        self._placed_ids[signal_id] = True
        # Evict oldest entries daca depasim limita
        while len(self._placed_ids) > _PLACED_IDS_MAXLEN:
            self._placed_ids.popitem(last=False)  # FIFO: sterge primul adaugat

    # ──────────────────────────────────────────────── recent signals

    def _add_recent_signal(self, signal: StrategySignal, status: str) -> None:
        entry = {
            **signal.model_dump(),
            "signal_status": status,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._recent_signals.append(entry)
        # Mentine fereastra la max _max_recent_signals
        if len(self._recent_signals) > self._max_recent_signals:
            self._recent_signals = self._recent_signals[-self._max_recent_signals :]

    def get_recent_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._recent_signals[-limit:]

    # ──────────────────────────────────────────────── event hooks

    def on(self, event: str, handler: Callable[..., Coroutine]) -> None:
        self._events.on(event, handler)
