"""
TradeJournal — dual-sink append-only trade log.

Sinks:
  1. CSV   — human-readable, importabil în Excel / TradingView
  2. SQLite — queryable pentru analytics

Usage:
    journal = TradeJournal()
    await journal.setup()
    await journal.log_trade(trade)
    await journal.log_signal(signal)
    df = await journal.query_trades(symbol="BTCUSDT", limit=100)
"""
from __future__ import annotations

import asyncio
import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

from backend.models import StrategySignal, Trade

logger = logging.getLogger(__name__)

_JOURNAL_DIR = Path(os.getenv("JOURNAL_DIR", "./journal_data"))
_TRADES_CSV = _JOURNAL_DIR / "trades.csv"
_SIGNALS_CSV = _JOURNAL_DIR / "signals.csv"
_DB_PATH = _JOURNAL_DIR / "journal.db"

_TRADES_HEADERS = [
    "id", "symbol", "side", "entry_price", "exit_price", "quantity",
    "realized_pnl", "fee", "net_pnl", "r_multiple", "entry_time",
    "exit_time", "duration_min", "strategy", "exit_reason", "notes",
]
_SIGNALS_HEADERS = [
    "id", "symbol", "action", "confidence", "entry_price", "stop_loss",
    "take_profit_1", "take_profit_2", "timeframe", "reason", "ts",
]


class TradeJournal:
    """Thread-safe async dual-sink trade journal."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._db: Optional[aiosqlite.Connection] = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def setup(self) -> None:
        """Create directories, CSV headers, SQLite tables."""
        _JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
        self._init_csv(_TRADES_CSV, _TRADES_HEADERS)
        self._init_csv(_SIGNALS_CSV, _SIGNALS_HEADERS)
        self._db = await aiosqlite.connect(str(_DB_PATH))
        await self._create_tables()
        logger.info("TradeJournal ready at %s", _JOURNAL_DIR)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    # ------------------------------------------------------------------ #
    # Public write API
    # ------------------------------------------------------------------ #

    async def log_trade(self, trade: Trade) -> None:
        """Append a completed trade to CSV + SQLite."""
        duration_min = 0
        if trade.entry_time and trade.exit_time:
            delta = trade.exit_time - trade.entry_time
            duration_min = int(delta.total_seconds() / 60)

        row = {
            "id": trade.id,
            "symbol": trade.symbol,
            "side": trade.side,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price or "",
            "quantity": trade.quantity,
            "realized_pnl": trade.realized_pnl or "",
            "fee": trade.fee or "",
            "net_pnl": (trade.realized_pnl or 0) - (trade.fee or 0),
            "r_multiple": trade.r_multiple or "",
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else "",
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else "",
            "duration_min": duration_min,
            "strategy": trade.strategy or "",
            "exit_reason": trade.exit_reason or "",
            "notes": "",
        }
        async with self._lock:
            self._append_csv(_TRADES_CSV, row, _TRADES_HEADERS)
            if self._db:
                await self._db.execute(
                    """INSERT OR REPLACE INTO trades
                       (id, symbol, side, entry_price, exit_price, quantity,
                        realized_pnl, fee, net_pnl, r_multiple,
                        entry_time, exit_time, duration_min, strategy, exit_reason)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        str(row["id"]), row["symbol"], row["side"],
                        row["entry_price"], row["exit_price"] or None,
                        row["quantity"], row["realized_pnl"] or None,
                        row["fee"] or None, row["net_pnl"],
                        row["r_multiple"] or None,
                        row["entry_time"] or None, row["exit_time"] or None,
                        row["duration_min"], row["strategy"] or None,
                        row["exit_reason"] or None,
                    ),
                )
                await self._db.commit()

    async def log_signal(self, signal: StrategySignal) -> None:
        """Append a generated strategy signal to CSV + SQLite."""
        row = {
            "id": str(signal.id),
            "symbol": signal.symbol,
            "action": signal.action.value,
            "confidence": signal.confidence,
            "entry_price": signal.entry_price or "",
            "stop_loss": signal.stop_loss,
            "take_profit_1": signal.take_profit_1,
            "take_profit_2": signal.take_profit_2,
            "timeframe": signal.timeframe,
            "reason": signal.reason,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        async with self._lock:
            self._append_csv(_SIGNALS_CSV, row, _SIGNALS_HEADERS)
            if self._db:
                await self._db.execute(
                    """INSERT OR IGNORE INTO signals
                       (id, symbol, action, confidence, entry_price,
                        stop_loss, take_profit_1, take_profit_2, timeframe, reason, ts)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row["id"], row["symbol"], row["action"],
                        row["confidence"], row["entry_price"] or None,
                        row["stop_loss"], row["take_profit_1"],
                        row["take_profit_2"], row["timeframe"],
                        row["reason"], row["ts"],
                    ),
                )
                await self._db.commit()

    # ------------------------------------------------------------------ #
    # Query API
    # ------------------------------------------------------------------ #

    async def query_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Return recent trades as list of dicts (newest first)."""
        if not self._db:
            return []
        where = "WHERE symbol = ?" if symbol else ""
        params = [symbol] if symbol else []
        params += [limit, offset]
        async with self._db.execute(
            f"SELECT * FROM trades {where} ORDER BY entry_time DESC LIMIT ? OFFSET ?",
            params,
        ) as cur:
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) async for row in cur]

    async def query_signals(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Return recent signals as list of dicts."""
        if not self._db:
            return []
        where = "WHERE symbol = ?" if symbol else ""
        params = ([symbol] if symbol else []) + [limit]
        async with self._db.execute(
            f"SELECT * FROM signals {where} ORDER BY ts DESC LIMIT ?",
            params,
        ) as cur:
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) async for row in cur]

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _init_csv(path: Path, headers: list[str]) -> None:
        if not path.exists():
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=headers).writeheader()

    @staticmethod
    def _append_csv(path: Path, row: dict, headers: list[str]) -> None:
        with open(path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=headers).writerow(row)

    async def _create_tables(self) -> None:
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id          TEXT PRIMARY KEY,
                symbol      TEXT NOT NULL,
                side        TEXT NOT NULL,
                entry_price REAL,
                exit_price  REAL,
                quantity    REAL,
                realized_pnl REAL,
                fee         REAL,
                net_pnl     REAL,
                r_multiple  REAL,
                entry_time  TEXT,
                exit_time   TEXT,
                duration_min INTEGER,
                strategy    TEXT,
                exit_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS signals (
                id          TEXT PRIMARY KEY,
                symbol      TEXT NOT NULL,
                action      TEXT NOT NULL,
                confidence  REAL,
                entry_price REAL,
                stop_loss   REAL,
                take_profit_1 REAL,
                take_profit_2 REAL,
                timeframe   TEXT,
                reason      TEXT,
                ts          TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
            CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time);
            CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
        """)
        await self._db.commit()
