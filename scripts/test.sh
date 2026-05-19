#!/usr/bin/env bash
# =============================================================================
# Nexus Trader — Full Test Suite Runner
# Usage: ./scripts/test.sh [unit|integration|backtest|smoke|all]
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
MODE=${1:-all}

if [ -z "${VIRTUAL_ENV:-}" ]; then source .venv/bin/activate; fi

passed=0; failed=0

run_step() {
  local label=$1; shift
  echo -e "\n${CYAN}▶ $label${NC}"
  if "$@"; then
    echo -e "${GREEN}[✓] $label passed${NC}"
    ((passed++))
  else
    echo -e "${RED}[✗] $label FAILED${NC}"
    ((failed++))
  fi
}

# ── Unit tests ──────────────────────────────────────────────────────────────
if [[ "$MODE" == "unit" || "$MODE" == "all" ]]; then
  run_step "Unit tests (pytest)" \
    pytest tests/ -v --tb=short -q \
      -k "not integration and not slow" \
      --ignore=tests/test_integration.py 2>&1 | tee /tmp/nexus_unit.log
fi

# ── Integration tests (need backend running) ────────────────────────────────
if [[ "$MODE" == "integration" || "$MODE" == "all" ]]; then
  echo -e "\n${YELLOW}[!] Integration tests require backend on :8000${NC}"
  if curl -sf http://localhost:8000/api/v1/health > /dev/null 2>&1; then
    run_step "Integration tests" \
      pytest tests/test_integration.py -v --tb=short 2>&1 | tee /tmp/nexus_integration.log
  else
    echo -e "${YELLOW}[!] Backend not running — skipping integration tests${NC}"
    echo -e "    Start with: ./scripts/start_dev.sh"
  fi
fi

# ── Backtesting smoke test ───────────────────────────────────────────────────
if [[ "$MODE" == "backtest" || "$MODE" == "all" ]]; then
  run_step "Backtest engine (BTCUSDT 15m 30 days)" \
    python -m backtesting.backtest_engine \
      --symbol BTCUSDT --interval 15m \
      --start 2024-11-01 --end 2024-11-30 \
      --strategy composite --initial-capital 10000
fi

# ── Smoke test: backend health ───────────────────────────────────────────────
if [[ "$MODE" == "smoke" || "$MODE" == "all" ]]; then
  if curl -sf http://localhost:8000/api/v1/health > /dev/null 2>&1; then
    run_step "Smoke: GET /health" \
      bash -c 'curl -sf http://localhost:8000/api/v1/health | jq .'
    run_step "Smoke: GET /metrics" \
      bash -c 'curl -sf http://localhost:8000/api/v1/metrics | jq .'
    run_step "Smoke: GET /positions" \
      bash -c 'curl -sf http://localhost:8000/api/v1/positions | jq .'
    run_step "Smoke: GET /balance" \
      bash -c 'curl -sf http://localhost:8000/api/v1/balance | jq .'
    run_step "Smoke: DRY RUN place_order" \
      bash -c 'curl -sf -X POST http://localhost:8000/api/v1/place_order \
        -H "Content-Type: application/json" \
        -d '\''{
          "symbol":"BTCUSDT","side":"BUY","quantity":0.001,
          "order_type":"MARKET","market_mode":"SPOT"
        }'\'' | jq .'
  else
    echo -e "${YELLOW}[!] Backend not running — skipping smoke tests${NC}"
  fi
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo -e "\n${CYAN}━━━ Test Summary ━━━${NC}"
echo -e "  Passed: ${GREEN}$passed${NC}"
echo -e "  Failed: ${RED}$failed${NC}"

[ "$failed" -eq 0 ] && exit 0 || exit 1
