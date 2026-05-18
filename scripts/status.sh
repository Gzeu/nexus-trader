#!/usr/bin/env bash
# ============================================================
# Nexus Trader — Status Dashboard (terminal)
# Usage: bash scripts/status.sh
# ============================================================
BOLD='\033[1m'; RESET='\033[0m'
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'

echo -e "${BOLD}\n═══════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  🤖 Nexus Trader — Status Dashboard${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════════${RESET}\n"

# ── Containere ──────────────────────────────────────────────
echo -e "${CYAN}CONTAINERE:${RESET}"
docker compose -f docker-compose.prod.yml ps 2>/dev/null || \
  docker ps --filter "name=nexus" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# ── Health API ──────────────────────────────────────────────
echo -e "\n${CYAN}API HEALTH:${RESET}"
HEALTH=$(curl -sf http://localhost/health 2>/dev/null || echo '{"status":"DOWN"}')
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"

# ── Metrici trading ─────────────────────────────────────────
echo -e "\n${CYAN}METRICI TRADING:${RESET}"
METRICS=$(curl -sf http://localhost/api/v1/metrics 2>/dev/null || echo '{}')
echo "$METRICS" | python3 -c "
import sys, json
try:
    m = json.load(sys.stdin)
    print(f\"  Win Rate:      {m.get('win_rate',0):.1%}\")
    print(f\"  Profit Factor: {m.get('profit_factor',0):.2f}\")
    print(f\"  Sharpe:        {m.get('sharpe_ratio',0):.2f}\")
    print(f\"  Drawdown:      {m.get('current_drawdown',0):.1%}\")
    print(f\"  Daily PnL:     {m.get('daily_pnl_pct',0):.2%}\")
    print(f\"  Open Positions:{m.get('open_positions',0)}\")
except: print('  (metrici indisponibile)') \
" 2>/dev/null

# ── Ultime 5 loguri ─────────────────────────────────────────
echo -e "\n${CYAN}ULTIME LOGURI (nexus-trader):${RESET}"
docker logs nexus-trader --tail 10 2>/dev/null | grep -v '^$' || echo "  Container oprit"

# ── Utilizare resurse ───────────────────────────────────────
echo -e "\n${CYAN}RESURSE:${RESET}"
docker stats --no-stream --format "  {{.Name}}: CPU {{.CPUPerc}} | RAM {{.MemUsage}}" \
  nexus-trader nexus-redis nexus-nginx 2>/dev/null || true

echo -e "\n${BOLD}═══════════════════════════════════════════════${RESET}\n"
