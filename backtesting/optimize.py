"""
Parameter optimization via grid search + Optuna.

Usage (grid search):
    python -m backtesting.optimize --mode grid --symbol BTCUSDT --interval 15m

Usage (Optuna bayesian):
    python -m backtesting.optimize --mode optuna --symbol BTCUSDT --interval 15m --trials 200
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np

from backtesting.backtest_engine import BacktestConfig, EventBacktester, SignalGenerator, fetch_ohlcv

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ─── Grid search space ───────────────────────────────────────────────────────

GRID: dict[str, list[Any]] = {
    "ema_fast":      [7, 9, 12],
    "ema_slow":      [18, 21, 26],
    "atr_sl_mult":   [1.2, 1.5, 2.0],
    "atr_tp1_mult":  [1.8, 2.0, 2.5],
    "risk_per_trade": [0.005, 0.01, 0.015],
}


async def run_one(df_base, cfg_kwargs: dict) -> dict:
    """Run a single backtest and return metrics dict."""
    cfg = BacktestConfig(**cfg_kwargs)
    gen = SignalGenerator(df_base.copy(), cfg)
    df  = gen.get_signals()
    bt  = EventBacktester(df, cfg)
    res = bt.run()
    return {
        **cfg_kwargs,
        "total_return_pct": res.total_return_pct,
        "max_drawdown_pct": res.max_drawdown_pct,
        "sharpe_ratio":     res.sharpe_ratio,
        "profit_factor":    res.profit_factor,
        "win_rate":         res.win_rate,
        "total_trades":     res.total_trades,
        # Composite score: Sharpe * (1 - dd/100)
        "score": res.sharpe_ratio * (1 - res.max_drawdown_pct / 100),
    }


async def grid_search(symbol: str, interval: str, start: str, end: str) -> None:
    logger.info("Loading OHLCV data...")
    df = await fetch_ohlcv(symbol, interval, start, end)

    keys   = list(GRID.keys())
    combos = list(product(*GRID.values()))
    logger.info("Grid search: %d combinations", len(combos))

    results: list[dict] = []
    base_cfg = dict(
        symbol=symbol, interval=interval, start=start, end=end,
        strategy="composite", initial_capital=10_000.0,
        commission_pct=0.0005, slippage_pct=0.0002,
    )

    for i, combo in enumerate(combos):
        cfg_kwargs = {**base_cfg, **dict(zip(keys, combo))}
        res = await run_one(df, cfg_kwargs)
        results.append(res)
        if (i + 1) % 10 == 0:
            logger.info("  %d / %d done", i + 1, len(combos))

    results.sort(key=lambda x: -x["score"])

    out_dir = Path("backtesting/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{symbol}_{interval}_grid_search"

    # CSV
    with open(out_dir / f"{tag}.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    # Top 10 JSON
    (out_dir / f"{tag}_top10.json").write_text(json.dumps(results[:10], indent=2))

    print("\n── Top 10 parameter sets ──")
    for r in results[:10]:
        print(f"  Score={r['score']:.3f}  Sharpe={r['sharpe_ratio']:.3f}  "
              f"DD={r['max_drawdown_pct']:.1f}%  Return={r['total_return_pct']:+.1f}%  "
              f"Params: ema={r['ema_fast']}/{r['ema_slow']} "
              f"sl={r['atr_sl_mult']} tp1={r['atr_tp1_mult']} risk={r['risk_per_trade']}")
    print(f"\nFull results → {out_dir / tag}.csv")


async def optuna_search(symbol: str, interval: str, start: str, end: str, n_trials: int) -> None:
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        logger.error("Install optuna: pip install optuna")
        return

    df = await fetch_ohlcv(symbol, interval, start, end)
    base_cfg = dict(
        symbol=symbol, interval=interval, start=start, end=end,
        strategy="composite", initial_capital=10_000.0,
        commission_pct=0.0005, slippage_pct=0.0002,
    )

    def objective(trial: optuna.Trial) -> float:
        cfg_kwargs = {
            **base_cfg,
            "ema_fast":       trial.suggest_int("ema_fast", 5, 15),
            "ema_slow":       trial.suggest_int("ema_slow", 15, 35),
            "atr_sl_mult":    trial.suggest_float("atr_sl_mult", 0.8, 3.0, step=0.1),
            "atr_tp1_mult":   trial.suggest_float("atr_tp1_mult", 1.5, 4.0, step=0.1),
            "atr_tp2_mult":   trial.suggest_float("atr_tp2_mult", 3.0, 6.0, step=0.1),
            "risk_per_trade": trial.suggest_float("risk_per_trade", 0.003, 0.02, step=0.001),
            "rsi_len":        trial.suggest_int("rsi_len", 7, 21),
            "bb_len":         trial.suggest_int("bb_len", 14, 30),
        }
        # Run synchronously inside Optuna trial
        cfg = BacktestConfig(**cfg_kwargs)
        gen = SignalGenerator(df.copy(), cfg)
        df2 = gen.get_signals()
        bt  = EventBacktester(df2, cfg)
        res = bt.run()
        # Penalize strategies with too few trades (< 10)
        if res.total_trades < 10:
            return -999.0
        return res.sharpe_ratio * (1 - res.max_drawdown_pct / 100)

    study = optuna.create_study(direction="maximize",
                                sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    out_dir = Path("backtesting/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{symbol}_{interval}_optuna"

    best = study.best_params
    print(f"\n── Optuna best params (score={study.best_value:.4f}) ──")
    for k, v in best.items():
        print(f"  {k}: {v}")

    (out_dir / f"{tag}_best.json").write_text(json.dumps({"score": study.best_value, **best}, indent=2))
    logger.info("Best params saved → %s", out_dir / f"{tag}_best.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Nexus Trader Optimizer")
    parser.add_argument("--mode",     default="grid", choices=["grid", "optuna"])
    parser.add_argument("--symbol",   default="BTCUSDT")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--start",    default="2024-01-01")
    parser.add_argument("--end",      default="2024-12-31")
    parser.add_argument("--trials",   type=int, default=100)
    args = parser.parse_args()

    if args.mode == "grid":
        asyncio.run(grid_search(args.symbol, args.interval, args.start, args.end))
    else:
        asyncio.run(optuna_search(args.symbol, args.interval, args.start, args.end, args.trials))


if __name__ == "__main__":
    main()
