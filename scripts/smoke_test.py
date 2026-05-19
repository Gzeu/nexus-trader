"""
scripts/smoke_test.py – Post-fix smoke test suite.

Verifies all critical paths without a live Binance connection:
1. Imports of all core modules
2. RiskManager._check_rr() does NOT veto market orders (entry_price=None)
3. CompositeStrategy uses conservative min/max SL/TP (not average)
4. Synthetic OHLCV (100 candles random walk) flows through CompositeStrategy
5. ExecutionEngine dry-run returns DRY_RUN status

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
from uuid import uuid4

# Force testnet + dry_run so no real API calls happen
os.environ.setdefault("TESTNET", "true")
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("BINANCE_API_KEY", "smoke_test_key")
os.environ.setdefault("BINANCE_API_SECRET", "smoke_test_secret")
os.environ.setdefault("MIN_RR", "1.5")
os.environ.setdefault("MAX_POSITIONS", "3")
os.environ.setdefault("RISK_PER_TRADE", "0.01")
os.environ.setdefault("MAX_CONSECUTIVE_LOSSES", "3")
os.environ.setdefault("MAX_DAILY_LOSS", "0.03")
os.environ.setdefault("MAX_DRAWDOWN", "0.12")
os.environ.setdefault("COOLDOWN_MINUTES", "0")
os.environ.setdefault("FUTURES_LEVERAGE", "1")
os.environ.setdefault("SCAN_INTERVAL_SECONDS", "60")
os.environ.setdefault("PRIMARY_TIMEFRAME", "15m")
os.environ.setdefault("EXCHANGE_INFO_TTL_SECONDS", "1800")
os.environ.setdefault("MAX_RETRIES", "3")
os.environ.setdefault("RETRY_BASE_DELAY", "0.01")
os.environ.setdefault("RETRY_MAX_DELAY", "1.0")
os.environ.setdefault("SYMBOL_WHITELIST", "BTCUSDT")

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m●\033[0m"

results: List[tuple] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((name, condition, detail))
    icon = PASS if condition else FAIL
    print(f"  {icon} {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        print(f"     {traceback.format_exc().strip()}" if sys.exc_info()[0] else "")


def make_klines(n: int = 100, start_price: float = 50000.0) -> List:
    """Generate synthetic Binance klines (random walk)."""
    klines = []
    price = start_price
    now_ms = 1_700_000_000_000
    for i in range(n):
        change = random.uniform(-0.005, 0.005) * price
        open_  = price
        close  = price + change
        high   = max(open_, close) * random.uniform(1.0, 1.003)
        low    = min(open_, close) * random.uniform(0.997, 1.0)
        vol    = random.uniform(10, 500)
        t      = now_ms + i * 900_000  # 15m intervals
        klines.append([
            t, str(open_), str(high), str(low), str(close), str(vol),
            t + 899_999, str(close * vol), 100,
            str(vol * 0.6), str(close * vol * 0.6), "0",
        ])
        price = close
    return klines


async def run_tests():
    print(f"\n{INFO} Nexus Trader — Smoke Test Suite")
    print("=" * 50)

    # ── Test 1: Module Imports ────────────────────────────────────────────────
    print(f"\n{INFO} [1] Module imports")
    try:
        from backend.config import get_settings
        from backend.models import (
            Action, MarketMode, Order, OrderRequest, OrderSide,
            OrderStatus, OrderType, RiskVeto, StrategySignal,
        )
        from backend.core.strategy_engine import (
            OHLCV, CompositeStrategy, TrendFollowingStrategy,
            MeanReversionStrategy, BreakoutStrategy, detect_regime,
        )
        from backend.core.trade_logic import (
            calc_position_size, should_enter_long, should_enter_short,
        )
        from backend.core.risk_manager import RiskManager
        from backend.core.execution_engine import ExecutionEngine
        check("All core modules imported", True)
    except Exception as exc:
        check("All core modules imported", False, str(exc))
        print(f"\n{FAIL} Critical import failure — aborting smoke tests.")
        return

    settings = get_settings()

    # ── Test 2: RiskManager._check_rr() with entry_price=None ────────────────
    print(f"\n{INFO} [2] RiskManager — market order RR check (entry_price=None)")
    rm = RiskManager()
    rm.update_equity(10_000.0)

    # Signal with NO entry_price but last_close in metadata (market order)
    sig_market = StrategySignal(
        symbol="BTCUSDT",
        action=Action.BUY,
        confidence=0.75,
        entry_type="market",
        entry_price=None,          # ← the bug scenario
        stop_loss=49_000.0,
        take_profit_1=52_000.0,
        take_profit_2=55_000.0,
        timeframe="15m",
        reason="smoke_test",
        metadata={"last_close": 50_000.0},  # ← FIX 1: fallback price
    )
    veto = rm.check_signal(sig_market)
    check(
        "Market order (entry_price=None) is NOT vetoed as LOW_RR",
        veto != RiskVeto.LOW_RR,
        f"veto={veto.value}",
    )
    check(
        "Market order check_signal returns OK",
        veto == RiskVeto.OK,
        f"veto={veto.value}",
    )

    # Signal that genuinely has bad RR should still be caught
    sig_bad_rr = StrategySignal(
        symbol="BTCUSDT",
        action=Action.BUY,
        confidence=0.75,
        entry_type="market",
        entry_price=None,
        stop_loss=49_900.0,    # SL very close — risk = 100
        take_profit_1=50_050.0,  # TP1 tiny — reward = 50, RR = 0.5
        take_profit_2=50_100.0,
        timeframe="15m",
        reason="bad_rr_test",
        metadata={"last_close": 50_000.0},
    )
    veto_bad = rm.check_signal(sig_bad_rr)
    check(
        "Genuinely bad RR signal IS vetoed as LOW_RR",
        veto_bad == RiskVeto.LOW_RR,
        f"veto={veto_bad.value}",
    )

    # ── Test 3: CompositeStrategy conservative SL/TP (FIX 2) ─────────────────
    print(f"\n{INFO} [3] CompositeStrategy — conservative min/max SL/TP (FIX 2)")
    from backend.models import StrategySignal as SS
    from backend.core.strategy_engine import CompositeStrategy as CS, Action as A

    # Simulate _merge_signals manually with two BUY signals
    class _FakeStrategy:
        pass

    # Two BUY signals with different SL/TP
    s1 = StrategySignal(
        symbol="BTCUSDT", action=Action.BUY, confidence=0.8,
        entry_type="market", entry_price=None,
        stop_loss=48_000.0, take_profit_1=53_000.0, take_profit_2=56_000.0,
        timeframe="15m", reason="s1", metadata={"last_close": 50_000.0},
    )
    s2 = StrategySignal(
        symbol="BTCUSDT", action=Action.BUY, confidence=0.7,
        entry_type="market", entry_price=None,
        stop_loss=49_000.0, take_profit_1=52_000.0, take_profit_2=54_000.0,
        timeframe="15m", reason="s2", metadata={"last_close": 50_000.0},
    )
    # Conservative BUY: SL = min(48k, 49k) = 48k; TP1 = min(53k, 52k) = 52k
    # Average BUY (old): SL = 48.5k; TP1 = 52.5k
    # Conservative is BETTER — SL further away, TP closer (safer RR guaranteed)
    klines = make_klines(100)
    ohlcv  = OHLCV(klines)

    composite = CompositeStrategy(
        strategies=[], symbol="BTCUSDT", timeframe="15m", market_mode=MarketMode.SPOT
    )
    # Direct call to _merge_signals
    merged = composite._merge_signals([(s1, 1.0), (s2, 1.0)], "TRENDING", ohlcv)
    if merged:
        check(
            "Merged SL = min of individual SLs (conservative)",
            merged.stop_loss == 48_000.0,
            f"got sl={merged.stop_loss}",
        )
        check(
            "Merged TP1 = min of individual TP1s (conservative)",
            merged.take_profit_1 == 52_000.0,
            f"got tp1={merged.take_profit_1}",
        )
        check(
            "Merged TP2 = min of individual TP2s",
            merged.take_profit_2 == 54_000.0,
            f"got tp2={merged.take_profit_2}",
        )
    else:
        check("_merge_signals returned a signal", False, "returned None")

    # ── Test 4: CompositeStrategy.compute() with synthetic OHLCV ─────────────
    print(f"\n{INFO} [4] CompositeStrategy.compute() — synthetic 100-candle OHLCV")
    try:
        trend_strat  = TrendFollowingStrategy(symbol="BTCUSDT", timeframe="15m", market_mode=MarketMode.SPOT)
        mean_strat   = MeanReversionStrategy(symbol="BTCUSDT", timeframe="15m", market_mode=MarketMode.SPOT)
        break_strat  = BreakoutStrategy(symbol="BTCUSDT", timeframe="15m", market_mode=MarketMode.SPOT)
        composite_full = CompositeStrategy(
            strategies=[trend_strat, mean_strat, break_strat],
            weights={"TrendFollowingStrategy": 1.5, "MeanReversionStrategy": 1.0, "BreakoutStrategy": 1.2},
            symbol="BTCUSDT", timeframe="15m", market_mode=MarketMode.SPOT,
        )
        random.seed(42)  # deterministic
        klines2 = make_klines(100)
        ohlcv2  = OHLCV(klines2)
        signal  = await composite_full.compute(ohlcv2)
        check(
            "CompositeStrategy.compute() completes without exception",
            True,
        )
        if signal:
            check(
                "Signal has valid SL/TP",
                signal.stop_loss > 0 and signal.take_profit_1 > 0,
                f"action={signal.action.value} sl={signal.stop_loss:.2f} tp1={signal.take_profit_1:.2f}",
            )
            check(
                "Signal has last_close in metadata (FIX 1 compatibility)",
                "last_close" in signal.metadata,
                str(signal.metadata.get("last_close")),
            )
            print(f"     Signal: {signal.action.value} confidence={signal.confidence:.3f} reason={signal.reason[:60]}")
        else:
            check("Signal is None (HOLD) — acceptable for random data", True)
    except Exception as exc:
        check("CompositeStrategy.compute() — no exception", False, str(exc))

    # ── Test 5: ExecutionEngine dry-run ───────────────────────────────────────
    print(f"\n{INFO} [5] ExecutionEngine — dry-run order")
    try:
        mock_client = MagicMock()
        mock_client.get_exchange_info = AsyncMock(return_value={"symbols": []})
        mock_client.get_symbol_price  = AsyncMock(return_value={"price": "50000.00"})
        mock_client.place_order       = AsyncMock(return_value={
            "orderId": "123", "status": "FILLED",
            "origQty": "0.001", "executedQty": "0.001",
            "price": "50000.00", "fills": [],
        })

        engine = ExecutionEngine(spot_client=mock_client)
        await engine.setup()

        req = OrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.001"),
            market_mode=MarketMode.SPOT,
        )
        order = await engine.place_order(req)
        check(
            "ExecutionEngine dry-run returns DRY_RUN status",
            order.status == OrderStatus.DRY_RUN,
            f"status={order.status.value}",
        )
        check(
            "Dry-run order has exchange_order_id starting with DRY_",
            str(order.exchange_order_id).startswith("DRY_"),
            f"id={order.exchange_order_id}",
        )
        check(
            "Dry-run filled_quantity matches requested",
            order.filled_quantity == Decimal("0.001"),
            f"filled={order.filled_quantity}",
        )
    except Exception as exc:
        check("ExecutionEngine dry-run — no exception", False, str(exc))
        traceback.print_exc()

    # ── Test 6: OHLCVProvider cache ───────────────────────────────────────────
    print(f"\n{INFO} [6] OHLCVProvider — cache TTL")
    try:
        from backend.core.ohlcv_provider import OHLCVProvider
        mock_spot = MagicMock()
        mock_spot.get_klines = AsyncMock(return_value=make_klines(100))

        provider = OHLCVProvider(spot_client=mock_spot, cache_ttl=60)
        ohlcv_a = await provider.get_ohlcv("BTCUSDT", "15m")
        ohlcv_b = await provider.get_ohlcv("BTCUSDT", "15m")  # should hit cache

        check("OHLCVProvider returns OHLCV object", isinstance(ohlcv_a, OHLCV))
        check(
            "OHLCVProvider serves cache on second call (get_klines called once)",
            mock_spot.get_klines.call_count == 1,
            f"call_count={mock_spot.get_klines.call_count}",
        )
        check(
            "Cache size is 1 after two identical calls",
            provider.cache_size() == 1,
        )
        await provider.invalidate("BTCUSDT", "15m", MarketMode.SPOT)
        check(
            "Cache empty after invalidate",
            provider.cache_size() == 0,
        )
    except Exception as exc:
        check("OHLCVProvider tests — no exception", False, str(exc))
        traceback.print_exc()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    total  = len(results)

    if failed == 0:
        print(f"\033[92m✓ ALL SMOKE TESTS PASSED ({passed}/{total})\033[0m")
        sys.exit(0)
    else:
        print(f"\033[91m✗ {failed} TEST(S) FAILED ({passed}/{total} passed)\033[0m")
        print("\nFailed tests:")
        for name, ok, detail in results:
            if not ok:
                print(f"  {FAIL} {name}" + (f" — {detail}" if detail else ""))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_tests())
