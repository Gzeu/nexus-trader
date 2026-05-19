#!/usr/bin/env bash
# Validates .env before running — checks required keys and safe defaults
set -euo pipefail
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
ENV_FILE="${1:-.env}"
errors=0

check_required() {
  local key=$1
  if ! grep -qE "^${key}=.+" "$ENV_FILE" 2>/dev/null; then
    echo -e "${RED}[✗] MISSING: $key${NC}"
    ((errors++))
  else
    val=$(grep "^${key}=" "$ENV_FILE" | cut -d= -f2)
    echo -e "${GREEN}[✓] $key${NC} = $val"
  fi
}

check_safe() {
  local key=$1 expected=$2
  local val
  val=$(grep "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "")
  if [ "$val" != "$expected" ]; then
    echo -e "${YELLOW}[!] $key=$val (expected $expected for safe testing)${NC}"
  else
    echo -e "${GREEN}[✓] $key=$val (safe)${NC}"
  fi
}

echo -e "\nChecking $ENV_FILE ..."
check_required "BINANCE_API_KEY"
check_required "BINANCE_API_SECRET"
check_required "SECRET_KEY"
check_safe     "DRY_RUN"  "true"
check_safe     "TESTNET"  "true"
check_required "MARKET_MODE"
check_required "SYMBOL_WHITELIST"

echo ""
if [ "$errors" -gt 0 ]; then
  echo -e "${RED}$errors required variable(s) missing in $ENV_FILE${NC}"
  exit 1
else
  echo -e "${GREEN}.env looks good!${NC}"
fi
