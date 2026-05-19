"""
scripts/smoke_test.py – Nexus Trader post-fix smoke test suite v2.

Covers:
  1. All core module imports
  2. FIX 1  — RiskManager._check_rr() does NOT veto market orders (entry_price=None)
  3. FIX 1b — Valid limit order passes RR check
  4. FIX 2  — CompositeStrategy conservative SL/TP merge (no LOW_RR veto)
  5. FIX 3  — _sharpe() on percentage returns (not absolute)
  6. FIX 4  — ExecutionEngine bracket dry-run returns DRY_RUN, ids prefixed DRY_
  7. COMPLETARE 1 — OHLCVProvider cache TTL (get_klines called once on repeated fetch)
  8. Bonus  — calc_position_size stays within risk_per_trade limit
  9. Bonus  — CompositeStrategy.compute() synthetic OHLCV full flow

Run:
    python -m scripts.smoke_test
"""
from __future__ import annotations

import asyncio
import math
import os
import random
import sys
import traceback
from decimal import Decimal
from typing import List
from unittest.mock import AsyncMock, MagicMock

# ── Bootstrap env (no real .env needed) ─────────────────────────────────────
os.environ.setdefault("TESTNET",                  "true")
os.environ.setdefault("DRY_RUN",                  "true")
os.environ.setdefault("BINANCE_API_KEY",           "smoke_test_key")
os.environ.setdefault("BINANCE_API_SECRET",        "smoke_test_secret")
os.environ.setdefault("MIN_RR",                    "1.5")
os.environ.setdefault("MAX_POSITIONS",             "3")
os.environ.setdefault("RISK_PER_TRADE",            "0.01")
os.environ.setdefault("MAX_CONSECUTIVE_LOSSES",    "3")
os.environ.setdefault("MAX_DAILY_LOSS",            "0.03")
os.environ.setdefault("MAX_DRAWDOWN",              "0.12")
os.environ.setdefault("COOLDOWN_MINUTES",          "0")
os.environ.setdefault("FUTURES_LEVERAGE",          "1")
os.environ.setdefault("SCAN_INTERVAL_SECONDS",     "60")
os.environ.setdefault("PRIMARY_TIMEFRAME",         "15m")
os.environ.setdefault("EXCHANGE_INFO_TTL_SECONDS", "1800")
os.environ.setdefault("MAX_RETRIES",               "3")
os.environ.setdefault("RETRY_BASE_DELAY",          "0.01")
os.environ.setdefault("RETRY_MAX_DELAY",           "1.0")
os.environ.setdefault("SYMBOL_WHITELIST",          "BTCUSDT")
os.environ.setdefault("LOG_LEVEL",                 "WARNING")

# ── Colors ───────────────────────────────────────────────────────────────────
PASS = "\033[92m\u2713\033[0m"
FAIL = "\033[91m\u2717\033[0m"
INFO = "\033[94m\u25cf\033[0m"
BOLD = "\033[1m"
RST  = "\033[0m"

results: List[tuple] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((name, condition, detail))
    icon = PASS if condition else FAIL
    suffix = f" \u2014 {detail}" if detail else ""
    print(f"  {icon} {name}{suffix}")


# ── Synthetic data helpers ────────────────────────────────────────────────────

def _random_walk(n: int = 120, start: float = 42_000.0, vol: float = 0.002) -> List[float]:
    """Geometric random walk price series."""
    prices = [start]
    rng = random.Random(42)  # deterministic seed for reproducibility
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + rng.gauss(0, vol)))
    return prices


def make_klines(n: int = 120) -> List[List]:
    """
    Generate n synthetic klines in Binance format:
    [open_time, open, high, low, close, volume, close_time, ...]
    """
    closes = _random_walk(n)
    opens: List[float] = []
    klines = []
    rng = random.Random(99)
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        spread = c * 0.003
        h = max(o, c) + abs(rng.gauss(0, spread))
        lo = min(o, c) - abs(rng.gauss(0, spread))
        vol = rng.uniform(10, 500)
        ts = 1_700_000_000_000 + i * 60_000
        klines.append([
            ts,               # 0 open_time
            str(o),           # 1 open
            str(h),           # 2 high
            str(lo),          # 3 low
            str(c),           # 4 close
            str(vol),         # 5 volume
            ts + 59_999,      # 6 close_time
            "0", "0", "0", "0", "0",  # 7-11 unused
        ])
        opens.append(o)
    return klines


def make_market_signal(
    symbol: str = "BTCUSDT",
    last_close: float = 42_000.0,
) -> object:
    """StrategySignal with entry_price=None — FIX 1 scenario."""
    from backend.models import Action, EntryType, MarketMode, StrategySignal
    return StrategySignal(
        symbol=symbol,
        action=Action.BUY,
        confidence=0.80,
        entry_type=EntryType.MARKET,
        entry_price=None,
        stop_loss=last_close * 0.985,
        take_profit_1=last_close * 1.030,
        take_profit_2=last_close * 1.060,
        trailing_stop=None,
        timeframe="15m",
        reason="smoke_test_market_order",
        metadata={"last_close": last_close},
    )


def make_limit_signal(
    symbol: str = "BTCUSDT",
    entry: float = 42_000.0,
) -> object:
    """StrategySignal with explicit entry_price — valid RR."""
    from backend.models import Action, EntryType, MarketMode, StrategySignal
    return StrategySignal(
        symbol=symbol,
        action=Action.BUY,
        confidence=0.78,
        entry_type=EntryType.LIMIT,
        entry_price=entry,
        stop_loss=entry * 0.985,      # risk  = 1.5 %
        take_profit_1=entry * 1.030,  # reward= 3.0 %  → RR = 2.0 ≥ 1.5 ✓
        take_profit_2=entry * 1.060,
        trailing_stop=None,
        timeframe="15m",
        reason="smoke_test_limit_order",
        metadata={},
    )


# ── Test runner ────────────────────────────────────────────────────────────────

async def run_tests() -> None:
    # ── [1] Imports ─────────────────────────────────────────────────────────
    print(f"\n{BOLD}[1] Core module imports{RST}")
    try:
        from backend.config import get_settings                          # noqa
        from backend.models import (
            Action, EntryType, MarketMode, Order, OrderRequest,
            OrderSide, OrderStatus, OrderType, RiskVeto, StrategySignal,
        )
        from backend.core.risk_manager   import RiskManager
        from backend.core.strategy_engine import OHLCV, CompositeStrategy
        from backend.core.trade_logic    import (
            calc_position_size, should_enter_long, should_enter_short,
        )
        from backend.core.execution_engine import ExecutionEngine
        from backend.core.ohlcv_provider    import OHLCVProvider
        check("All core imports succeed", True)
    except Exception as exc:
        check("All core imports succeed", False, str(exc))
        traceback.print_exc()
        print(f"\n{FAIL} Cannot continue — fix imports first")
        sys.exit(1)

    settings = get_settings()

    # ── [2] FIX 1a — market order RR not vetoed ─────────────────────────────
    print(f"\n{BOLD}[2] FIX 1 — market order (entry_price=None) not LOW_RR vetoed{RST}")
    try:
        rm = RiskManager()
        rm.update_equity(10_000.0)
        sig = make_market_signal()
        veto = rm.check_signal(sig)
        check(
            "Market order veto is NOT LOW_RR",
            veto != RiskVeto.LOW_RR,
            f"veto={veto.value}",
        )
        check(
            "Market order veto is OK (equity set, no open positions)",
            veto == RiskVeto.OK,
            f"veto={veto.value}",
        )
    except Exception as exc:
        check("FIX 1 — no exception", False, str(exc))
        traceback.print_exc()

    # ── [3] FIX 1b — valid limit order passes ───────────────────────────────
    print(f"\n{BOLD}[3] FIX 1b — valid limit order (good RR) passes{RST}")
    try:
        rm2 = RiskManager()
        rm2.update_equity(10_000.0)
        sig2 = make_limit_signal()
        veto2 = rm2.check_signal(sig2)
        check(
            "Limit order with RR=2.0 returns OK",
            veto2 == RiskVeto.OK,
            f"veto={veto2.value}",
        )
    except Exception as exc:
        check("FIX 1b — no exception", False, str(exc))

    # ── [4] CompositeStrategy full flow ─────────────────────────────────────
    print(f"\n{BOLD}[4] CompositeStrategy.compute() on synthetic OHLCV{RST}")
    try:
        klines = make_klines(120)
        ohlcv  = OHLCV(klines)
        cs     = CompositeStrategy()
        signal = await cs.compute(ohlcv)

        check("compute() runs without exception", True)
        if signal is not None:
            check(
                "Signal has required fields",
                all([
                    signal.symbol is not None,
                    signal.action is not None,
                    signal.stop_loss > 0,
                    signal.take_profit_1 > 0,
                    0.0 <= signal.confidence <= 1.0,
                ]),
                f"action={signal.action.value} conf={signal.confidence:.3f} "
                f"sl={signal.stop_loss:.2f} tp1={signal.take_profit_1:.2f}",
            )
        else:
            check("No consensus / HOLD returned cleanly (valid)", True)
    except Exception as exc:
        check("CompositeStrategy — no exception", False, str(exc))
        traceback.print_exc()

    # ── [5] FIX 2 — conservative merge no LOW_RR ────────────────────────────
    print(f"\n{BOLD}[5] FIX 2 — conservative SL/TP merge does not cause LOW_RR veto{RST}")
    try:
        rm3 = RiskManager()
        rm3.update_equity(50_000.0)
        low_rr_hits = 0
        rng = random.Random(7)

        for trial in range(8):
            k = make_klines(120)
            # Add deterministic drift so we get actionable signals
            closes = [float(row[4]) for row in k]
            trend  = 1.0
            for i in range(len(k)):
                trend *= 1 + rng.gauss(0.001, 0.001)  # slight uptrend
                k[i][4] = str(float(k[i][4]) * trend)

            ohlcv_t = OHLCV(k)
            cs2     = CompositeStrategy()
            sig_t   = await cs2.compute(ohlcv_t)
            if sig_t and str(sig_t.action) not in ("HOLD", "CLOSE"):
                v = rm3.check_signal(sig_t)
                if v == RiskVeto.LOW_RR:
                    low_rr_hits += 1

        check(
            "Conservative merge: no LOW_RR veto across 8 trials",
            low_rr_hits == 0,
            f"low_rr_hits={low_rr_hits}/8",
        )
    except Exception as exc:
        check("FIX 2 — no exception", False, str(exc))
        traceback.print_exc()

    # ── [6] FIX 3 — Sharpe on % returns ─────────────────────────────────────
    print(f"\n{BOLD}[6] FIX 3 — _sharpe() uses percentage returns{RST}")
    try:
        rm4 = RiskManager()
        rm4.update_equity(10_000.0)
        for pnl in [120, -80, 200, -50, 300, -100, 150, -90, 180, 60]:
            rm4.record_trade_result(float(pnl))

        metrics = rm4.get_metrics()
        sharpe  = metrics.sharpe_ratio

        check(
            "Sharpe is non-zero with 10 trades",
            sharpe != 0.0,
            f"sharpe={sharpe}",
        )
        check(
            "Sharpe is in realistic range [-5, 5]",
            -5.0 <= sharpe <= 5.0,
            f"sharpe={sharpe} (absolute PnL leak if outside range)",
        )
        check(
            "Win rate is correct (6/10)",
            abs(metrics.win_rate - 0.6) < 0.01,
            f"win_rate={metrics.win_rate:.0%}",
        )
    except Exception as exc:
        check("FIX 3 — no exception", False, str(exc))
        traceback.print_exc()

    # ── [7] FIX 4 — Bracket order dry-run ───────────────────────────────────
    print(f"\n{BOLD}[7] FIX 4 — ExecutionEngine bracket_order dry-run{RST}")
    try:
        mock_client = MagicMock()
        mock_client.get_exchange_info = AsyncMock(return_value={"symbols": []})
        mock_client.get_symbol_price  = AsyncMock(return_value={"price": "42000.00"})
        mock_client.place_order       = AsyncMock(return_value={
            "orderId": "999", "status": "FILLED",
            "origQty": "0.001", "executedQty": "0.001",
            "price": "42000.00", "fills": [],
        })

        engine = ExecutionEngine(spot_client=mock_client)
        await engine.setup()

        entry, sl_order, tp_order = await engine.bracket_order(
            symbol      = "BTCUSDT",
            side        = OrderSide.BUY,
            quantity    = Decimal("0.001"),
            stop_loss   = Decimal("41370.0"),
            take_profit = Decimal("43260.0"),
            market_mode = MarketMode.SPOT,
        )

        check(
            "Entry order status is DRY_RUN",
            entry.status == OrderStatus.DRY_RUN,
            f"status={entry.status.value}",
        )
        check(
            "Entry order id starts with DRY_",
            str(entry.exchange_order_id).startswith("DRY_"),
            f"id={entry.exchange_order_id}",
        )
        check(
            "SL order returned (not None)",
            sl_order is not None,
            f"sl={sl_order.status.value if sl_order else 'None'}",
        )
        check(
            "TP order returned (not None)",
            tp_order is not None,
            f"tp={tp_order.status.value if tp_order else 'None'}",
        )
    except Exception as exc:
        check("FIX 4 — no exception", False, str(exc))
        traceback.print_exc()

    # ── [8] OHLCVProvider cache ──────────────────────────────────────────────
    print(f"\n{BOLD}[8] OHLCVProvider — cache TTL (get_klines called once){RST}")
    try:
        mock_spot = MagicMock()
        mock_spot.get_klines = AsyncMock(return_value=make_klines(120))

        provider  = OHLCVProvider(spot_client=mock_spot, cache_ttl=60)
        ohlcv_a   = await provider.get_ohlcv("BTCUSDT", "15m")
        ohlcv_b   = await provider.get_ohlcv("BTCUSDT", "15m")  # cache hit

        check("Returns OHLCV object",
              isinstance(ohlcv_a, OHLCV))
        check(
            "get_klines called exactly once (cache served second call)",
            mock_spot.get_klines.call_count == 1,
            f"call_count={mock_spot.get_klines.call_count}",
        )
        check(
            "cache_size() == 1 after two identical calls",
            provider.cache_size() == 1,
            f"cache_size={provider.cache_size()}",
        )
        await provider.invalidate("BTCUSDT", "15m", MarketMode.SPOT)
        check(
            "cache empty after invalidate()",
            provider.cache_size() == 0,
        )
    except Exception as exc:
        check("OHLCVProvider — no exception", False, str(exc))
        traceback.print_exc()

    # ── [9] calc_position_size ───────────────────────────────────────────────
    print(f"\n{BOLD}[9] calc_position_size — stays within risk_per_trade{RST}")
    try:
        equity  = 10_000.0
        entry_p = 42_000.0
        sl_p    = 41_370.0   # 1.5% below
        qty     = calc_position_size(
            equity=equity,
            entry=entry_p,
            stop_loss=sl_p,
            market_mode=MarketMode.SPOT,
            leverage=1,
        )
        risk_dollar = (entry_p - sl_p) * qty
        risk_pct    = risk_dollar / equity
        check(
            f"Position size yields risk ≤ {settings.risk_per_trade:.0%}",
            risk_pct <= settings.risk_per_trade * 1.05,
            f"qty={qty:.6f}  risk_$={risk_dollar:.2f}  risk_pct={risk_pct:.2%}",
        )
        check(
            "Position size is positive",
            qty > 0,
            f"qty={qty}",
        )
    except Exception as exc:
        check("calc_position_size — no exception", False, str(exc))
        traceback.print_exc()

    # ── Summary ──────────────────────────────────────────────────────────────
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    total  = len(results)

    print("\n" + "=" * 55)
    if failed == 0:
        print(f"\033[92m{BOLD}\u2713 ALL SMOKE TESTS PASSED ({passed}/{total}){RST}")
        sys.exit(0)
    else:
        print(f"\033[91m{BOLD}\u2717 {failed} TEST(S) FAILED ({passed}/{total} passed){RST}")
        print("\nFailed:")
        for name, ok, detail in results:
            if not ok:
                suf = f" — {detail}" if detail else ""
                print(f"  {FAIL} {name}{suf}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_tests())
