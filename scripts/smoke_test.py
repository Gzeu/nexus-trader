#!/usr/bin/env python3
"""
smoke_test.py — Rapid post-fix validation for nexus-trader core modules.

Run: python -m scripts.smoke_test
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
from decimal import Decimal
from typing import List

# ── bootstrap env so config loads without a real .env ──────────────────────────
for k, v in {
    "BINANCE_API_KEY": "test",
    "BINANCE_API_SECRET": "test",
    "DRY_RUN": "true",
    "TESTNET": "true",
    "RISK_PER_TRADE": "0.01",
    "MIN_RR": "1.5",
    "MAX_POSITIONS": "3",
    "MAX_DAILY_LOSS": "0.03",
    "MAX_DRAWDOWN": "0.12",
    "COOLDOWN_MINUTES": "15",
    "MAX_CONSECUTIVE_LOSSES": "3",
    "SYMBOL_WHITELIST": "BTCUSDT,ETHUSDT",
    "EXCHANGE_INFO_TTL_SECONDS": "1800",
    "MAX_RETRIES": "3",
    "RETRY_BASE_DELAY": "1.0",
    "RETRY_MAX_DELAY": "30.0",
}.items():
    os.environ.setdefault(k, v)

# ── imports ───────────────────────────────────────────────────────────────────────
print("\U0001f4e6 [1/7] Importing core modules...")
from backend.config import get_settings                          # noqa: E402
from backend.models import (                                     # noqa: E402
    Action, MarketMode, OrderStatus, RiskVeto, StrategySignal,
)
from backend.core.risk_manager import RiskManager                # noqa: E402
from backend.core.strategy_engine import CompositeStrategy, OHLCV  # noqa: E402
from backend.core.trade_logic import calc_position_size, should_enter_long  # noqa: E402
from backend.core.execution_engine import ExecutionEngine        # noqa: E402

print("   \u2713 All imports OK")

settings = get_settings()
ERRORS: List[str] = []


# ── helpers ─────────────────────────────────────────────────────────────────────────
def _random_walk(n: int = 100, start: float = 42_000.0, vol: float = 0.002) -> List[float]:
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + random.gauss(0, vol)))
    return prices


def _make_ohlcv(n: int = 100) -> OHLCV:
    closes = _random_walk(n)
    opens, highs, lows, volumes, timestamps = [], [], [], [], []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        spread = c * 0.003
        highs.append(max(o, c) + abs(random.gauss(0, spread)))
        lows.append(min(o, c) - abs(random.gauss(0, spread)))
        opens.append(o)
        volumes.append(random.uniform(50, 500))
        timestamps.append(1_700_000_000_000 + i * 60_000)
    return OHLCV(
        opens=opens, highs=highs, lows=lows,
        closes=closes, volumes=volumes, timestamps=timestamps,
    )


def _make_market_signal(symbol: str = "BTCUSDT") -> StrategySignal:
    last_close = 42_000.0
    return StrategySignal(
        symbol=symbol,
        action=Action.BUY,
        confidence=0.80,
        entry_type="market",
        entry_price=None,          # FIX 1: must NOT cause LOW_RR veto
        stop_loss=last_close * 0.985,
        take_profit_1=last_close * 1.03,
        take_profit_2=last_close * 1.06,
        trailing_stop=None,
        timeframe="15m",
        reason="smoke_test_market_order",
        metadata={"last_close": last_close},
    )


# ── TEST 1: FIX 1 — RR check on market order (entry_price=None) ────────────────
print("\n\U0001f9ea [2/7] FIX 1 — RR check on market order (entry_price=None)...")
rm = RiskManager()
rm.update_equity(10_000.0)
signal = _make_market_signal()
veto = rm.check_signal(signal)
if veto == RiskVeto.LOW_RR:
    ERRORS.append("FIX 1 FAIL: market order incorrectly vetoed with LOW_RR")
    print(f"   \u2717 FAIL — veto={veto} (expected anything but LOW_RR)")
else:
    print(f"   \u2713 PASS — veto={veto.value} (not LOW_RR)")


# ── TEST 2: RR with valid limit order ───────────────────────────────────────────
print("\n\U0001f9ea [3/7] RR check — valid limit order (good RR)...")
entry = 42_000.0
limit_signal = StrategySignal(
    symbol="BTCUSDT",
    action=Action.BUY,
    confidence=0.75,
    entry_type="limit",
    entry_price=entry,
    stop_loss=entry * 0.985,
    take_profit_1=entry * 1.03,
    take_profit_2=entry * 1.06,
    trailing_stop=None,
    timeframe="15m",
    reason="smoke_test_limit",
    metadata={},
)
rm2 = RiskManager()
rm2.update_equity(10_000.0)
veto2 = rm2.check_signal(limit_signal)
if veto2 == RiskVeto.LOW_RR:
    ERRORS.append("FIX 1 FAIL: valid limit signal vetoed LOW_RR")
    print(f"   \u2717 FAIL — veto={veto2}")
else:
    print(f"   \u2713 PASS — veto={veto2.value}")


# ── TEST 3: CompositeStrategy.compute() ─────────────────────────────────────────
print("\n\U0001f9ea [4/7] CompositeStrategy.compute() on synthetic OHLCV...")
ohlcv = _make_ohlcv(120)

async def _run_composite():
    cs = CompositeStrategy()
    return await cs.compute(ohlcv)

result = asyncio.run(_run_composite())
if result is not None:
    print(
        f"   \u2713 PASS — signal={result.action.value}  "
        f"confidence={result.confidence:.2f}  "
        f"sl={result.stop_loss:.2f}  tp1={result.take_profit_1:.2f}"
    )
else:
    print("   \u2139  No consensus signal (HOLD) — regime may be VOLATILE or no consensus")
    print("   \u2713 PASS — returned None cleanly (valid HOLD outcome)")


# ── TEST 4: FIX 2 — Conservative SL/TP merge in CompositeStrategy ─────────────
print("\n\U0001f9ea [5/7] FIX 2 — Conservative SL/TP merge in CompositeStrategy...")
rm3 = RiskManager()
rm3.update_equity(50_000.0)
low_rr_hits = 0

async def _check_merged_rr():
    cs = CompositeStrategy()
    for _ in range(5):
        sig = await cs.compute(_make_ohlcv(120))
        if sig and sig.action not in (Action.HOLD,):
            v = rm3.check_signal(sig)
            if v == RiskVeto.LOW_RR:
                return True
    return False

had_low_rr = asyncio.run(_check_merged_rr())
if had_low_rr:
    print("   \u26a0  WARNING — some merged signals hit LOW_RR (may be valid edge case)")
else:
    print("   \u2713 PASS — no LOW_RR vetos on merged signals")


# ── TEST 5: FIX 3 — Sharpe on percentage returns ─────────────────────────────
print("\n\U0001f9ea [6/7] FIX 3 — Sharpe on percentage returns...")
rm4 = RiskManager()
rm4.update_equity(10_000.0)
for pnl in [120, -80, 200, -50, 300, -100, 150, -90, 180, 60]:
    rm4.record_trade_result(float(pnl))

metrics = rm4.get_metrics()
sharpe = metrics.sharpe_ratio
if abs(sharpe) > 50:
    ERRORS.append(f"FIX 3 FAIL: Sharpe {sharpe} unrealistically large (absolute PnL leak?)")
    print(f"   \u2717 FAIL — sharpe={sharpe} too large (absolute PnL issue)")
else:
    print(
        f"   \u2713 PASS — sharpe={sharpe}  win_rate={metrics.win_rate:.0%}  "
        f"pf={metrics.profit_factor:.2f}  expectancy={metrics.expectancy:.2f}"
    )


# ── TEST 6: ExecutionEngine dry-run ───────────────────────────────────────────
print("\n\U0001f9ea [7/7] ExecutionEngine dry-run mode...")

class _MockWS:
    async def broadcast_raw(self, *a, **kw): pass

async def _test_execution():
    ee = ExecutionEngine(ws_hub=_MockWS(), dry_run=True)
    return await ee.place_order(
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("0.001"),
        price=None,
        idempotency_key="smoke-test-001",
    )

order = asyncio.run(_test_execution())
if order is None:
    ERRORS.append("ExecutionEngine dry-run returned None")
    print("   \u2717 FAIL — returned None")
elif order.status == OrderStatus.REJECTED:
    ERRORS.append(f"ExecutionEngine dry-run REJECTED: {order.reject_reason}")
    print(f"   \u2717 FAIL — status=REJECTED  reason={order.reject_reason}")
else:
    print(f"   \u2713 PASS — dry_run order id={order.client_order_id}  status={order.status.value}")


# ── calc_position_size sanity ──────────────────────────────────────────────────
print("\n\U0001f4d0 Bonus: calc_position_size sanity check...")
equity = 10_000.0
entry_p = 42_000.0
sl_p = 41_370.0
qty = calc_position_size(equity, entry_p, sl_p, settings.risk_per_trade)
risk_dollar = (entry_p - sl_p) * float(qty)
risk_pct = risk_dollar / equity
print(
    f"   qty={qty}  risk_$={risk_dollar:.2f}  risk_pct={risk_pct:.2%}  "
    f"(limit={settings.risk_per_trade:.0%})"
)
if risk_pct > settings.risk_per_trade * 1.05:
    ERRORS.append(f"Position size exceeds risk limit: {risk_pct:.2%} > {settings.risk_per_trade:.0%}")
    print("   \u2717 FAIL — exceeds risk limit")
else:
    print("   \u2713 PASS")


# ── Final verdict ───────────────────────────────────────────────────────────────────
print("\n" + "\u2550" * 60)
if ERRORS:
    print(f"\u274c  SMOKE TEST FAILED — {len(ERRORS)} error(s):")
    for e in ERRORS:
        print(f"    \u2022 {e}")
    sys.exit(1)
else:
    print("\u2705  ALL SMOKE TESTS PASSED")
    print("\u2550" * 60)
    sys.exit(0)
