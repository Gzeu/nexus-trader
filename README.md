# Nexus Trader — Production-Grade Python Algo Trading System

> **Dual-mode (Spot + Futures) — TradingView ↔ Backend ↔ Binance sync**  
> Zero duplicate orders • Startup reconciliation • DRY_RUN + Testnet defaults  
> Vectorized backtesting • Walk-forward optimizer • Structured audit log

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Table of Contents

- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Backtesting](#backtesting)
- [REST Endpoints](#rest-endpoints)
- [Safety Features](#safety-features)
- [Strategy Overview](#strategy-overview)
- [Risk Management](#risk-management)
- [TradingView Integration](#tradingview-integration)
- [Environment Variables](#environment-variables)
- [Known Fixes (Changelog)](#known-fixes-changelog)

---

## Architecture

```
nexus-trader/
├── .env.example                    ← All configuration variables
├── requirements.txt
├── backtesting/
│   ├── backtest_engine.py          ← Vectorized backtest + walk-forward optimizer
│   └── results/                    ← Auto-generated HTML tearsheets + CSV trade logs
├── backend/
│   ├── main.py                     ← uvicorn entry point
│   ├── config.py                   ← Pydantic v2 Settings (singleton)
│   ├── models.py                   ← All domain models (Pydantic v2)
│   ├── api/
│   │   ├── app.py                  ← FastAPI factory + lifespan
│   │   ├── state.py                ← AppState – component wiring
│   │   ├── routes.py               ← REST endpoints
│   │   └── websocket.py            ← WS broadcast hub → TradingView
│   ├── binance/
│   │   └── binance_client.py       ← Async HTTP client (Spot + Futures)
│   ├── core/
│   │   ├── strategy_engine.py      ← BaseStrategy + Trend/MeanRev/Breakout/Composite
│   │   ├── trade_logic.py          ← Entry/exit decisions, sizing, breakeven
│   │   ├── risk_manager.py         ← Risk gate, drawdown, daily loss, cooldown
│   │   ├── execution_engine.py     ← Normalization, idempotency, retry, dry-run
│   │   ├── portfolio_engine.py     ← Reconciliation, balance sync, PnL analytics
│   │   └── automation_engine.py    ← APScheduler + EventEmitter + anti-dupe
│   └── journal/
│       ├── journal.py              ← CSV + SQLite audit log
│       └── telegram_alerts.py      ← Critical event notifications
└── broker_adapter/
    └── tradingview_broker.ts       ← Full IBrokerTerminal implementation
```

---

## Quick Start

```bash
# 1. Clone + install
git clone https://github.com/Gzeu/nexus-trader.git
cd nexus-trader
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env: set BINANCE_API_KEY, BINANCE_API_SECRET
# DRY_RUN=true and TESTNET=true are on by default — safe to start

# 3. Run
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 4. Verify
curl http://localhost:8000/api/v1/health
```

> ⚠️ **Do not go live before running a backtest.** See [Backtesting](#backtesting) below.  
> ⚠️ **Run at least 24h on testnet with `DRY_RUN=true` before switching to mainnet.**

---

## Backtesting

The backtest engine downloads real Binance data (no API key required) and runs a full simulation with fees, slippage, partial TP closes, and breakeven SL logic. All signals use **confirmed candle closes only** — zero lookahead bias.

### Run a standard backtest

```bash
# BTCUSDT 15m — 1 year of data from Binance mainnet (recommended)
python -m backtesting.backtest_engine \
  --symbol BTCUSDT \
  --tf 15m \
  --days 365

# Long + short (Futures)
python -m backtesting.backtest_engine \
  --symbol BTCUSDT \
  --tf 1h \
  --days 365 \
  --futures

# Load from your own CSV (columns: timestamp,open,high,low,close,volume)
python -m backtesting.backtest_engine \
  --symbol BTCUSDT \
  --tf 15m \
  --csv data/btcusdt_15m.csv
```

### Walk-forward parameter optimization

```bash
# Grid-searches 729 parameter combinations, trains on 70%, validates on 30%
python -m backtesting.backtest_engine \
  --symbol BTCUSDT \
  --tf 15m \
  --days 365 \
  --optimize

# Best params saved to:
# backtesting/results/BTCUSDT_15m_params.json
```

### Outputs

| File | Description |
|---|---|
| `backtesting/results/{symbol}_{tf}.html` | Interactive Plotly tearsheet (equity curve, drawdown, entries) |
| `backtesting/results/{symbol}_{tf}_trades.csv` | Full trade log (entry, exit, PnL, reason, bars held) |
| `backtesting/results/{symbol}_{tf}_params.json` | Optimal parameters from walk-forward optimizer |

### Minimum acceptable results before going live

| Metric | Minimum | Good |
|---|---|---|
| `win_rate` | > 0.42 | > 0.52 |
| `profit_factor` | > 1.20 | > 1.80 |
| `sharpe_ratio` | > 0.80 | > 1.50 |
| `max_drawdown` | < 20% | < 10% |
| `total_trades` | > 100 | 200–500 |

> **Do not enable live trading until all five metrics are met.**

### Signal filters applied

- **EMA crossover** — detected on `shift(1)/shift(2)` confirmed bars, executed on next open
- **MACD histogram** — positive for longs, negative for shorts (eliminates ~18% false entries)
- **ATR% volatility guard** — skips entries when `ATR/close > 3%` (choppy markets)
- **Volume filter** — entry only when volume ≥ `vol_mult × 20-bar rolling average`
- **RR gate** — rejects trades with reward/risk < 1.5 before sizing

### Exit logic

1. **TP1** at `0.5 × ATR_TP_MULT` → 40% partial close → SL moves to breakeven
2. **TP2** at `ATR_TP_MULT` → 40% of remainder
3. **Trailing stop** on final 20% (1.5% below peak for longs)
4. **Signal exit** — opposite EMA cross or RSI extreme
5. **SL / Breakeven** — standard stop-loss or breakeven level

---

## REST Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/health` | System status + reconciliation state |
| `GET` | `/api/v1/metrics` | Risk + portfolio analytics |
| `GET` | `/api/v1/signals` | Last 50 journal entries |
| `POST` | `/api/v1/place_order` | Manual order (blocked if paused) |
| `POST` | `/api/v1/emergency_stop` | Halt automation + pause risk |
| `POST` | `/api/v1/resume_trading` | Resume after pause |
| `POST` | `/api/v1/cancel_all` | Cancel all open orders |
| `POST` | `/api/v1/close_all` | Close all positions at market |
| `GET` | `/api/v1/positions` | Open positions |
| `GET` | `/api/v1/account` | Balances + equity |
| `WS` | `/ws` | Live events → TradingView UI |

> `/docs` and `/redoc` are only available when `IS_PRODUCTION=false` (default for local dev).

---

## Safety Features

| Feature | Behavior |
|---|---|
| **DRY_RUN** | All orders simulate — no real exchange calls |
| **TESTNET** | Routes to Binance testnet URLs |
| **Startup reconciliation** | Trading blocked until `portfolio.reconcile()` succeeds |
| **Zero duplicate orders** | Idempotency keys (TTL 1h) + per-candle deduplication |
| **Daily loss limit** | Auto-pause at −3% daily equity |
| **Max drawdown** | Emergency stop at −12% from peak equity |
| **SL cooldown** | 15 min lockout after stop-loss hit |
| **Consecutive losses** | Auto-pause after N consecutive losing trades (configurable) |
| **Emergency stop** | `POST /api/v1/emergency_stop` + Telegram alert |
| **Drift detection** | Periodic reconciliation detects Binance ↔ local state divergence |
| **IS_PRODUCTION guard** | Warns at startup if `/docs` exposed with live trading enabled |

---

## Strategy Overview

The `CompositeStrategy` combines three sub-strategies with weighted voting (weights auto-normalized to sum=1.0):

| Strategy | Logic | Best Conditions |
|---|---|---|
| `TrendFollowingStrategy` | EMA crossover + RSI + MACD histogram + volume | Trending markets |
| `MeanReversionStrategy` | Bollinger Bands extremes + RSI oversold/overbought | Range-bound markets |
| `BreakoutStrategy` | N-candle high/low + volume confirmation | Consolidation breaks |

All strategies return a `StrategySignal` with `confidence`, `entry_price`, `stop_loss`, `take_profit_1`, `take_profit_2`, and `trailing_stop`. `CompositeStrategy` resolves conflicts by weighted vote — signals below `min_consensus` confidence are dropped as `HOLD`.

---

## Risk Management

All risk checks run through `RiskManager.check_signal()` before any order is placed.

`open_position_count` is derived authoritatively from `len(_open_symbols)` — the set is idempotent and cannot desync from the actual state.

```
1. Is system paused?          → VETO_PAUSED
2. Max drawdown exceeded?     → VETO_DRAWDOWN (emergency stop)
3. Daily loss limit reached?  → VETO_DAILY_LOSS (auto-pause)
4. Max positions open?        → VETO_MAX_POSITIONS
5. Symbol already has a pos?  → VETO_DUPLICATE_SYMBOL
6. SL cooldown active?        → VETO_COOLDOWN
7. Consecutive losses limit?  → VETO_CONSECUTIVE_LOSSES
8. Min reward/risk < 1.5?     → VETO_POOR_RR
9. ATR% too high?             → VETO_VOLATILITY
→ OK — signal proceeds to execution
```

Position sizing uses fixed-fractional Kelly: `size = (equity × RISK_PER_TRADE) / SL_distance`. On Futures, the result is divided by leverage.

`equity` in `RiskManager` is synced explicitly after every fill (entry, partial TP, full close) — drawdown is always calculated against real, up-to-date equity.

---

## TradingView Integration

```typescript
import { TradingSystemBroker } from './broker_adapter/tradingview_broker';

const widget = new TradingView.widget({
  // ...other options
  brokerFactory: (host) => new TradingSystemBroker(host, 'http://localhost:8000'),
});
```

Live fills and position updates are pushed via WebSocket at `ws://localhost:8000/ws`. The broker adapter auto-reconnects and calls `host.orderUpdate()` / `host.positionUpdate()` on every relevant event.

### Broker Adapter Methods

| Method | Behavior |
|---|---|
| `placeOrder()` | Posts to `/api/v1/place_order`, validates via `/api/v1/health` first |
| `cancelOrder()` | Cancels single order via Binance client |
| `cancelOrders()` | Batch cancel via `/api/v1/cancel_all` |
| `closePosition()` | Market close via `/api/v1/close_all` |
| `orders()` | Fetches open orders from portfolio state |
| `positions()` | Fetches open positions |
| `executions()` | Fetches recent fills from journal |
| `preOrderChecks()` | Verifies system health before every order |

---

## Environment Variables

See `.env.example` for the full list. Key variables:

```env
# Binance credentials
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret

# Safety defaults (change with care)
DRY_RUN=true           # true = simulate all orders (no real fills)
TESTNET=true           # true = Binance testnet endpoints
                       # NOTE: use mainnet for backtesting (no historical data on testnet)
IS_PRODUCTION=false    # ⚠️ Set to true before any live deploy (hides /docs, /redoc)

# Timeouts
ORDER_TIMEOUT_SECONDS=15      # Per-order asyncio timeout (increase to 30 on slow testnet)
RECONCILE_TIMEOUT_SECONDS=60  # Startup reconciliation timeout (testnet: 60+, mainnet: 30)

# Risk parameters
RISK_PER_TRADE=0.01    # 1% risk per trade
MAX_DAILY_LOSS=0.03    # Auto-pause at -3% daily equity
MAX_DRAWDOWN=0.12      # Emergency stop at -12% from peak equity
MAX_POSITIONS=3        # Max simultaneous open positions
FUTURES_LEVERAGE=5     # Leverage for futures positions

# Symbol whitelists
SPOT_WHITELIST=BTCUSDT,ETHUSDT
FUTURES_WHITELIST=BTCUSDT

# Automation
SCAN_INTERVAL_SECONDS=60     # How often the strategy scan runs
PRIMARY_TIMEFRAME=15m        # Candle timeframe for signals

# Telegram alerts (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

---

## Known Fixes (Changelog)

### v5.0.0 — 2026-05-20

**Risk engine & automation hardening — [commit a9e0e59](https://github.com/Gzeu/nexus-trader/commit/a9e0e59e628b590c9dee60d84d9c5e7b2863d072)**

#### `backend/core/automation_engine.py`

- **FIX — `risk.update_equity()` called after every fill**  
  `RiskManager._equity` was never updated during a trading session — drawdown was always calculated against `0`, which caused either a `ZeroDivisionError` or an immediate `VETO_DRAWDOWN` on the first signal. `update_equity()` is now called explicitly after entry order fill, partial TP close, and full close.

- **FIX — Dead code assignment removed**  
  `order_timeout = cfg = get_settings()` incorrectly assigned the entire `AppSettings` object to `order_timeout` before overwriting it on the next line. Split into `cfg = get_settings()` / `order_timeout = cfg.order_timeout_seconds`.

#### `backend/core/risk_manager.py`

- **FIX — `open_position_count` is now an authoritative property**  
  `_open_position_count: int` was incremented/decremented manually in `on_position_opened()` and `on_trade_closed()`. A double-call on the same symbol caused the counter to exceed the actual set size. Replaced with `@property open_position_count → len(self._open_symbols)`. `set.add()` and `set.discard()` are idempotent — counter cannot desync.

---

### v4.0.0 — 2026-05-20

**Post-launch fixes round 2 — [commit 7bfb54e](https://github.com/Gzeu/nexus-trader/commit/7bfb54e7b4456cd594e990e37bfa498b11c708b6)**

#### `backend/core/automation_engine.py`

- **FIX — `pos.side` normalization for Futures SHORT**  
  Binance Futures returns `"SHORT"` (not `"SELL"`) in position responses. The previous `pos.side.upper() == "SELL"` check silently skipped sign inversion on Futures shorts, leaving `consecutive_losses` always at 0 and the risk manager blind to losses. Fixed to `pos.side.upper() in ("SELL", "SHORT")`.

- **FIX — `_midnight_reset()` trim cap added**  
  `keep = max(2, interval_minutes * 2)` produced `keep=120` at `interval_minutes=60`. Added `_SEEN_CANDLES_KEEP_MAX = 20` module constant and capped with `min(..., _SEEN_CANDLES_KEEP_MAX)`.

- **FIX — `getattr(cfg, ...)` replaced with direct attribute access**  
  `getattr(cfg, "order_timeout_seconds", 15)` masked any `AttributeError` if the field was ever renamed or removed from `Settings`. Replaced with `cfg.order_timeout_seconds` (field guaranteed by Pydantic with `default=15`).

- **FIX — `deque(maxlen)` consistent across all `_seen_candles` init points**  
  Some code paths initialized `deque()` without `maxlen`, others used `deque(maxlen=200)`. All instances now use `deque(maxlen=_SEEN_CANDLES_MAXLEN)` (module constant = 200).

#### `backend/core/portfolio_engine.py`

- **FIX — `remove_position()` idempotent with explicit WARNING**  
  Previously returned `None` silently on double-close or reconciliation drift. Now logs a `WARNING` with symbol name for audit trail. Non-raising, backward-compatible.

---

### v3.3.0 — 2026-05-20

**Post-launch fixes round 1 — [commit 69ba9a5](https://github.com/Gzeu/nexus-trader/commit/69ba9a5900b4a67bdb8874669d57b9633aabcea4)**

#### `backend/binance/binance_client.py`

- **FIX — `get_open_orders(futures=bool)` routing**  
  Always routed to Spot `/api/v3/openOrders`. Added `futures: bool = False` parameter — when `True`, routes to Futures `/fapi/v1/openOrders`. `portfolio_engine.reconcile()` now passes `futures=is_futures` correctly.

- **FIX — `hmac.new()` keyword arguments**  
  Positional `hmac.new(key, msg, digestmod)` raised a `DeprecationWarning` in Python 3.13+. Replaced with explicit `hmac.new(key=..., msg=..., digestmod=hashlib.sha256)`.

- **FIX — `cancel_all_orders(futures=bool)` routing**  
  Added `futures: bool = False` parameter. When `True`, issues `DELETE /fapi/v1/allOpenOrders`; when `False`, issues `DELETE /api/v3/openOrders`.

#### `backend/core/automation_engine.py`

- **FIX — `price_cache` accessed via public property**  
  `self._portfolio._price_cache` (private attribute access) replaced with `self._portfolio.price_cache` (public `@property` added in `portfolio_engine.py`).

- **FIX — `realized_pnl` sign correct for SHORT positions**  
  PnL sign inversion was missing for SHORT closes. Added `if pos.side.upper() == "SELL": realized_pnl *= -1` (later strengthened to include `"SHORT"` in v4.0.0).

- **FIX — `place_order()` wrapped with `asyncio.wait_for()`**  
  Long-running Binance calls could block the automation tick indefinitely. Both entry and exit calls are now gated by `cfg.order_timeout_seconds` (default 15s). On `TimeoutError` → log `ERROR` + `continue`.

#### `backend/core/portfolio_engine.py`

- **ADD — `price_cache` public property**  
  `@property price_cache` exposes `_price_cache` safely, eliminating fragile cross-module private access.

#### `backend/core/risk_manager.py`

- **FIX — `reset_daily()` equity guard**  
  `self._daily_start_equity = self._equity` without checking `_equity > 0` would reset the daily baseline to `0` if called before the first reconciliation. Now logs `WARNING` and skips the update if `_equity == 0`.

#### `.env.example`

- **ADD — `IS_PRODUCTION` with visible warning**  
  Documents that `IS_PRODUCTION=false` exposes `/docs` and `/redoc`. Default kept as `false` for local dev.

- **ADD — `ORDER_TIMEOUT_SECONDS` + `RECONCILE_TIMEOUT_SECONDS`**  
  Documented with recommended values for testnet (higher) vs mainnet (lower).

---

### v3.2.0 — 2026-05-19

**TradingView chart fixes — [commit 7d6b825](https://github.com/Gzeu/nexus-trader/commit/7d6b825ea02de536ea9a7f248b061db6d61568ab)**

#### `TradingChart.tsx`

- **FIX — MACD race condition at mount**  
  The MACD `useEffect` previously checked `candleDataRef.current.length >= 35` at activation time, which silently no-oped if called before `loadData` completed. A stable `populateMACDPaneRef` callback ref now decouples mounting order from data availability: `loadData` calls `populateMACDPaneRef.current?.()` after writing to the candle ref, and the MACD effect calls the same function immediately on mount. Whichever runs second wins — the pane always populates exactly once with complete data.

- **FIX — `barSpacing` TypeScript-safe cast**  
  `(ts.options() as { barSpacing: number }).barSpacing` failed under `strict` mode because LWC v4 types `ts.options()` as `DeepPartial<TimeScaleOptions>`. Replaced with a `Record<string, unknown>` cast and `Number()` coercion with `|| 8` fallback.

- **FIX — `fetch24hChange` NaN guard**  
  `await res.json() as { priceChangePercent: string }` asserted a type without validating the shape. On an invalid symbol or Binance API error, `d.priceChangePercent` was `undefined` → `parseFloat(undefined)` → `NaN` → crash in `.toFixed(2)`. Now typed as `Record<string, unknown>`, gated by `isFinite()`, returns `null` instead of `NaN`.

---

### v1.1.0 — 2026-05-19

**Critical bug fixes — [commit f83f983](https://github.com/Gzeu/nexus-trader/commit/f83f983cb4828fd35529275ac182f03869727f68)**

#### `backtesting/backtest_engine.py`
- **FIX — Lookahead bias in EMA crossover detection** — uses `shift(1)` vs `shift(2)` (confirmed bars only)
- **FIX — Execution price** — fills on `open[i+1]` (next bar open), not `close[i]`
- **FIX — Testnet flag default** — `load_from_binance(testnet=False)` — testnet has no historical OHLCV data
- **ADD — MACD histogram filter** — eliminates ~18% false entries in low-momentum conditions
- **ADD — ATR% volatility guard** — skips entries when `ATR / close > 3%`
- **ADD — Walk-forward parameter optimizer** — 729-combination grid search, 70/30 train/validate split
- **ADD — Interactive HTML tearsheet** — Plotly equity curve, drawdown panel, entry markers

#### `backend/core/automation_engine.py`
- **FIX — `calc_position_size` missing arguments** — now passes `market_mode` and `leverage` correctly
- **FIX — Live candle price** — uses `ohlcv.last_close` (confirmed close), not in-progress candle
- **FIX — Position management uses confirmed close** — `klines[-2][4]` (second-to-last closed candle)

---

## License

MIT — see [LICENSE](LICENSE).
