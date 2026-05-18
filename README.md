# Nexus Trader

Production-grade Python algorithmic trading system with TradingView integration.

## Architecture

```
nexus-trader/
├── .env.example
├── requirements.txt
├── backend/
│   ├── config.py                # Pydantic v2 Settings (singleton)
│   ├── models.py                # All domain models
│   ├── main.py                  # uvicorn entry point
│   ├── api/
│   │   ├── app.py               # FastAPI factory + lifespan
│   │   ├── state.py             # Component wiring (AppState)
│   │   ├── routes.py            # REST endpoints
│   │   └── websocket.py         # WS broadcast hub
│   ├── binance/
│   │   └── binance_client.py    # Async HTTP client (Spot + Futures)
│   ├── core/
│   │   ├── strategy_engine.py   # BaseStrategy + 4 implementations
│   │   ├── trade_logic.py       # Entry/exit/sizing/breakeven
│   │   ├── risk_manager.py      # Risk gate, drawdown, daily loss
│   │   ├── execution_engine.py  # Normalization + retry + dry-run
│   │   ├── portfolio_engine.py  # Reconciliation + PnL analytics
│   │   └── automation_engine.py # APScheduler + EventEmitter
│   └── journal/
│       ├── journal.py           # CSV + SQLite trade journal
│       └── telegram_alerts.py   # Telegram notifications
└── broker_adapter/
    └── tradingview_broker.ts    # Full IBrokerTerminal implementation
```

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Set BINANCE_API_KEY, BINANCE_API_SECRET
# Keep DRY_RUN=true and TESTNET=true for safe testing

# 3. Start the backend
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 4. Verify health
curl http://localhost:8000/api/v1/health
```

## Safety Features

| Feature | Implementation |
|---|---|
| Dry-run mode | All order methods short-circuit to simulation |
| Testnet | Separate Binance testnet URLs |
| Startup reconciliation | `portfolio.reconcile()` must succeed before trading |
| Zero duplicate orders | Idempotency keys + per-candle deduplication |
| Daily loss limit | Auto-pause at -3% daily equity |
| Max drawdown | Emergency stop at -12% from peak |
| Cooldown | 15 min post-SL before new entries |
| Emergency stop | `POST /api/v1/emergency_stop` |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/health` | Liveness + readiness |
| GET | `/api/v1/metrics` | Risk + portfolio analytics |
| GET | `/api/v1/signals` | Last 50 trades |
| POST | `/api/v1/place_order` | Manual order placement |
| POST | `/api/v1/emergency_stop` | Pause trading + kill automation |
| POST | `/api/v1/resume_trading` | Resume after pause |
| POST | `/api/v1/cancel_all` | Cancel open orders |
| POST | `/api/v1/close_all` | Market-close all positions |
| GET | `/api/v1/positions` | Open positions |
| GET | `/api/v1/account` | Account balance |
| WS | `/ws` | Live event stream |

## TradingView Integration

```typescript
import { TradingSystemBroker } from './broker_adapter/tradingview_broker';

const widget = new TradingView.widget({
  // ...other options
  brokerFactory: (host) => new TradingSystemBroker(host),
});
```

Live fills, position changes, and TP/SL hits are pushed via WebSocket to the UI automatically.
