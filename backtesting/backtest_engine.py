"""
backtest_engine.py – Vectorbt-based backtesting wrapper for Nexus strategies.

Usage:
    python -m backtesting.backtest_engine --symbol BTCUSDT --tf 15m --days 180

Requires:
    pip install vectorbt pandas-ta

Outputs:
    - Console: sharpe, win_rate, profit_factor, max_drawdown, total_trades
    - backtesting/results/{symbol}_{tf}.html  – interactive tearsheet
    - backtesting/results/{symbol}_{tf}.csv   – trade log

Architecture note:
    BacktestEngine is intentionally decoupled from the live trading engine.
    It uses the same strategy logic (via pandas_ta) but runs vectorized on
    historical OHLCV data – no Binance API calls, no order management.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta
except ImportError:
    raise ImportError("Install pandas-ta: pip install pandas-ta")

try:
    import vectorbt as vbt
except ImportError:
    raise ImportError("Install vectorbt: pip install vectorbt")

RESULTS_DIR = Path("backtesting/results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


class BacktestEngine:
    """
    Vectorbt backtesting engine.
    Implements the same EMA + RSI + MACD + Volume logic as TrendFollowingStrategy.

    Args:
        symbol: Binance symbol, e.g. "BTCUSDT"
        timeframe: Kline interval, e.g. "15m"
        ema_fast: Fast EMA period (default 9)
        ema_slow: Slow EMA period (default 21)
        rsi_period: RSI period (default 14)
        atr_period: ATR period for SL/TP (default 14)
        atr_sl_mult: ATR multiplier for stop-loss (default 1.5)
        atr_tp_mult: ATR multiplier for take-profit (default 2.5)
        risk_per_trade: Fraction of equity risked per trade (default 0.01)
        initial_capital: Starting equity in USDT (default 10000)
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "15m",
        ema_fast: int = 9,
        ema_slow: int = 21,
        rsi_period: int = 14,
        atr_period: int = 14,
        atr_sl_mult: float = 1.5,
        atr_tp_mult: float = 2.5,
        risk_per_trade: float = 0.01,
        initial_capital: float = 10_000.0,
        fees: float = 0.001,  # 0.1% taker fee
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp_mult = atr_tp_mult
        self.risk_per_trade = risk_per_trade
        self.initial_capital = initial_capital
        self.fees = fees
        self._df: Optional[pd.DataFrame] = None

    # ── Data loading ────────────────────────────────────────────────────────

    def load_from_csv(self, path: str) -> "BacktestEngine":
        """
        Load OHLCV data from a CSV file.
        Expected columns: timestamp, open, high, low, close, volume
        """
        df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
        df.columns = [c.lower() for c in df.columns]
        self._df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return self

    async def load_from_binance(
        self, days: int = 180, testnet: bool = True
    ) -> "BacktestEngine":
        """
        Fetch OHLCV data from Binance REST API.
        Uses python-binance or httpx directly.

        Args:
            days: Number of days of history to fetch.
            testnet: Use Binance testnet endpoint.
        """
        try:
            import httpx
        except ImportError:
            raise ImportError("Install httpx: pip install httpx")

        base = (
            "https://testnet.binance.vision/api"
            if testnet
            else "https://api.binance.com/api"
        )
        interval_map = {
            "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "4h": 240, "1d": 1440,
        }
        minutes = interval_map.get(self.timeframe, 15)
        limit = min(1000, (days * 24 * 60) // minutes)

        rows = []
        end_time = int(datetime.utcnow().timestamp() * 1000)
        fetched = 0

        async with httpx.AsyncClient(timeout=30) as client:
            while fetched < (days * 24 * 60) // minutes:
                params = {
                    "symbol": self.symbol,
                    "interval": self.timeframe,
                    "limit": min(1000, limit - fetched),
                    "endTime": end_time,
                }
                resp = await client.get(f"{base}/v3/klines", params=params)
                resp.raise_for_status()
                data = resp.json()
                if not data:
                    break
                for k in data:
                    rows.append({
                        "timestamp": pd.Timestamp(k[0], unit="ms"),
                        "open":   float(k[1]),
                        "high":   float(k[2]),
                        "low":    float(k[3]),
                        "close":  float(k[4]),
                        "volume": float(k[5]),
                    })
                end_time = data[0][0] - 1
                fetched += len(data)
                if len(data) < 1000:
                    break

        df = pd.DataFrame(rows).sort_values("timestamp").set_index("timestamp")
        self._df = df.astype(float)
        print(f"Loaded {len(self._df)} candles for {self.symbol} {self.timeframe}")
        return self

    # ── Signal generation ────────────────────────────────────────────────────

    def _compute_signals(self) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        """
        Compute entry/exit signals using same logic as TrendFollowingStrategy.
        Returns: (long_entries, long_exits, short_entries, short_exits)
        """
        df = self._df.copy()

        df.ta.ema(length=self.ema_fast, append=True)
        df.ta.ema(length=self.ema_slow, append=True)
        df.ta.rsi(length=self.rsi_period, append=True)
        df.ta.macd(append=True)
        df.ta.atr(length=self.atr_period, append=True)

        ema_f_col = f"EMA_{self.ema_fast}"
        ema_s_col = f"EMA_{self.ema_slow}"
        rsi_col   = f"RSI_{self.rsi_period}"
        macd_col  = f"MACD_12_26_9"
        sig_col   = f"MACDs_12_26_9"

        vol_ma = df["volume"].rolling(20).mean()

        ema_cross_up   = (df[ema_f_col] > df[ema_s_col]) & (df[ema_f_col].shift(1) <= df[ema_s_col].shift(1))
        ema_cross_down = (df[ema_f_col] < df[ema_s_col]) & (df[ema_f_col].shift(1) >= df[ema_s_col].shift(1))

        long_entries  = ema_cross_up  & (df[rsi_col] > 45) & (df[rsi_col] < 70) & (df[macd_col] > df[sig_col]) & (df["volume"] > vol_ma)
        short_entries = ema_cross_down & (df[rsi_col] < 55) & (df[rsi_col] > 30) & (df[macd_col] < df[sig_col]) & (df["volume"] > vol_ma)

        # Exits: opposite signal or RSI extreme
        long_exits  = ema_cross_down | (df[rsi_col] > 75)
        short_exits = ema_cross_up   | (df[rsi_col] < 25)

        return long_entries, long_exits, short_entries, short_exits

    # ── Run ──────────────────────────────────────────────────────────────────────

    def run(self, long_only: bool = True) -> dict:
        """
        Execute backtest and return metrics dict.

        Args:
            long_only: If True, only test long signals (SPOT mode). Set False for Futures.

        Returns:
            dict with all key metrics + saved file paths.
        """
        if self._df is None:
            raise RuntimeError("Load data first: load_from_csv() or load_from_binance()")

        long_entries, long_exits, short_entries, short_exits = self._compute_signals()

        price = self._df["close"]

        if long_only:
            pf = vbt.Portfolio.from_signals(
                price,
                entries=long_entries,
                exits=long_exits,
                init_cash=self.initial_capital,
                fees=self.fees,
                slippage=0.001,
                freq=self.timeframe,
            )
        else:
            pf = vbt.Portfolio.from_signals(
                price,
                entries=long_entries,
                exits=long_exits,
                short_entries=short_entries,
                short_exits=short_exits,
                init_cash=self.initial_capital,
                fees=self.fees,
                slippage=0.001,
                freq=self.timeframe,
            )

        stats = pf.stats()
        trades = pf.trades.records_readable

        # Save outputs
        slug = f"{self.symbol}_{self.timeframe}"
        html_path = RESULTS_DIR / f"{slug}.html"
        csv_path  = RESULTS_DIR / f"{slug}_trades.csv"

        try:
            pf.plot().write_html(str(html_path))
        except Exception:
            pass  # plotly not available in headless env

        trades.to_csv(str(csv_path), index=False)

        metrics = {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "total_trades":     int(stats.get("Total Trades", 0)),
            "win_rate":         round(float(stats.get("Win Rate [%]", 0)) / 100, 4),
            "profit_factor":    round(float(stats.get("Profit Factor", 0)), 4),
            "sharpe_ratio":     round(float(stats.get("Sharpe Ratio", 0)), 4),
            "sortino_ratio":    round(float(stats.get("Sortino Ratio", 0)), 4),
            "max_drawdown_pct": round(float(stats.get("Max Drawdown [%]", 0)) / 100, 4),
            "total_return_pct": round(float(stats.get("Total Return [%]", 0)) / 100, 4),
            "expectancy_usdt":  round(float(stats.get("Expectancy", 0)), 2),
            "initial_capital":  self.initial_capital,
            "final_equity":     round(float(stats.get("End Value", self.initial_capital)), 2),
            "html_report":      str(html_path),
            "csv_trades":       str(csv_path),
        }

        self._print_summary(metrics)
        return metrics

    def _print_summary(self, m: dict) -> None:
        print("\n" + "="*60)
        print(f"  Nexus Trader Backtest — {m['symbol']} {m['timeframe']}")
        print("="*60)
        print(f"  Total Trades    : {m['total_trades']}")
        print(f"  Win Rate        : {m['win_rate']:.1%}")
        print(f"  Profit Factor   : {m['profit_factor']:.2f}")
        print(f"  Sharpe Ratio    : {m['sharpe_ratio']:.2f}")
        print(f"  Max Drawdown    : {m['max_drawdown_pct']:.1%}")
        print(f"  Total Return    : {m['total_return_pct']:.1%}")
        print(f"  Final Equity    : ${m['final_equity']:,.2f}")
        print(f"  HTML Report     : {m['html_report']}")
        print(f"  Trade CSV       : {m['csv_trades']}")
        print("="*60 + "\n")


# ── CLI entry point ───────────────────────────────────────────────────────

async def _main():
    parser = argparse.ArgumentParser(description="Nexus Trader Backtest")
    parser.add_argument("--symbol",   default="BTCUSDT")
    parser.add_argument("--tf",       default="15m", dest="timeframe")
    parser.add_argument("--days",     default=180, type=int)
    parser.add_argument("--testnet",  default=True,  action=argparse.BooleanOptionalAction)
    parser.add_argument("--futures",  default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument("--csv",      default=None,  help="Load from CSV instead of Binance")
    args = parser.parse_args()

    engine = BacktestEngine(symbol=args.symbol, timeframe=args.timeframe)

    if args.csv:
        engine.load_from_csv(args.csv)
    else:
        await engine.load_from_binance(days=args.days, testnet=args.testnet)

    engine.run(long_only=not args.futures)


if __name__ == "__main__":
    asyncio.run(_main())
