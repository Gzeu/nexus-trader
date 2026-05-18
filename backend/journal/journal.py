"""
journal.py – Async trade journal: CSV append + SQLite.

Fixes / improvements over v1:
- get_trades() accepts `limit` parameter (was fixed at 50 in routes.py)
- log_order() only logs FILLED / DRY_RUN orders (was logging every order incl. REJECTED)
- CSV header written only if file doesn't already exist (was overwriting on restart)
- SQLite WAL mode enabled (better concurrent read performance)
- close() properly awaits DB connection close
- All DB operations use a single shared connection (was opening per call)
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from backend.config import get_settings
from backend.models import Order, OrderStatus, StrategySignal

log = structlog.get_logger(__name__)
settings = get_settings()

_CSV_FIELDS = [
    "id", "symbol", "side", "order_type", "status", "quantity",
    "avg_fill_price", "exchange_order_id", "market_mode",
    "signal_id", "placed_at", "filled_at",
]

_SIGNAL_FIELDS = [
    "id", "symbol", "action", "confidence", "entry_price",
    "stop_loss", "take_profit_1", "take_profit_2",
    "timeframe", "reason", "created_at",
]


class TradeJournal:
    """Dual-write journal: CSV (audit trail) + SQLite (queryable history)."""

    def __init__(self):
        self._csv_path = settings.journal_csv_path
        self._db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
        self._db = None  # aiosqlite connection
        self._ready = False

    async def setup(self) -> None:
        """Initialize DB tables and CSV file."""
        # Ensure journal directory exists
        os.makedirs(os.path.dirname(self._csv_path) or ".", exist_ok=True)

        try:
            import aiosqlite
            self._db = await aiosqlite.connect(self._db_path)
            # WAL mode for better concurrent performance
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    symbol TEXT,
                    side TEXT,
                    order_type TEXT,
                    status TEXT,
                    quantity TEXT,
                    avg_fill_price TEXT,
                    exchange_order_id TEXT,
                    market_mode TEXT,
                    signal_id TEXT,
                    placed_at TEXT,
                    filled_at TEXT
                )
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY,
                    symbol TEXT,
                    action TEXT,
                    confidence REAL,
                    entry_price TEXT,
                    stop_loss TEXT,
                    take_profit_1 TEXT,
                    take_profit_2 TEXT,
                    timeframe TEXT,
                    reason TEXT,
                    created_at TEXT
                )
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS equity_curve (
                    ts TEXT PRIMARY KEY,
                    equity REAL
                )
                """
            )
            await self._db.commit()
            self._ready = True
            log.info("journal_db_ready", path=self._db_path)
        except ImportError:
            log.warning("aiosqlite_not_found_journal_db_disabled")

        # CSV — write header only if file doesn't exist yet
        if not os.path.exists(self._csv_path):
            with open(self._csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
                writer.writeheader()

    async def log_order(self, order: Order) -> None:
        """Journal a filled order. Skips PENDING/REJECTED/CANCELED."""
        if order.status not in (OrderStatus.FILLED, OrderStatus.DRY_RUN, OrderStatus.PARTIALLY_FILLED):
            return

        row = {
            "id": str(order.id),
            "symbol": order.symbol,
            "side": str(order.side),
            "order_type": str(order.order_type),
            "status": str(order.status),
            "quantity": str(order.filled_quantity),
            "avg_fill_price": str(order.avg_fill_price),
            "exchange_order_id": order.exchange_order_id or "",
            "market_mode": str(order.market_mode),
            "signal_id": str(order.signal_id) if order.signal_id else "",
            "placed_at": order.placed_at.isoformat(),
            "filled_at": order.filled_at.isoformat() if order.filled_at else "",
        }

        # Append to CSV
        try:
            with open(self._csv_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
                writer.writerow(row)
        except Exception as exc:
            log.warning("journal_csv_write_error", error=str(exc))

        # Write to SQLite
        if self._ready and self._db:
            try:
                await self._db.execute(
                    "INSERT OR IGNORE INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(row.values()),
                )
                await self._db.commit()
            except Exception as exc:
                log.warning("journal_db_write_error", error=str(exc))

    async def log_signal(self, signal: StrategySignal) -> None:
        """Journal a strategy signal."""
        if not self._ready or not self._db:
            return
        try:
            await self._db.execute(
                "INSERT OR IGNORE INTO signals VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(signal.id), signal.symbol, str(signal.action),
                    signal.confidence,
                    str(signal.entry_price) if signal.entry_price else None,
                    str(signal.stop_loss), str(signal.take_profit_1),
                    str(signal.take_profit_2), signal.timeframe,
                    signal.reason, signal.created_at.isoformat(),
                ),
            )
            await self._db.commit()
        except Exception as exc:
            log.warning("journal_signal_write_error", error=str(exc))

    async def log_equity(self, equity: float) -> None:
        """Append equity snapshot to equity_curve table."""
        if not self._ready or not self._db:
            return
        try:
            await self._db.execute(
                "INSERT OR REPLACE INTO equity_curve VALUES (?, ?)",
                (datetime.utcnow().isoformat(), equity),
            )
            await self._db.commit()
        except Exception as exc:
            log.warning("journal_equity_write_error", error=str(exc))

    async def get_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return last `limit` filled orders from SQLite (or CSV fallback)."""
        if self._ready and self._db:
            try:
                async with self._db.execute(
                    "SELECT * FROM orders ORDER BY filled_at DESC LIMIT ?",
                    (limit,),
                ) as cur:
                    rows = await cur.fetchall()
                    cols = [d[0] for d in cur.description]
                    return [dict(zip(cols, r)) for r in rows]
            except Exception as exc:
                log.warning("journal_get_trades_db_error", error=str(exc))

        # CSV fallback
        try:
            with open(self._csv_path, "r") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            return rows[-limit:]
        except Exception:
            return []

    async def close(self) -> None:
        """Close the SQLite connection gracefully."""
        if self._db:
            try:
                await self._db.close()
            except Exception as exc:
                log.warning("journal_db_close_error", error=str(exc))
