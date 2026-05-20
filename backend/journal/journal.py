"""
TradeJournal — audit log CSV + SQLite pentru toate trade-urile si semnalele.

CHANGELOG:
  🟡 FIX #8: CSV header guard — headerul se scrie DOAR daca fisierul nu exista.
     La restart, append fara header duplicat.
"""
from __future__ import annotations

import asyncio
import csv
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TRADE_FIELDS = [
    "id", "symbol", "side", "quantity", "entry_price", "exit_price",
    "pnl", "pnl_pct", "commission", "opened_at", "closed_at",
    "exit_reason", "r_multiple", "strategy_name",
]

SIGNAL_FIELDS = [
    "ts", "symbol", "action", "confidence", "entry_type", "entry_price",
    "stop_loss", "take_profit_1", "take_profit_2", "timeframe",
    "reason", "signal_status",
]


class TradeJournal:
    """
    Scrie tranzactiile si semnalele in CSV (append) si SQLite (optional).
    Thread-safe prin asyncio.Lock.
    """

    def __init__(
        self,
        csv_trades_path: str   = "journal/trades.csv",
        csv_signals_path: str  = "journal/signals.csv",
        db_path: Optional[str] = "journal/journal.db",
    ) -> None:
        self._csv_trades  = Path(csv_trades_path)
        self._csv_signals = Path(csv_signals_path)
        self._db_path     = db_path
        self._lock        = asyncio.Lock()
        self._db_conn: Optional[sqlite3.Connection] = None

        # Asigura directoarele
        self._csv_trades.parent.mkdir(parents=True, exist_ok=True)
        self._csv_signals.parent.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────────────────────────────── setup

    async def setup(self) -> None:
        """Initializeaza SQLite schema."""
        if not self._db_path:
            return
        await asyncio.to_thread(self._init_db)

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                symbol TEXT, side TEXT, quantity REAL,
                entry_price REAL, exit_price REAL,
                pnl REAL, pnl_pct REAL, commission REAL,
                opened_at TEXT, closed_at TEXT,
                exit_reason TEXT, r_multiple REAL, strategy_name TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                ts TEXT, symbol TEXT, action TEXT,
                confidence REAL, entry_type TEXT, entry_price REAL,
                stop_loss REAL, take_profit_1 REAL, take_profit_2 REAL,
                timeframe TEXT, reason TEXT, signal_status TEXT
            )
        """)
        conn.commit()
        conn.close()
        self._db_conn = None   # reopen per-thread

    # ─────────────────────────────────────────────────── write trades

    async def log_trade(self, trade: Dict[str, Any]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._write_trade_csv, trade)
            if self._db_path:
                await asyncio.to_thread(self._write_trade_db, trade)

    def _write_trade_csv(self, trade: Dict[str, Any]) -> None:
        # 🟡 FIX #8: Header guard — scriem header DOAR daca fisierul e nou
        write_header = not self._csv_trades.exists()
        with open(self._csv_trades, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(trade)

    def _write_trade_db(self, trade: Dict[str, Any]) -> None:
        conn = sqlite3.connect(self._db_path)  # type: ignore
        row  = {k: trade.get(k) for k in TRADE_FIELDS}
        conn.execute(
            f"INSERT OR REPLACE INTO trades ({', '.join(TRADE_FIELDS)}) "
            f"VALUES ({', '.join('?' * len(TRADE_FIELDS))})",
            [row[k] for k in TRADE_FIELDS],
        )
        conn.commit()
        conn.close()

    # ─────────────────────────────────────────────────── write signals

    async def log_signal(self, signal: Dict[str, Any]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._write_signal_csv, signal)
            if self._db_path:
                await asyncio.to_thread(self._write_signal_db, signal)

    def _write_signal_csv(self, signal: Dict[str, Any]) -> None:
        # 🟡 FIX #8: Header guard
        write_header = not self._csv_signals.exists()
        with open(self._csv_signals, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SIGNAL_FIELDS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(signal)

    def _write_signal_db(self, signal: Dict[str, Any]) -> None:
        conn = sqlite3.connect(self._db_path)  # type: ignore
        row  = {k: signal.get(k) for k in SIGNAL_FIELDS}
        conn.execute(
            f"INSERT INTO signals ({', '.join(SIGNAL_FIELDS)}) "
            f"VALUES ({', '.join('?' * len(SIGNAL_FIELDS))})",
            [row[k] for k in SIGNAL_FIELDS],
        )
        conn.commit()
        conn.close()

    # ─────────────────────────────────────────────────── queries

    async def query_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if not self._db_path:
            return []
        return await asyncio.to_thread(self._query_trades_db, symbol, limit, offset)

    def _query_trades_db(
        self, symbol: Optional[str], limit: int, offset: int
    ) -> List[Dict[str, Any]]:
        conn   = sqlite3.connect(self._db_path)  # type: ignore
        conn.row_factory = sqlite3.Row
        query  = "SELECT * FROM trades"
        params: list = []
        if symbol:
            query  += " WHERE symbol = ?"
            params.append(symbol)
        query  += " ORDER BY opened_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        rows   = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    async def query_signals(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        if not self._db_path:
            return []
        return await asyncio.to_thread(self._query_signals_db, symbol, limit)

    def _query_signals_db(
        self, symbol: Optional[str], limit: int
    ) -> List[Dict[str, Any]]:
        conn  = sqlite3.connect(self._db_path)  # type: ignore
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM signals"
        params: list = []
        if symbol:
            query  += " WHERE symbol = ?"
            params.append(symbol)
        query  += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        rows  = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
