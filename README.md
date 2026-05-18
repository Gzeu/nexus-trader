# 🚀 Nexus Trader

**Production-grade Python Algo Trading System** — Binance Spot & Futures, FastAPI backend, TradingView IBrokerTerminal integration, multi-strategy engine, full risk management, and auto-reconciliation.

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Testnet](https://img.shields.io/badge/Default-Testnet%20%26%20DryRun-orange)](.env.example)

---

## 📐 Architecture

```
nexus-trader/
├── .env.example
├── requirements.txt
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── models.py
│   ├── api/
│   │   ├── app.py
│   │   ├── state.py
│   │   ├── routes.py
│   │   └── websocket.py
│   ├── binance/
│   │   └── binance_client.py
│   ├── core/
│   │   ├── strategy_engine.py
│   │   ├── trade_logic.py
│   │   ├── risk_manager.py
│   │   ├── execution_engine.py
│   │   ├── portfolio_engine.py
│   │   └── automation_engine.py
│   └── journal/
│       ├── journal.py
│       └── telegram_alerts.py
└── broker_adapter/
    └── tradingview_broker.ts
```

---

## ⚡ Quick Start

```bash
git clone https://github.com/Gzeu/nexus-trader.git
cd nexus-trader
cp .env.example .env
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
curl http://localhost:8000/api/v1/health
```

---

## 🔌 REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | System status |
| `GET` | `/api/v1/metrics` | Risk + portfolio metrics |
| `GET` | `/api/v1/positions` | Open positions |
| `POST` | `/api/v1/place_order` | Manual order |
| `POST` | `/api/v1/emergency_stop` | Kill switch |
| `POST` | `/api/v1/close_all` | Close all positions |
| `WS` | `/ws` | Live updates |

---

## 🛡️ Risk Rules

- Max 3 positions · 1% risk/trade · Daily loss -3% → pause
- Max drawdown -12% → emergency stop
- Cooldown 15min after SL · Max 3 consecutive losses
- One position per symbol · Min RR 1.5
- Startup reconciliation required before any trading

---

## 🔄 TradingView

```typescript
import { TradingSystemBroker } from './broker_adapter/tradingview_broker';
const widget = new TradingView.widget({
  brokerFactory: (host) => new TradingSystemBroker(host),
});
```

---

## 📄 License

MIT
