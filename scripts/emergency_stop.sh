#!/usr/bin/env bash
# ============================================================
# Nexus Trader — Emergency Stop (killswitch manual)
# Usage: bash scripts/emergency_stop.sh
# ============================================================
set -euo pipefail
RED='\033[0;31m'; BOLD='\033[1m'; RESET='\033[0m'; GREEN='\033[0;32m'

echo -e "${RED}${BOLD}"
echo "  ╔════════════════════════════════════════╗"
echo "  ║       ⛔ EMERGENCY STOP ACTIVAT        ║"
echo "  ╚════════════════════════════════════════╝"
echo -e "${RESET}"

# 1. API emergency stop (anulează toate ordinele + pauzează trading)
echo "Apel API emergency_stop..."
curl -sf -X POST http://localhost/api/v1/emergency_stop 2>/dev/null && \
  echo -e "${GREEN}✅ API: trading oprit + ordine anulate${RESET}" || \
  echo "API indisponibil — continui cu stop forțat"

# 2. Dacă API nu răspunde, oprire forțată container
read -p "Oprești și containerul? (da va opri complet sistemul) [y/N]: " c
if [[ "$c" == "y" || "$c" == "Y" ]]; then
  docker compose -f docker-compose.prod.yml stop nexus-trader
  echo -e "${GREEN}✅ Container nexus-trader oprit${RESET}"
fi

echo ""
echo "Pentru restart: bash scripts/deploy.sh --skip-backtest"
echo "Pentru status:  bash scripts/status.sh"
