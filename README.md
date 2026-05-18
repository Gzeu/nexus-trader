# Nexus Trader — Production-Grade Python Algo Trading System

> Dual-mode (Spot + Futures) — TradingView ↔ Backend ↔ Binance sync  
> Zero duplicate orders • Startup reconciliation • DRY_RUN + Testnet defaults

## Architecture

```
nexus-trader/
├── .env.example                    ← All configuration variables
├── requirements.txt
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

## REST Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/health` | System status + reconciliation state |
| GET | `/api/v1/metrics` | Risk + portfolio analytics |
| GET | `/api/v1/signals` | Last 50 journal entries |
| POST | `/api/v1/place_order` | Manual order (blocked if paused) |
| POST | `/api/v1/emergency_stop` | Halt automation + pause risk |
| POST | `/api/v1/resume_trading` | Resume after pause |
| POST | `/api/v1/cancel_all` | Cancel all open orders |
| POST | `/api/v1/close_all` | Close all positions at market |
| GET | `/api/v1/positions` | Open positions |
| GET | `/api/v1/account` | Balances + equity |
| WS | `/ws` | Live events → TradingView UI |

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
| **Emergency stop** | `POST /api/v1/emergency_stop` + Telegram alert |

## TradingView Integration

```typescript
import { TradingSystemBroker } from './broker_adapter/tradingview_broker';

const widget = new TradingView.widget({
  // ...other options
  brokerFactory: (host) => new TradingSystemBroker(host, 'http://localhost:8000'),
});
```

Live fills and position updates are pushed via WebSocket at `ws://localhost:8000/ws`.
The broker adapter auto-reconnects and calls `host.orderUpdate()` / `host.positionUpdate()`
on every relevant event.

## Environment Variables

See `.env.example` for the full list. Key variables:

```env
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
DRY_RUN=true           # true = simulate all orders
TESTNET=true           # true = Binance testnet endpoints
RISK_PER_TRADE=0.01    # 1% risk per trade
MAX_DAILY_LOSS=0.03    # Pause at -3% daily
MAX_DRAWDOWN=0.12      # Stop at -12% from peak
MAX_POSITIONS=3        # Max simultaneous positions
SPOT_WHITELIST=BTCUSDT,ETHUSDT
```
