# Nexus Trader

> **Complete algorithmic trading system** — manual trading from TradingView and automated trading via Python engine, with perfect synchronization between Binance ↔ Backend ↔ UI.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What it does

Nexus Trader combines manual trading through TradingView with an autonomous Python engine, on the same Binance account, without conflicts and without duplicate orders.

- **Manual trading** — place orders directly from TradingView, just like any broker. Positions and fills appear instantly in the UI.
- **Automated trading** — the engine runs configured strategies (Trend, Mean Reversion, Breakout, or a composite with weighted voting) and places orders without human intervention.
- **Bidirectional sync** — any change on Binance (fill, SL hit, liquidation) is immediately reflected in TradingView and in internal state.
- **Spot and Futures** — configurable per symbol, with leverage, whitelist, and separate mode.

---

## Requirements

- Python 3.11+
- Node.js 18+ (for the TypeScript broker adapter)
- Binance account with API key (testnet recommended at first)
- Optional: PostgreSQL for persistent journal, Redis for idempotency

---

## Installation & Quickstart

```bash
# 1. Clone and install dependencies
git clone https://github.com/Gzeu/nexus-trader.git
cd nexus-trader
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Open .env and set at minimum:
#   BINANCE_API_KEY=...
#   BINANCE_API_SECRET=...
# DRY_RUN=true and TESTNET=true are active by default — no risk on first start

# 3. Start the server
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 4. Check status
curl http://localhost:8000/api/v1/health
```

> ⚠️ **Do not enable live trading without prior backtesting.** See the [Backtesting](#backtesting) section.
> ⚠️ **Run for at least 24h on testnet with `DRY_RUN=true` before going mainnet.**

---

## TradingView Integration

```typescript
import { TradingSystemBroker } from './broker_adapter/tradingview_broker';

const widget = new TradingView.widget({
  // ...other options
  brokerFactory: (host) => new TradingSystemBroker(host, 'http://localhost:8000'),
});
```

Fills and position updates are pushed via WebSocket at `ws://localhost:8000/ws`. The broker adapter auto-reconnects and calls `host.orderUpdate()` / `host.positionUpdate()` on every relevant event.

---

## Backtesting

The backtesting engine downloads real data from Binance (no API key required) and runs a full simulation with commissions, slippage, partial TPs, and breakeven logic. All signals use **exclusively confirmed candles** — zero lookahead bias.

### Quick command

```bash
# BTCUSDT 15m — 1 year of data
python -m backtesting.backtest_engine \
  --symbol BTCUSDT \
  --tf 15m \
  --days 365

# With walk-forward optimizer (~5 min)
python -m backtesting.backtest_engine \
  --symbol BTCUSDT \
  --tf 15m \
  --days 365 \
  --optimize
```

### Output files

| File | Content |
|------|---------|
| `backtesting/results/{symbol}_{tf}.html` | Interactive Plotly tearsheet (equity curve, drawdown, entries) |
| `backtesting/results/{symbol}_{tf}_trades.csv` | Full trade log (entry, exit, PnL, reason, bars held) |
| `backtesting/results/{symbol}_{tf}_params.json` | Optimal parameters from walk-forward optimizer |

### Minimum thresholds before going live

| Metric | Minimum | Good |
|--------|---------|------|
| `win_rate` | > 0.42 | > 0.52 |
| `profit_factor` | > 1.20 | > 1.80 |
| `sharpe_ratio` | > 0.80 | > 1.50 |
| `max_drawdown` | < 20% | < 10% |
| `total_trades` | > 100 | 200–500 |

---

## Risk Management

All checks run through `RiskManager.check_signal()` before any order. If any condition fails, the signal is vetoed with an explicit code.

```
1. System paused?                    → VETO_PAUSED
2. Max drawdown exceeded?            → VETO_DRAWDOWN  (auto emergency stop)
3. Daily loss limit reached?         → VETO_DAILY_LOSS (auto pause)
4. Too many open positions?          → VETO_MAX_POSITIONS
5. Symbol already open?              → VETO_DUPLICATE_SYMBOL
6. Cooldown active after SL?         → VETO_COOLDOWN
7. Too many consecutive losses?      → VETO_CONSECUTIVE_LOSSES
8. RR < 1.5?                         → VETO_POOR_RR
9. ATR% volatility too high?         → VETO_VOLATILITY
→ OK — signal reaches execution
```

**Sizing:** `size = (equity × RISK_PER_TRADE) / sl_distance`. On Futures, the result is divided by leverage.

---

## Available Strategies

| Strategy | Logic | Optimal conditions |
|----------|-------|--------------------|
| `TrendFollowingStrategy` | EMA crossover + RSI + MACD histogram + volume | Trending markets |
| `MeanReversionStrategy` | Bollinger Bands + RSI oversold/overbought | Range-bound markets |
| `BreakoutStrategy` | N-candle high/low + volume confirmation | Breakout from consolidation |
| `CompositeStrategy` | Weighted voting (auto-normalized weights) | Any market conditions |

`CompositeStrategy` resolves conflicts through weighted voting — signals below the `min_consensus` threshold are ignored as `HOLD`.

---

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/health` | System status + reconciliation state |
| `GET` | `/api/v1/metrics` | Risk + portfolio analytics |
| `GET` | `/api/v1/signals` | Last 50 signals from journal |
| `GET` | `/api/v1/positions` | Open positions |
| `GET` | `/api/v1/account` | Balances + equity |
| `POST` | `/api/v1/place_order` | Manual order (blocked if system paused) |
| `POST` | `/api/v1/emergency_stop` | Immediate stop + auto pause |
| `POST` | `/api/v1/resume_trading` | Resume after pause |
| `POST` | `/api/v1/cancel_all` | Cancel all open orders |
| `POST` | `/api/v1/close_all` | Close all positions at market |
| `WS` | `/ws` | Live events → TradingView UI |

> `/docs` and `/redoc` are available only when `IS_PRODUCTION=false` (default locally).

---

## Safety Protections

| Protection | Behavior |
|------------|----------|
| **DRY_RUN** | All orders are simulated — zero real exchange calls |
| **TESTNET** | Routed to Binance testnet endpoints |
| **Startup reconciliation** | Trading blocked until `portfolio.reconcile()` succeeds |
| **Zero duplicate orders** | Idempotency keys with 1h TTL + per-candle deduplication |
| **Daily loss limit** | Auto-pause at −3% daily equity |
| **Max drawdown** | Emergency stop at −12% from peak equity |
| **Cooldown after SL** | 15-minute lockout after a stop-loss |
| **Consecutive losses** | Auto-pause after N consecutive losses (configurable) |
| **Emergency stop** | `POST /api/v1/emergency_stop` + Telegram alert |
| **Drift detection** | Periodic reconciliation detects Binance ↔ local state divergence |

---

## Configuration Variables

Full settings are in `.env.example`. The most important ones:

```env
# Binance credentials
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret

# Operating mode (safe defaults)
DRY_RUN=true           # true = full simulation, no real orders
TESTNET=true           # true = Binance testnet endpoints
IS_PRODUCTION=false    # ⚠️ Set true before any live deploy (hides /docs)

# Timeouts (increase on testnet)
ORDER_TIMEOUT_SECONDS=15
RECONCILE_TIMEOUT_SECONDS=60

# Risk parameters
RISK_PER_TRADE=0.01    # 1% risk per trade
MAX_DAILY_LOSS=0.03    # Auto-pause at -3% daily loss
MAX_DRAWDOWN=0.12      # Emergency stop at -12% from peak
MAX_POSITIONS=3        # Maximum simultaneous positions
FUTURES_LEVERAGE=5

# Allowed symbols
SPOT_WHITELIST=BTCUSDT,ETHUSDT
FUTURES_WHITELIST=BTCUSDT

# Automation
SCAN_INTERVAL_SECONDS=60
PRIMARY_TIMEFRAME=15m

# Telegram (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

---

## Project Structure

```
nexus-trader/
├── .env.example
├── requirements.txt
├── backtesting/
│   ├── backtest_engine.py       ← Vectorized backtest + walk-forward optimizer
│   └── results/                 ← Auto-generated HTML tearsheets + CSVs
├── backend/
│   ├── main.py                  ← Uvicorn entry point
│   ├── config.py                ← Pydantic v2 Settings (singleton)
│   ├── models.py                ← All domain models
│   ├── api/
│   │   ├── app.py               ← FastAPI factory + lifespan
│   │   ├── state.py             ← AppState — component wiring
│   │   ├── routes.py            ← REST endpoints
│   │   └── websocket.py         ← WebSocket broadcast hub → TradingView
│   ├── binance/
│   │   └── binance_client.py    ← Async HTTP client (Spot + Futures)
│   ├── core/
│   │   ├── strategy_engine.py   ← BaseStrategy + Trend/MeanRev/Breakout/Composite
│   │   ├── trade_logic.py       ← Entry/exit decisions, sizing, breakeven
│   │   ├── risk_manager.py      ← Risk gate, drawdown, daily loss, cooldown
│   │   ├── execution_engine.py  ← Normalization, idempotency, retry, dry-run
│   │   ├── portfolio_engine.py  ← Reconciliation, balance sync, PnL analytics
│   │   └── automation_engine.py ← APScheduler + EventEmitter + anti-dupe
│   └── journal/
│       ├── journal.py           ← CSV + SQLite journal
│       └── telegram_alerts.py   ← Telegram notifications for critical events
└── broker_adapter/
    └── tradingview_broker.ts    ← Full IBrokerTerminal implementation
```

---

## License

MIT — see [LICENSE](LICENSE).
