# Nexus Trader

> **Sistem complet de trading algoritmic** — manual din TradingView și automat prin engine Python, cu sincronizare perfectă Binance ↔ Backend ↔ UI.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Ce face

Nexus Trader combină trading manual prin TradingView cu un engine Python autonom, pe același cont Binance, fără conflicte și fără ordere duplicate.

- **Trading manual** — plasezi ordere direct din TradingView, ca la orice broker. Pozițiile și fill-urile apar instant în UI.
- **Trading automat** — engine-ul rulează strategiile configurate (Trend, Mean Reversion, Breakout sau un composite cu weighted voting) și plasează ordere fără intervenție umană.
- **Sincronizare bidirecțională** — orice schimbare pe Binance (fill, SL atins, lichidare) se reflectă imediat în TradingView și în starea internă.
- **Spot și Futures** — configurabil per simbol, cu leverage, whitelist și mod separat.

---

## Cerințe

- Python 3.11+
- Node.js 18+ (pentru broker adapter TypeScript)
- Cont Binance cu API key (testnet recomandat la început)
- Opțional: PostgreSQL pentru jurnal persistent, Redis pentru idempotency

---

## Instalare și pornire

```bash
# 1. Clonează și instalează dependențele
git clone https://github.com/Gzeu/nexus-trader.git
cd nexus-trader
pip install -r requirements.txt

# 2. Configurează
cp .env.example .env
# Deschide .env și setează cel puțin:
#   BINANCE_API_KEY=...
#   BINANCE_API_SECRET=...
# DRY_RUN=true și TESTNET=true sunt active implicit — nu riști nimic la primul start

# 3. Pornește serverul
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 4. Verifică starea
curl http://localhost:8000/api/v1/health
```

> ⚠️ **Nu activa live trading fără un backtest prealabil.** Vezi secțiunea [Backtesting](#backtesting).  
> ⚠️ **Rulează minimum 24h pe testnet cu `DRY_RUN=true` înainte de mainnet.**

---

## Integrare TradingView

```typescript
import { TradingSystemBroker } from './broker_adapter/tradingview_broker';

const widget = new TradingView.widget({
  // ...alte opțiuni
  brokerFactory: (host) => new TradingSystemBroker(host, 'http://localhost:8000'),
});
```

Fill-urile și actualizările de poziții sunt trimise prin WebSocket la `ws://localhost:8000/ws`. Broker adapter-ul reconectează automat și apelează `host.orderUpdate()` / `host.positionUpdate()` la fiecare eveniment relevant.

---

## Backtesting

Engine-ul de backtesting descarcă date reale de pe Binance (fără API key) și rulează o simulare completă cu comisioane, slippage, TP parțiale și logică de breakeven. Toate semnalele folosesc **exclusiv lumânări confirmate** — zero lookahead bias.

### Comandă rapidă

```bash
# BTCUSDT 15m — 1 an de date
python -m backtesting.backtest_engine \
  --symbol BTCUSDT \
  --tf 15m \
  --days 365

# Cu optimizator walk-forward (durează ~5 min)
python -m backtesting.backtest_engine \
  --symbol BTCUSDT \
  --tf 15m \
  --days 365 \
  --optimize
```

### Ce generează

| Fișier | Conținut |
|--------|----------|
| `backtesting/results/{symbol}_{tf}.html` | Tearsheet interactiv Plotly (equity curve, drawdown, intrări) |
| `backtesting/results/{symbol}_{tf}_trades.csv` | Log complet al tranzacțiilor (entry, exit, PnL, motiv, bars held) |
| `backtesting/results/{symbol}_{tf}_params.json` | Parametrii optimi din walk-forward optimizer |

### Praguri minime înainte de live

| Metrică | Minim | Bun |
|---------|-------|-----|
| `win_rate` | > 0.42 | > 0.52 |
| `profit_factor` | > 1.20 | > 1.80 |
| `sharpe_ratio` | > 0.80 | > 1.50 |
| `max_drawdown` | < 20% | < 10% |
| `total_trades` | > 100 | 200–500 |

---

## Gestionarea riscului

Toate verificările rulează prin `RiskManager.check_signal()` înainte de orice ordin. Dacă oricare condiție pică, semnalul este vetou-it cu un cod explicit.

```
1. Sistem pauzat?                → VETO_PAUSED
2. Drawdown maxim depășit?       → VETO_DRAWDOWN  (emergency stop automat)
3. Limita zilnică de pierdere?   → VETO_DAILY_LOSS (auto-pauză)
4. Prea multe poziții deschise?  → VETO_MAX_POSITIONS
5. Simbol deja deschis?          → VETO_DUPLICATE_SYMBOL
6. Cooldown activ după SL?       → VETO_COOLDOWN
7. Prea multe pierderi consecutive? → VETO_CONSECUTIVE_LOSSES
8. RR < 1.5?                     → VETO_POOR_RR
9. Volatilitate ATR% prea mare?  → VETO_VOLATILITY
→ OK — semnalul ajunge la execution
```

**Sizing:** `size = (equity × RISK_PER_TRADE) / distanță_SL`. Pe Futures, rezultatul este împărțit la leverage.

---

## Strategii disponibile

| Strategie | Logică | Condiții optime |
|-----------|--------|-----------------|
| `TrendFollowingStrategy` | EMA crossover + RSI + MACD histogram + volum | Piețe în trend |
| `MeanReversionStrategy` | Bollinger Bands + RSI oversold/overbought | Piețe range-bound |
| `BreakoutStrategy` | High/low N lumânări + confirmare volum | Breakout din consolidare |
| `CompositeStrategy` | Weighted voting (weights auto-normalizate) | Orice condiții de piață |

`CompositeStrategy` rezolvă conflictele prin vot ponderat — semnalele sub pragul `min_consensus` sunt ignorate ca `HOLD`.

---

## API REST

| Metodă | Endpoint | Descriere |
|--------|----------|-----------|
| `GET` | `/api/v1/health` | Starea sistemului + reconciliation state |
| `GET` | `/api/v1/metrics` | Analize risk + portfolio |
| `GET` | `/api/v1/signals` | Ultimele 50 semnale din jurnal |
| `GET` | `/api/v1/positions` | Poziții deschise |
| `GET` | `/api/v1/account` | Balanțe + equity |
| `POST` | `/api/v1/place_order` | Ordin manual (blocat dacă sistem pauzat) |
| `POST` | `/api/v1/emergency_stop` | Oprire imediată + pauză automată |
| `POST` | `/api/v1/resume_trading` | Reia după pauză |
| `POST` | `/api/v1/cancel_all` | Anulează toate ordinele deschise |
| `POST` | `/api/v1/close_all` | Închide toate pozițiile la market |
| `WS` | `/ws` | Evenimente live → TradingView UI |

> `/docs` și `/redoc` sunt disponibile doar când `IS_PRODUCTION=false` (default local).

---

## Protecții de siguranță

| Protecție | Comportament |
|-----------|-------------|
| **DRY_RUN** | Toate ordinele sunt simulate — zero apeluri reale la exchange |
| **TESTNET** | Rutat pe endpoint-urile Binance testnet |
| **Reconciliere la startup** | Trading blocat până când `portfolio.reconcile()` reușește |
| **Zero ordere duplicate** | Idempotency keys cu TTL 1h + deduplicare per lumânare |
| **Limita zilnică de pierdere** | Auto-pauză la −3% equity zilnic |
| **Drawdown maxim** | Emergency stop la −12% față de peak equity |
| **Cooldown după SL** | Lockout 15 min după un stop-loss |
| **Pierderi consecutive** | Auto-pauză după N pierderi la rând (configurabil) |
| **Emergency stop** | `POST /api/v1/emergency_stop` + alertă Telegram |
| **Drift detection** | Reconciliere periodică detectează divergența Binance ↔ stare locală |

---

## Variabile de configurare

Setările complete sunt în `.env.example`. Cele mai importante:

```env
# Credențiale Binance
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret

# Mod de operare (implicit sigur)
DRY_RUN=true           # true = simulare completă, fără ordere reale
TESTNET=true           # true = endpoint-uri Binance testnet
IS_PRODUCTION=false    # ⚠️ Setează true înainte de orice deploy live (ascunde /docs)

# Timeout-uri (mărește pe testnet)
ORDER_TIMEOUT_SECONDS=15
RECONCILE_TIMEOUT_SECONDS=60

# Parametri de risc
RISK_PER_TRADE=0.01    # 1% risc per tranzacție
MAX_DAILY_LOSS=0.03    # Pauză automată la -3% pierdere zilnică
MAX_DRAWDOWN=0.12      # Emergency stop la -12% față de peak
MAX_POSITIONS=3        # Număr maxim de poziții simultane
FUTURES_LEVERAGE=5

# Simboluri permise
SPOT_WHITELIST=BTCUSDT,ETHUSDT
FUTURES_WHITELIST=BTCUSDT

# Automatizare
SCAN_INTERVAL_SECONDS=60
PRIMARY_TIMEFRAME=15m

# Telegram (opțional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

---

## Structura proiectului

```
nexus-trader/
├── .env.example
├── requirements.txt
├── backtesting/
│   ├── backtest_engine.py       ← Backtest vectorizat + walk-forward optimizer
│   └── results/                 ← Tearsheet-uri HTML + CSV-uri generate automat
├── backend/
│   ├── main.py                  ← Entry point uvicorn
│   ├── config.py                ← Pydantic v2 Settings (singleton)
│   ├── models.py                ← Toate modelele de domeniu
│   ├── api/
│   │   ├── app.py               ← FastAPI factory + lifespan
│   │   ├── state.py             ← AppState — wiring componente
│   │   ├── routes.py            ← Endpoint-uri REST
│   │   └── websocket.py         ← WebSocket broadcast hub → TradingView
│   ├── binance/
│   │   └── binance_client.py    ← Client async HTTP (Spot + Futures)
│   ├── core/
│   │   ├── strategy_engine.py   ← BaseStrategy + Trend/MeanRev/Breakout/Composite
│   │   ├── trade_logic.py       ← Decizii entry/exit, sizing, breakeven
│   │   ├── risk_manager.py      ← Risk gate, drawdown, daily loss, cooldown
│   │   ├── execution_engine.py  ← Normalizare, idempotency, retry, dry-run
│   │   ├── portfolio_engine.py  ← Reconciliere, sync balanțe, analize PnL
│   │   └── automation_engine.py ← APScheduler + EventEmitter + anti-dupe
│   └── journal/
│       ├── journal.py           ← Jurnal CSV + SQLite
│       └── telegram_alerts.py   ← Notificări Telegram pentru evenimente critice
└── broker_adapter/
    └── tradingview_broker.ts    ← Implementare completă IBrokerTerminal
```

---

## Licență

MIT — vezi [LICENSE](LICENSE).
