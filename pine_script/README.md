# Pine Script — Nexus Trader Webhook Strategy

## Setup in TradingView

1. **Open** Pine Script editor → paste `nexus_webhook_strategy.pine`
2. **Add to chart** on the desired symbol + timeframe
3. **Create Alert**:
   - Condition: `Nexus Trader Webhook Strategy` → `alert()` function calls
   - Webhook URL: `https://your-backend.com/api/v1/signals`
   - Message: leave empty (JSON is built inside the script)
   - Expiration: Open-ended
   - Check: **Once per bar close** (prevents duplicate signals mid-candle)

## Inputs

| Input | Default | Description |
|---|---|---|
| Strategy Mode | composite | `trend` / `mean_reversion` / `breakout` / `composite` |
| Market Mode | FUTURES | `SPOT` or `FUTURES` |
| Leverage | 10 | Passed to backend for position sizing |
| Risk % per Trade | 1.0 | Backend uses this for quantity calc |
| Min Confidence | 0.60 | Below this threshold → alert not fired |
| ATR Length | 14 | For SL/TP distance |
| ATR × SL | 1.5 | SL = entry ± ATR × 1.5 |
| ATR × TP1 | 2.0 | TP1 = entry ± ATR × 2.0 |
| ATR × TP2 | 3.5 | TP2 = entry ± ATR × 3.5 |

## Backend Route That Receives Webhooks

```
POST /api/v1/signals
Content-Type: application/json

{
  "source": "tradingview",
  "symbol": "BTCUSDT",
  "action": "BUY",
  "confidence": 0.67,
  "entry_type": "market",
  "entry_price": 67420.5,
  "stop_loss": 66100.0,
  "take_profit_1": 68750.0,
  "take_profit_2": 70900.0,
  "timeframe": "15",
  "strategy": "composite",
  "market_mode": "FUTURES",
  "leverage": 10,
  "risk_pct": 1.0,
  "reason": "EMA crossover + RSI + composite vote"
}
```

Backend validates → RiskManager.check_signal() → ExecutionEngine.place_order().
