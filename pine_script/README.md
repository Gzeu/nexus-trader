# Pine Script Webhook Template

## Setup in TradingView

1. Open TradingView → Pine Script Editor
2. Paste `webhook_template.pine`
3. Set your **Webhook Secret** input to match `API_SECRET_KEY` in your `.env`
4. Add to chart → create an **Alert**:
   - **Condition**: `Nexus Trader Webhook: Long Signal` or `Short Signal`
   - **Webhook URL**: `https://your-server.com/api/v1/signals/webhook`
   - **Message**: leave default (script sends JSON via `alert()` function)
5. The alert fires `alert.freq_once_per_bar_close` — one signal per closed candle, no duplicates

## JSON Payload Sent

```json
{
  "secret": "your_api_secret_key",
  "symbol": "BTCUSDT",
  "action": "BUY",
  "entry_type": "market",
  "entry_price": 68000.0,
  "stop_loss": 67200.0,
  "take_profit_1": 70000.0,
  "take_profit_2": 72000.0,
  "confidence": 0.75,
  "timeframe": "15",
  "market_mode": "SPOT",
  "candle_open_time": 1716000000000,
  "reason": "EMA crossover + RSI + MACD + Volume"
}
```

## Backend Endpoint

`POST /api/v1/signals/webhook` → `backend/api/routes_webhook.py`

- Validates `secret` field
- Anti-duplicate via `candle_open_time`
- Full risk gate (RiskManager.check_signal)
- Auto-sizes position from equity
- Broadcasts result via WebSocket to TradingView UI

## Security Notes

- Never expose `API_SECRET_KEY` in public Pine scripts
- Use HTTPS only for webhook URL
- Consider IP allowlisting for TradingView webhook IPs
