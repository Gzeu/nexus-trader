#!/usr/bin/env bash
# =============================================================================
# Nexus Trader — cURL API Examples
# Run individual commands or: bash scripts/curl_examples.sh
# Backend must be running on :8000
# =============================================================================
BASE="http://localhost:8000/api/v1"
H='-H "Content-Type: application/json"'

echo "━━━ Health ━━━"
curl -sf $BASE/health | jq .

echo "━━━ Metrics ━━━"
curl -sf $BASE/metrics | jq .

echo "━━━ Balance ━━━"
curl -sf $BASE/balance | jq .

echo "━━━ Positions ━━━"
curl -sf $BASE/positions | jq .

echo "━━━ Open Orders ━━━"
curl -sf $BASE/orders | jq .

echo "━━━ Signals (last 20) ━━━"
curl -sf "$BASE/signals?limit=20" | jq .

echo "━━━ Journal page 1 ━━━"
curl -sf "$BASE/journal?page=1&page_size=10" | jq .

echo "━━━ DRY RUN: Place MARKET BUY ━━━"
curl -sf -X POST $BASE/place_order \
  -H 'Content-Type: application/json' \
  -d '{
    "symbol":      "BTCUSDT",
    "side":        "BUY",
    "quantity":    0.001,
    "order_type":  "MARKET",
    "market_mode": "SPOT"
  }' | jq .

echo "━━━ DRY RUN: Place LIMIT BUY with SL/TP ━━━"
curl -sf -X POST $BASE/place_order \
  -H 'Content-Type: application/json' \
  -d '{
    "symbol":       "BTCUSDT",
    "side":         "BUY",
    "quantity":     0.001,
    "order_type":   "LIMIT",
    "price":        60000,
    "stop_loss":    58000,
    "take_profit_1":62000,
    "take_profit_2":65000,
    "market_mode":  "SPOT"
  }' | jq .

echo "━━━ Emergency Stop ━━━"
curl -sf -X POST $BASE/emergency_stop | jq .

echo "━━━ Resume Trading ━━━"
curl -sf -X POST $BASE/resume_trading | jq .

echo "━━━ Cancel All Orders ━━━"
curl -sf -X POST $BASE/cancel_all | jq .

echo "━━━ WebSocket test (5 seconds) ━━━"
echo "Install wscat: npm install -g wscat"
echo "Then run: wscat -c ws://localhost:8000/ws"
