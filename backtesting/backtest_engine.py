"""
Nexus Trader — Backtesting Engine (vectorbt + pandas).

Usage:
    python -m backtesting.backtest_engine \\
        --symbol BTCUSDT \\
        --interval 15m \\
        --start 2024-01-01 \\
        --end   2024-12-31 \\
        --strategy composite \\
        --initial-capital 10000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ─── Data structures ─────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    symbol:          str   = "BTCUSDT"
    interval:        str   = "15m"
    start:           str   = "2024-01-01"
    end:             str   = "2024-12-31"
    strategy:        str   = "composite"
    initial_capital: float = 10_000.0
    risk_per_trade:  float = 0.01        # 1 %
    commission_pct:  float = 0.0005      # 0.05 %
    slippage_pct:    float = 0.0002      # 0.02 %
    atr_len:         int   = 14
    atr_sl_mult:     float = 1.5
    atr_tp1_mult:    float = 2.0
    atr_tp2_mult:    float = 3.5
    ema_fast:        int   = 9
    ema_slow:        int   = 21
    rsi_len:         int   = 14
    bb_len:          int   = 20
    bb_std:          float = 2.0
    breakout_len:    int   = 20
    vol_mult:        float = 1.5
    min_confidence:  float = 0.60


@dataclass
class BacktestResult:
    symbol:           str
    interval:         str
    start:            str
    end:              str
    strategy:         str
    initial_capital:  float
    final_equity:     float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio:     float
    sortino_ratio:    float
    calmar_ratio:     float
    win_rate:         float
    profit_factor:    float
    expectancy:       float
    total_trades:     int
    winning_trades:   int
    losing_trades:    int
    avg_win_pct:      float
    avg_loss_pct:     float
    best_trade_pct:   float
    worst_trade_pct:  float
    avg_holding_bars: float
    r_multiples:      list[float] = field(default_factory=list)
    equity_curve:     list[float] = field(default_factory=list)


# ─── Indicators ──────────────────────────────────────────────────────────────

class Indicators:
    """Vectorised indicator calculations on a DataFrame with OHLCV columns."""

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain  = delta.clip(lower=0)
        loss  = (-delta).clip(lower=0)
        avg_g = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_l = loss.ewm(alpha=1 / period, adjust=False).mean()
        rs    = avg_g / avg_l.replace(0, np.nan)
        return 100 - 100 / (1 + rs)

    @staticmethod
    def atr(df: pd.DataFrame, period: int) -> pd.Series:
        hl  = df["high"] - df["low"]
        hpc = (df["high"] - df["close"].shift()).abs()
        lpc = (df["low"]  - df["close"].shift()).abs()
        tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False).mean()

    @staticmethod
    def bollinger(series: pd.Series, period: int, std: float) -> tuple[pd.Series, pd.Series, pd.Series]:
        basis = series.rolling(period).mean()
        sd    = series.rolling(period).std()
        return basis + std * sd, basis, basis - std * sd


# ─── Signal generators ───────────────────────────────────────────────────────

class SignalGenerator:
    def __init__(self, df: pd.DataFrame, cfg: BacktestConfig):
        self.df  = df.copy()
        self.cfg = cfg
        self._compute_all()

    def _compute_all(self) -> None:
        df  = self.df
        cfg = self.cfg

        df["ema_fast"] = Indicators.ema(df["close"], cfg.ema_fast)
        df["ema_slow"] = Indicators.ema(df["close"], cfg.ema_slow)
        df["rsi"]      = Indicators.rsi(df["close"], cfg.rsi_len)
        df["atr"]      = Indicators.atr(df, cfg.atr_len)

        bb_upper, _, bb_lower = Indicators.bollinger(df["close"], cfg.bb_len, cfg.bb_std)
        df["bb_upper"] = bb_upper
        df["bb_lower"] = bb_lower

        df["vol_avg"] = df["volume"].rolling(20).mean()
        df["hi_n"]    = df["high"].rolling(cfg.breakout_len).max().shift(1)
        df["lo_n"]    = df["low"].rolling(cfg.breakout_len).min().shift(1)

        # Trend
        df["trend_long"]  = (df["ema_fast"] > df["ema_slow"]) & \
                            (df["ema_fast"].shift() <= df["ema_slow"].shift()) & \
                            (df["rsi"] > 50)
        df["trend_short"] = (df["ema_fast"] < df["ema_slow"]) & \
                            (df["ema_fast"].shift() >= df["ema_slow"].shift()) & \
                            (df["rsi"] < 50)

        # Mean reversion
        df["mr_long"]  = (df["close"] > df["bb_lower"]) & \
                         (df["close"].shift() <= df["bb_lower"].shift()) & \
                         (df["rsi"] < 35)
        df["mr_short"] = (df["close"] < df["bb_upper"]) & \
                         (df["close"].shift() >= df["bb_upper"].shift()) & \
                         (df["rsi"] > 65)

        # Breakout
        df["br_long"]  = (df["close"] > df["hi_n"]) & (df["volume"] > df["vol_avg"] * cfg.vol_mult)
        df["br_short"] = (df["close"] < df["lo_n"]) & (df["volume"] > df["vol_avg"] * cfg.vol_mult)

        # Composite
        df["comp_long"]  = (df["trend_long"].astype(int) +
                            df["mr_long"].astype(int) +
                            df["br_long"].astype(int)) >= 2
        df["comp_short"] = (df["trend_short"].astype(int) +
                            df["mr_short"].astype(int) +
                            df["br_short"].astype(int)) >= 2

        self.df = df

    def get_signals(self) -> pd.DataFrame:
        df  = self.df
        cfg = self.cfg
        mode = cfg.strategy

        if mode == "trend":
            go_long, go_short = df["trend_long"], df["trend_short"]
        elif mode == "mean_reversion":
            go_long, go_short = df["mr_long"], df["mr_short"]
        elif mode == "breakout":
            go_long, go_short = df["br_long"], df["br_short"]
        else:  # composite
            go_long, go_short = df["comp_long"], df["comp_short"]

        df["signal"] = 0
        df.loc[go_long,  "signal"] =  1
        df.loc[go_short, "signal"] = -1

        df["sl_long"]  = df["close"] - df["atr"] * cfg.atr_sl_mult
        df["tp1_long"] = df["close"] + df["atr"] * cfg.atr_tp1_mult
        df["tp2_long"] = df["close"] + df["atr"] * cfg.atr_tp2_mult

        df["sl_short"]  = df["close"] + df["atr"] * cfg.atr_sl_mult
        df["tp1_short"] = df["close"] - df["atr"] * cfg.atr_tp1_mult
        df["tp2_short"] = df["close"] - df["atr"] * cfg.atr_tp2_mult

        return df


# ─── Event-driven backtester ─────────────────────────────────────────────────

class EventBacktester:
    """
    Bar-by-bar event backtester with:
    - Fixed-fractional position sizing (risk_per_trade % of equity at SL distance)
    - TP1 (40 %) → move SL to breakeven
    - TP2 (40 % of rest)
    - Trailing stop on remaining 20 %
    - Commission + slippage simulation
    """

    def __init__(self, df: pd.DataFrame, cfg: BacktestConfig):
        self.df    = df
        self.cfg   = cfg
        self.equity = cfg.initial_capital
        self.trades: list[dict] = []
        self.equity_curve: list[float] = [cfg.initial_capital]

    def run(self) -> BacktestResult:
        df    = self.df
        cfg   = self.cfg
        pos   = None  # active position dict or None
        peak  = cfg.initial_capital
        max_dd = 0.0

        for i in range(1, len(df)):
            row  = df.iloc[i]
            prev = df.iloc[i - 1]

            # Manage open position
            if pos is not None:
                pos, closed = self._manage_position(pos, row)
                if closed:
                    self.trades.append(closed)
                    pos = None
                    peak = max(peak, self.equity)
                    dd   = (peak - self.equity) / peak * 100
                    max_dd = max(max_dd, dd)

            # Open new position on signal (only if flat)
            if pos is None and prev["signal"] != 0:
                pos = self._open_position(prev, row, prev["signal"])

            self.equity_curve.append(self.equity)

        # Force-close any open position at last bar
        if pos is not None:
            last = df.iloc[-1]
            pnl  = self._close_fill(pos, last["close"], "end_of_data", 1.0)
            self.equity += pnl
            self.trades.append({**pos, "exit_price": last["close"],
                                "pnl": pnl, "reason": "end_of_data",
                                "close_i": len(df) - 1})

        return self._compute_metrics(max_dd)

    def _open_position(self, signal_row: pd.Series, entry_row: pd.Series, direction: int) -> dict:
        cfg         = self.cfg
        entry_price = entry_row["open"] * (1 + cfg.slippage_pct * direction)
        sl          = signal_row["sl_long"]  if direction == 1 else signal_row["sl_short"]
        tp1         = signal_row["tp1_long"] if direction == 1 else signal_row["tp1_short"]
        tp2         = signal_row["tp2_long"] if direction == 1 else signal_row["tp2_short"]

        risk_amount = self.equity * cfg.risk_per_trade
        sl_dist     = abs(entry_price - sl)
        if sl_dist < 1e-9:
            sl_dist = entry_price * 0.01

        qty = risk_amount / sl_dist
        cost = entry_price * qty * cfg.commission_pct
        self.equity -= cost

        return {
            "direction":    direction,
            "entry_price":  entry_price,
            "qty":          qty,
            "qty_remaining": qty,
            "sl":           sl,
            "tp1":          tp1,
            "tp2":          tp2,
            "tp1_hit":      False,
            "tp2_hit":      False,
            "be_moved":     False,
            "entry_i":      entry_row.name,
            "open_equity":  self.equity,
        }

    def _manage_position(self, pos: dict, row: pd.Series) -> tuple[Optional[dict], Optional[dict]]:
        cfg = self.cfg
        d   = pos["direction"]
        lo, hi = row["low"], row["high"]

        # SL hit
        sl_hit = (d == 1 and lo <= pos["sl"]) or (d == -1 and hi >= pos["sl"])
        if sl_hit:
            pnl = self._close_fill(pos, pos["sl"], "stop_loss", 1.0)
            self.equity += pnl
            return None, {**pos, "exit_price": pos["sl"], "pnl": pnl, "reason": "stop_loss",
                          "close_i": row.name}

        # TP1 hit
        if not pos["tp1_hit"]:
            tp1_hit = (d == 1 and hi >= pos["tp1"]) or (d == -1 and lo <= pos["tp1"])
            if tp1_hit:
                close_qty = pos["qty"] * 0.40
                pnl = self._close_fill(pos, pos["tp1"], "tp1", close_qty / pos["qty"])
                self.equity += pnl
                pos["qty_remaining"] -= close_qty
                pos["tp1_hit"] = True
                pos["sl"] = pos["entry_price"]  # move to breakeven

        # TP2 hit
        if pos["tp1_hit"] and not pos["tp2_hit"]:
            tp2_hit = (d == 1 and hi >= pos["tp2"]) or (d == -1 and lo <= pos["tp2"])
            if tp2_hit:
                close_qty = pos["qty"] * 0.40
                pnl = self._close_fill(pos, pos["tp2"], "tp2", close_qty / pos["qty"])
                self.equity += pnl
                pos["qty_remaining"] -= close_qty
                pos["tp2_hit"] = True

        # Trailing stop on remaining 20 % after TP2
        if pos["tp2_hit"]:
            atr = row.get("atr", abs(pos["tp1"] - pos["entry_price"]) / 2)
            new_sl = row["close"] - d * atr * cfg.atr_sl_mult * 0.8
            if d == 1 and new_sl > pos["sl"]:
                pos["sl"] = new_sl
            elif d == -1 and new_sl < pos["sl"]:
                pos["sl"] = new_sl

        return pos, None

    def _close_fill(self, pos: dict, price: float, reason: str, fraction: float) -> float:
        cfg      = self.cfg
        fill     = price * (1 - cfg.slippage_pct * pos["direction"])
        qty      = pos["qty_remaining"] * fraction
        gross    = (fill - pos["entry_price"]) * qty * pos["direction"]
        cost     = fill * qty * cfg.commission_pct
        return gross - cost

    def _compute_metrics(self, max_dd: float) -> BacktestResult:
        cfg    = self.cfg
        trades = self.trades
        curve  = self.equity_curve

        total_return  = (self.equity - cfg.initial_capital) / cfg.initial_capital * 100
        wins          = [t for t in trades if t["pnl"] > 0]
        losses        = [t for t in trades if t["pnl"] <= 0]
        win_rate      = len(wins) / len(trades) * 100 if trades else 0.0
        gross_profit  = sum(t["pnl"] for t in wins)
        gross_loss    = abs(sum(t["pnl"] for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        avg_win  = np.mean([t["pnl"] / cfg.initial_capital * 100 for t in wins])  if wins   else 0.0
        avg_loss = np.mean([t["pnl"] / cfg.initial_capital * 100 for t in losses]) if losses else 0.0
        best     = max((t["pnl"] for t in trades), default=0.0)
        worst    = min((t["pnl"] for t in trades), default=0.0)
        expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

        returns   = pd.Series(curve).pct_change().dropna()
        sharpe    = (returns.mean() / returns.std() * np.sqrt(252 * 24)) if returns.std() > 0 else 0.0
        neg_ret   = returns[returns < 0]
        sortino   = (returns.mean() / neg_ret.std() * np.sqrt(252 * 24)) if len(neg_ret) > 0 else 0.0
        calmar    = total_return / max_dd if max_dd > 0 else float("inf")

        avg_bars  = np.mean([t["close_i"] - t["entry_i"] for t in trades]) if trades else 0.0
        r_mult    = [(t["pnl"] / (abs(t["entry_price"] - t["sl"]) * t["qty"]))
                     for t in trades if abs(t.get("entry_price", 0) - t.get("sl", 0)) > 0]

        return BacktestResult(
            symbol=cfg.symbol, interval=cfg.interval,
            start=cfg.start, end=cfg.end, strategy=cfg.strategy,
            initial_capital=cfg.initial_capital, final_equity=self.equity,
            total_return_pct=round(total_return, 2),
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=round(float(sharpe), 3),
            sortino_ratio=round(float(sortino), 3),
            calmar_ratio=round(float(calmar), 3),
            win_rate=round(win_rate, 2),
            profit_factor=round(profit_factor, 3),
            expectancy=round(float(expectancy), 4),
            total_trades=len(trades), winning_trades=len(wins), losing_trades=len(losses),
            avg_win_pct=round(float(avg_win), 3), avg_loss_pct=round(float(avg_loss), 3),
            best_trade_pct=round(best / cfg.initial_capital * 100, 3),
            worst_trade_pct=round(worst / cfg.initial_capital * 100, 3),
            avg_holding_bars=round(float(avg_bars), 1),
            r_multiples=[round(r, 3) for r in r_mult],
            equity_curve=curve,
        )


# ─── OHLCV fetcher (Binance public endpoint — no API key required) ────────────

async def fetch_ohlcv(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame:
    """Download historical klines from Binance."""
    import httpx

    testnet = os.getenv("TESTNET", "false").lower() == "true"
    base    = "https://testnet.binance.vision" if testnet else "https://api.binance.com"
    url     = f"{base}/api/v3/klines"

    start_ms = int(datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms   = int(datetime.strptime(end,   "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)

    all_rows: list[list] = []
    cursor   = start_ms
    limit    = 1000

    async with httpx.AsyncClient(timeout=30) as client:
        while cursor < end_ms:
            params = {"symbol": symbol, "interval": interval,
                      "startTime": cursor, "endTime": end_ms, "limit": limit}
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            all_rows.extend(data)
            cursor = data[-1][0] + 1
            if len(data) < limit:
                break
            logger.info("Fetched %d candles (total %d)", len(data), len(all_rows))

    if not all_rows:
        raise ValueError(f"No data returned for {symbol} {interval} {start}→{end}")

    df = pd.DataFrame(all_rows, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df[["open", "high", "low", "close", "volume"]]


# ─── Report writer ────────────────────────────────────────────────────────────

def save_report(result: BacktestResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{result.symbol}_{result.interval}_{result.strategy}_{result.start[:7]}_{result.end[:7]}"

    # JSON summary
    summary = {k: v for k, v in result.__dict__.items() if k not in ("equity_curve", "r_multiples")}
    (output_dir / f"{tag}_summary.json").write_text(json.dumps(summary, indent=2))

    # Equity curve CSV
    pd.Series(result.equity_curve, name="equity").to_csv(output_dir / f"{tag}_equity.csv")

    # R-multiple distribution CSV
    pd.Series(result.r_multiples, name="r_multiple").to_csv(output_dir / f"{tag}_r_multiples.csv")

    # Console report
    print("\n" + "═" * 60)
    print(f"  NEXUS TRADER BACKTEST — {result.symbol} {result.interval} ({result.strategy})")
    print("═" * 60)
    print(f"  Period           : {result.start} → {result.end}")
    print(f"  Initial Capital  : ${result.initial_capital:,.2f}")
    print(f"  Final Equity     : ${result.final_equity:,.2f}")
    print(f"  Total Return     : {result.total_return_pct:+.2f}%")
    print(f"  Max Drawdown     : {result.max_drawdown_pct:.2f}%")
    print(f"  Sharpe Ratio     : {result.sharpe_ratio:.3f}")
    print(f"  Sortino Ratio    : {result.sortino_ratio:.3f}")
    print(f"  Calmar Ratio     : {result.calmar_ratio:.3f}")
    print("-" * 60)
    print(f"  Total Trades     : {result.total_trades}")
    print(f"  Win Rate         : {result.win_rate:.1f}%")
    print(f"  Profit Factor    : {result.profit_factor:.3f}")
    print(f"  Expectancy       : {result.expectancy:.4f}")
    print(f"  Avg Win          : {result.avg_win_pct:+.3f}%")
    print(f"  Avg Loss         : {result.avg_loss_pct:+.3f}%")
    print(f"  Best Trade       : {result.best_trade_pct:+.3f}%")
    print(f"  Worst Trade      : {result.worst_trade_pct:+.3f}%")
    print(f"  Avg Holding      : {result.avg_holding_bars:.1f} bars")
    print("═" * 60)
    print(f"  Reports saved → {output_dir / tag}_*.json/csv")
    print()


# ─── CLI entry point ──────────────────────────────────────────────────────────

async def main_async(cfg: BacktestConfig) -> None:
    logger.info("Fetching OHLCV data for %s %s %s→%s", cfg.symbol, cfg.interval, cfg.start, cfg.end)
    df = await fetch_ohlcv(cfg.symbol, cfg.interval, cfg.start, cfg.end)
    logger.info("Downloaded %d candles", len(df))

    gen    = SignalGenerator(df, cfg)
    df_sig = gen.get_signals()

    bt     = EventBacktester(df_sig, cfg)
    result = bt.run()

    save_report(result, Path("backtesting/reports"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Nexus Trader Backtester")
    parser.add_argument("--symbol",           default="BTCUSDT")
    parser.add_argument("--interval",         default="15m")
    parser.add_argument("--start",            default="2024-01-01")
    parser.add_argument("--end",              default="2024-12-31")
    parser.add_argument("--strategy",         default="composite",
                        choices=["trend", "mean_reversion", "breakout", "composite"])
    parser.add_argument("--initial-capital",  type=float, default=10_000.0)
    parser.add_argument("--risk-per-trade",   type=float, default=0.01)
    parser.add_argument("--commission",        type=float, default=0.0005)
    args = parser.parse_args()

    cfg = BacktestConfig(
        symbol=args.symbol, interval=args.interval,
        start=args.start, end=args.end, strategy=args.strategy,
        initial_capital=args.initial_capital,
        risk_per_trade=args.risk_per_trade,
        commission_pct=args.commission,
    )
    asyncio.run(main_async(cfg))


if __name__ == "__main__":
    main()
