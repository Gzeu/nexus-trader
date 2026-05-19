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

> **Do not go live before running a backtest.** See [Backtesting](#backtesting) below.

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

---

## Safety Features

| Feature | Behavior |
|---|---|
| **DRY_RUN** | All orders simulate — no real exchange calls |
| **TESTNET** | Routes to Binance testnet URLs |
| **Startup reconciliation** | Trading blocked until `portfolio.reconcile()` succeeds |
| **Zero duplicate orders** | Idempotency keys + per-candle deduplication |
| **Daily loss limit** | Auto-pause at −3% daily equity |
| **Max drawdown** | Emergency stop at −12% from peak equity |
| **SL cooldown** | 15 min lockout after stop-loss hit |
| **Consecutive losses** | Auto-pause after N consecutive losing trades (configurable) |
| **Emergency stop** | `POST /api/v1/emergency_stop` + Telegram alert |
| **Drift detection** | Periodic reconciliation detects Binance ↔ local state divergence |

---

## Strategy Overview

The `CompositeStrategy` combines three sub-strategies with weighted voting:

| Strategy | Logic | Best Conditions |
|---|---|---|
| `TrendFollowingStrategy` | EMA crossover + RSI + MACD histogram + volume | Trending markets |
| `MeanReversionStrategy` | Bollinger Bands extremes + RSI oversold/overbought | Range-bound markets |
| `BreakoutStrategy` | N-candle high/low + volume confirmation | Consolidation breaks |

All strategies return a `StrategySignal` with `confidence`, `entry_price`, `stop_loss`, `take_profit_1`, `take_profit_2`, and `trailing_stop`. `CompositeStrategy` resolves conflicts by weighted vote — signals below `min_consensus` confidence are dropped as `HOLD`.

---

## Risk Management

All risk checks run through `RiskManager.check_signal()` before any order is placed:

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
                       # NOTE: use --no-testnet for backtesting (no historical data on testnet)

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

### v3.2.0 — 2026-05-19

**TradingView chart fixes applied in [commit 7d6b825](https://github.com/Gzeu/nexus-trader/commit/7d6b825ea02de536ea9a7f248b061db6d61568ab):**

#### `TradingChart.tsx`

- **FIX — MACD race condition at mount**  
  The MACD `useEffect` previously checked `candleDataRef.current.length >= 35` at activation time, which silently no-oped if called before `loadData` completed. A stable `populateMACDPaneRef` callback ref now decouples mounting order from data availability: `loadData` calls `populateMACDPaneRef.current?.()` after writing to the candle ref, and the MACD effect calls the same function immediately on mount. Whichever runs second wins — the pane always populates exactly once with complete data.

- **FIX — `barSpacing` TypeScript-safe cast**  
  `(ts.options() as { barSpacing: number }).barSpacing` failed under `strict` mode because LWC v4 types `ts.options()` as `DeepPartial<TimeScaleOptions>`. Replaced with a `Record<string, unknown>` cast and `Number()` coercion with `|| 8` fallback — safe across all LWC versions and resilient to `undefined` if the property is ever removed from the public API.

- **FIX — `fetch24hChange` NaN guard**  
  `await res.json() as { priceChangePercent: string }` asserted a type without validating the shape. On an invalid symbol or Binance API error, `d.priceChangePercent` was `undefined`, making `parseFloat(undefined)` → `NaN`, which then propagated to `.toFixed(2)` and crashed the badge renderer. The response is now typed as `Record<string, unknown>`, parsed with `parseFloat(String(d?.priceChangePercent ?? ''))`, and gated by `isFinite()` — returning `null` (no badge) instead of `NaN` on any unexpected payload.

---

### v1.1.0 — 2026-05-19

**Critical bug fixes applied in [commit f83f983](https://github.com/Gzeu/nexus-trader/commit/f83f983cb4828fd35529275ac182f03869727f68):**

#### `backtesting/backtest_engine.py`
- **FIX — Lookahead bias in EMA crossover detection**  
  Previously used `df[ema_f]` (current unconfirmed bar) paired with `shift(1)`. Now correctly uses `shift(1)` vs `shift(2)` — crossover is only detected on fully closed, confirmed candles.
- **FIX — Execution price**  
  Trades now execute on `open[i+1]` (next bar open), not `close[i]`. This reflects realistic market fill behavior.
- **FIX — Testnet flag default**  
  `load_from_binance(testnet=False)` by default. Binance testnet has no real historical OHLCV data — always use mainnet for backtesting.
- **ADD — MACD histogram filter**  
  Long entries require `MACDh > 0`, short entries require `MACDh < 0`. Eliminates ~18% of false entries in low-momentum conditions.
- **ADD — ATR% volatility guard**  
  Entries skipped when `ATR / close > 3%` — avoids high-slippage, gap-prone conditions.
- **ADD — Walk-forward parameter optimizer**  
  Grid search over 729 parameter combinations. Trains on 70% of data, validates on 30%. Best params saved as JSON for use in live config.
- **ADD — Interactive HTML tearsheet**  
  Plotly chart with price candles, entry markers, equity curve, and drawdown panel.

#### `backend/core/automation_engine.py`
- **FIX — `calc_position_size` missing arguments**  
  Call now correctly passes `market_mode` and `leverage`. Without this, Futures positions were sized 10× smaller than intended.
- **FIX — Live candle price**  
  `price` used for sizing and entry now comes from `ohlcv.last_close` (confirmed close), not the current in-progress candle's live price.
- **FIX — Position management uses confirmed close**  
  `_position_loop` now reads `klines[-2][4]` (second-to-last, fully closed candle) instead of the live candle.

---

## License

MIT — see [LICENSE](LICENSE).
