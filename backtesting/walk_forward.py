"""
Walk-Forward Analysis — rolling in-sample optimization + out-of-sample validation.

Usage:
    python -m backtesting.walk_forward \\
        --symbol BTCUSDT --interval 15m \\
        --start 2023-01-01 --end 2024-12-31 \\
        --is-months 3 --oos-months 1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from pathlib import Path

import numpy as np
import pandas as pd

from backtesting.backtest_engine import BacktestConfig, EventBacktester, SignalGenerator, fetch_ohlcv
from backtesting.optimize import GRID
from itertools import product

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@dataclass
class WFWindow:
    is_start: str
    is_end:   str
    oos_start: str
    oos_end:   str


def build_windows(start: str, end: str, is_months: int, oos_months: int) -> list[WFWindow]:
    windows: list[WFWindow] = []
    s = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    e = datetime.strptime(end,   "%Y-%m-%d").replace(tzinfo=timezone.utc)
    cursor = s
    while True:
        is_end   = cursor + relativedelta(months=is_months)
        oos_end  = is_end + relativedelta(months=oos_months)
        if oos_end > e:
            break
        windows.append(WFWindow(
            is_start=cursor.strftime("%Y-%m-%d"),
            is_end=is_end.strftime("%Y-%m-%d"),
            oos_start=is_end.strftime("%Y-%m-%d"),
            oos_end=oos_end.strftime("%Y-%m-%d"),
        ))
        cursor += relativedelta(months=oos_months)  # rolling step = OOS window
    return windows


def quick_optimize(df: pd.DataFrame, base_cfg: dict) -> dict:
    """Tiny grid search (subset of GRID) for speed in WF."""
    mini_grid = {
        "ema_fast":    [7, 9, 12],
        "ema_slow":    [18, 21, 26],
        "atr_sl_mult": [1.2, 1.5, 2.0],
    }
    keys   = list(mini_grid.keys())
    combos = list(product(*mini_grid.values()))
    best_score = -999.0
    best_params: dict = {}

    for combo in combos:
        kw  = {**base_cfg, **dict(zip(keys, combo))}
        cfg = BacktestConfig(**kw)
        gen = SignalGenerator(df.copy(), cfg)
        df2 = gen.get_signals()
        bt  = EventBacktester(df2, cfg)
        res = bt.run()
        score = res.sharpe_ratio * (1 - res.max_drawdown_pct / 100)
        if score > best_score:
            best_score  = score
            best_params = dict(zip(keys, combo))

    return best_params


async def walk_forward(symbol: str, interval: str,
                       start: str, end: str,
                       is_months: int, oos_months: int) -> None:
    logger.info("Fetching full OHLCV data for WF analysis...")
    df_full = await fetch_ohlcv(symbol, interval, start, end)
    df_full = df_full.sort_index()

    windows = build_windows(start, end, is_months, oos_months)
    logger.info("%d walk-forward windows", len(windows))

    oos_results: list[dict] = []
    base_cfg = dict(
        symbol=symbol, interval=interval, start=start, end=end,
        strategy="composite", initial_capital=10_000.0,
        commission_pct=0.0005, slippage_pct=0.0002,
    )

    for i, w in enumerate(windows):
        logger.info("Window %d/%d — IS: %s→%s  OOS: %s→%s",
                    i + 1, len(windows),
                    w.is_start, w.is_end, w.oos_start, w.oos_end)

        df_is  = df_full[w.is_start:w.is_end]
        df_oos = df_full[w.oos_start:w.oos_end]
        if len(df_is) < 100 or len(df_oos) < 20:
            logger.warning("  Skipping — insufficient data")
            continue

        # In-sample optimization
        best_params = quick_optimize(df_is, {**base_cfg, "start": w.is_start, "end": w.is_end})

        # Out-of-sample validation
        oos_cfg = BacktestConfig(**{**base_cfg, "start": w.oos_start, "end": w.oos_end, **best_params})
        gen = SignalGenerator(df_oos.copy(), oos_cfg)
        df2 = gen.get_signals()
        bt  = EventBacktester(df2, oos_cfg)
        res = bt.run()

        oos_results.append({
            "window": i + 1,
            "is_start": w.is_start, "is_end": w.is_end,
            "oos_start": w.oos_start, "oos_end": w.oos_end,
            "best_params": best_params,
            "oos_return":  res.total_return_pct,
            "oos_sharpe":  res.sharpe_ratio,
            "oos_dd":      res.max_drawdown_pct,
            "oos_trades":  res.total_trades,
            "oos_wr":      res.win_rate,
        })

    out_dir = Path("backtesting/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{symbol}_{interval}_wf_{is_months}m{oos_months}m"
    (out_dir / f"{tag}.json").write_text(json.dumps(oos_results, indent=2))

    # Summary
    if oos_results:
        avg_ret  = np.mean([r["oos_return"]  for r in oos_results])
        avg_shar = np.mean([r["oos_sharpe"]  for r in oos_results])
        avg_dd   = np.mean([r["oos_dd"]      for r in oos_results])
        pct_pos  = sum(1 for r in oos_results if r["oos_return"] > 0) / len(oos_results) * 100
        print("\n── Walk-Forward Summary ──")
        print(f"  Windows          : {len(oos_results)}")
        print(f"  Avg OOS Return   : {avg_ret:+.2f}%")
        print(f"  Avg OOS Sharpe   : {avg_shar:.3f}")
        print(f"  Avg OOS MaxDD    : {avg_dd:.2f}%")
        print(f"  % Profitable OOS : {pct_pos:.0f}%")
        print(f"  Report → {out_dir / tag}.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Nexus Trader Walk-Forward")
    parser.add_argument("--symbol",     default="BTCUSDT")
    parser.add_argument("--interval",   default="15m")
    parser.add_argument("--start",      default="2023-01-01")
    parser.add_argument("--end",        default="2024-12-31")
    parser.add_argument("--is-months",  type=int, default=3)
    parser.add_argument("--oos-months", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(walk_forward(args.symbol, args.interval,
                             args.start, args.end,
                             args.is_months, args.oos_months))


if __name__ == "__main__":
    main()
