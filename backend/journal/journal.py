"""
journal.py – Async trade journal.

Writes every trade to:
  - CSV (append-only, human-readable)
  - SQLite via aiosqlite (queryable)

Tables:
  trades   – closed trade records
  signals  – all signals emitted (including rejected ones)
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite
import structlog

from backend.config import get_settings

log = structlog.get_logger(__name__)

TRADE_COLUMNS = [
    "id", "symbol", "side", "entry_price", "exit_price",
    "quantity", "realized_pnl", "pnl_pct", "r_multiple",
    "entry_time", "exit_time", "duration_min",
    "strategy", "exit_reason", "market_mode",
]

SIGNAL_COLUMNS = [
    "id", "symbol", "action", "confidence", "entry_type",
    "entry_price", "stop_loss", "take_profit_1", "take_profit_2",
    "timeframe", "reason", "created_at", "accepted", "veto_reason",
]


class TradeJournal:
    """Async append-only journal backed by CSV + SQLite."""

    def __init__(self):
        s = get_settings()
        base = Path(s.journal_dir)
        base.mkdir(parents=True, exist_ok=True)
        self._csv_path = base / "trades.csv"
        self._db_path = base / "trades.db"
        self._db: Optional[aiosqlite.Connection] = None

    async def setup(self) -> None:
        """Initialize DB tables and CSV header."""
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.execute(
            f"CREATE TABLE IF NOT EXISTS trades ({', '.join(TRADE_COLUMNS)})"
        )
        await self._db.execute(
            f"CREATE TABLE IF NOT EXISTS signals ({', '.join(SIGNAL_COLUMNS)})"
        )
        await self._db.commit()

        if not self._csv_path.exists():
            with open(self._csv_path, "w", newline="") as f:
                csv.DictWriter(f, fieldnames=TRADE_COLUMNS).writeheader()
        log.info("journal_ready", db=str(self._db_path), csv=str(self._csv_path))

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def log_trade(self, trade: Dict[str, Any]) -> None:
        """Append a closed trade to CSV + SQLite."""
        row = {col: trade.get(col, "") for col in TRADE_COLUMNS}
        # CSV
        with open(self._csv_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=TRADE_COLUMNS)
            writer.writerow(row)
        # SQLite
        placeholders = ", ".join(["?"] * len(TRADE_COLUMNS))
        values = [row[c] for c in TRADE_COLUMNS]
        await self._db.execute(
            f"INSERT INTO trades VALUES ({placeholders})", values
        )
        await self._db.commit()
        log.info("trade_logged", symbol=trade.get("symbol"), pnl=trade.get("realized_pnl"))

    async def log_signal(
        self,
        signal: Dict[str, Any],
        accepted: bool,
        veto_reason: Optional[str] = None,
    ) -> None:
        """Record every signal (accepted or vetoed)."""
        row = {col: signal.get(col, "") for col in SIGNAL_COLUMNS}
        row["created_at"] = datetime.now(timezone.utc).isoformat()
        row["accepted"] = int(accepted)
        row["veto_reason"] = veto_reason or ""
        placeholders = ", ".join(["?"] * len(SIGNAL_COLUMNS))
        values = [row[c] for c in SIGNAL_COLUMNS]
        await self._db.execute(
            f"INSERT INTO signals VALUES ({placeholders})", values
        )
        await self._db.commit()

    async def get_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Query trade history from SQLite."""
        if symbol:
            cursor = await self._db.execute(
                "SELECT * FROM trades WHERE symbol = ? ORDER BY rowid DESC LIMIT ?",
                (symbol, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM trades ORDER BY rowid DESC LIMIT ?", (limit,)
            )
        rows = await cursor.fetchall()
        return [dict(zip(TRADE_COLUMNS, row)) for row in rows]

    async def get_signals(self, limit: int = 100) -> List[Dict[str, Any]]:
        cursor = await self._db.execute(
            "SELECT * FROM signals ORDER BY rowid DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(zip(SIGNAL_COLUMNS, row)) for row in rows]
