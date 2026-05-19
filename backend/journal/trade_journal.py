"""
TradeJournal — dual-sink audit log: CSV append-only + SQLite via aiosqlite.
Thread-safe cu asyncio.Lock. Indexuri pe symbol + entry_time.
"""
from __future__ import annotations

import asyncio
import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from backend.models import StrategySignal, Trade

logger = logging.getLogger(__name__)

_JOURNAL_DIR = Path(os.getenv("JOURNAL_DIR", "./journal_data"))
_TRADES_CSV = _JOURNAL_DIR / "trades.csv"
_SIGNALS_CSV = _JOURNAL_DIR / "signals.csv"
_DB_PATH = _JOURNAL_DIR / "journal.db"

_TRADE_FIELDS = [
    "id", "symbol", "side", "entry_price", "exit_price", "quantity",
    "pnl", "pnl_pct", "r_multiple", "entry_time", "exit_time",
    "strategy", "reason", "fees",
]
_SIGNAL_FIELDS = [
    "id", "symbol", "action", "confidence", "entry_type", "entry_price",
    "stop_loss", "take_profit_1", "take_profit_2", "timeframe",
    "reason", "created_at",
]


class TradeJournal:
    """Async journal cu CSV + SQLite."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._db: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        """Creeaza directorul, CSV-urile si schema SQLite daca nu exista."""
        _JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
        self._init_csv(_TRADES_CSV, _TRADE_FIELDS)
        self._init_csv(_SIGNALS_CSV, _SIGNAL_FIELDS)
        self._db = await aiosqlite.connect(str(_DB_PATH))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("TradeJournal initialized at %s", _JOURNAL_DIR)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    # ------------------------------------------------------------------ write

    async def log_trade(self, trade: Trade) -> None:
        """Salveaza un trade inchis in CSV + SQLite."""
        async with self._lock:
            row = {
                "id": trade.id,
                "symbol": trade.symbol,
                "side": trade.side,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "quantity": trade.quantity,
                "pnl": trade.pnl,
                "pnl_pct": trade.pnl_pct,
                "r_multiple": trade.r_multiple,
                "entry_time": trade.entry_time.isoformat() if trade.entry_time else "",
                "exit_time": trade.exit_time.isoformat() if trade.exit_time else "",
                "strategy": trade.strategy,
                "reason": trade.exit_reason,
                "fees": trade.fees,
            }
            self._append_csv(_TRADES_CSV, _TRADE_FIELDS, row)
            if self._db:
                await self._db.execute(
                    """
                    INSERT OR REPLACE INTO trades
                    (id, symbol, side, entry_price, exit_price, quantity,
                     pnl, pnl_pct, r_multiple, entry_time, exit_time, strategy, reason, fees)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row["id"], row["symbol"], row["side"],
                        row["entry_price"], row["exit_price"], row["quantity"],
                        row["pnl"], row["pnl_pct"], row["r_multiple"],
                        row["entry_time"], row["exit_time"],
                        row["strategy"], row["reason"], row["fees"],
                    ),
                )
                await self._db.commit()

    async def log_signal(self, signal: StrategySignal) -> None:
        """Salveaza un semnal generat in CSV + SQLite."""
        async with self._lock:
            row = {
                "id": signal.id,
                "symbol": signal.symbol,
                "action": signal.action,
                "confidence": signal.confidence,
                "entry_type": signal.entry_type,
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit_1": signal.take_profit_1,
                "take_profit_2": signal.take_profit_2,
                "timeframe": signal.timeframe,
                "reason": signal.reason,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._append_csv(_SIGNALS_CSV, _SIGNAL_FIELDS, row)
            if self._db:
                await self._db.execute(
                    """
                    INSERT OR REPLACE INTO signals
                    (id, symbol, action, confidence, entry_type, entry_price,
                     stop_loss, take_profit_1, take_profit_2, timeframe, reason, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row["id"], row["symbol"], row["action"],
                        row["confidence"], row["entry_type"], row["entry_price"],
                        row["stop_loss"], row["take_profit_1"], row["take_profit_2"],
                        row["timeframe"], row["reason"], row["created_at"],
                    ),
                )
                await self._db.commit()

    # ------------------------------------------------------------------ read

    async def query_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if not self._db:
            return []
        where = "WHERE symbol = ?" if symbol else ""
        params = (symbol, limit, offset) if symbol else (limit, offset)
        async with self._db.execute(
            f"SELECT * FROM trades {where} ORDER BY entry_time DESC LIMIT ? OFFSET ?",
            params,
        ) as cur:
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) async for row in cur]

    async def query_signals(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        if not self._db:
            return []
        where = "WHERE symbol = ?" if symbol else ""
        params = (symbol, limit) if symbol else (limit,)
        async with self._db.execute(
            f"SELECT * FROM signals {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ) as cur:
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) async for row in cur]

    # ----------------------------------------------------------------- private

    @staticmethod
    def _init_csv(path: Path, fields: List[str]) -> None:
        if not path.exists():
            with open(path, "w", newline="") as f:
                csv.DictWriter(f, fieldnames=fields).writeheader()

    @staticmethod
    def _append_csv(path: Path, fields: List[str], row: Dict[str, Any]) -> None:
        with open(path, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=fields).writerow(row)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id          TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL,
    side        TEXT,
    entry_price REAL,
    exit_price  REAL,
    quantity    REAL,
    pnl         REAL,
    pnl_pct     REAL,
    r_multiple  REAL,
    entry_time  TEXT,
    exit_time   TEXT,
    strategy    TEXT,
    reason      TEXT,
    fees        REAL
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol     ON trades (symbol);
CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades (entry_time);

CREATE TABLE IF NOT EXISTS signals (
    id           TEXT PRIMARY KEY,
    symbol       TEXT NOT NULL,
    action       TEXT,
    confidence   REAL,
    entry_type   TEXT,
    entry_price  REAL,
    stop_loss    REAL,
    take_profit_1 REAL,
    take_profit_2 REAL,
    timeframe    TEXT,
    reason       TEXT,
    created_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol     ON signals (symbol);
CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals (created_at);
"""
