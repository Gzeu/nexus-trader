#!/usr/bin/env bash
# ============================================================
# Nexus Trader — Production Deploy Script
# Usage: ./scripts/deploy.sh [--skip-backtest] [--force]
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${BLUE}[$(date '+%H:%M:%S')]${RESET} $*"; }
ok()   { echo -e "${GREEN}✅ $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠️  $*${RESET}"; }
fail() { echo -e "${RED}❌ $*${RESET}"; exit 1; }

SKIP_BACKTEST=false
FORCE=false
for arg in "$@"; do
  [[ "$arg" == "--skip-backtest" ]] && SKIP_BACKTEST=true
  [[ "$arg" == "--force" ]]         && FORCE=true
done

echo -e "${BOLD}\n🚀 Nexus Trader — Production Deploy\n${RESET}"

# ── 1. Verificări prerequisite ─────────────────────────────
log "Verificare prerequisite..."
command -v docker    >/dev/null || fail "Docker nu e instalat"
command -v docker    compose version >/dev/null 2>&1 || \
  command -v docker-compose >/dev/null 2>&1 || fail "Docker Compose nu e instalat"
command -v python3   >/dev/null || fail "Python3 nu e instalat"
ok "Prerequisite OK"

# ── 2. Verificare .env.prod ─────────────────────────────────
log "Verificare .env.prod..."
[[ -f .env.prod ]] || fail ".env.prod lipsește! Copiază .env.prod.example și completează."

# Verifică că nu mai sunt valori placeholder
if grep -qE '(CHANGE_THIS|YOUR_|HERE|REAL_KEY_HERE)' .env.prod && [[ "$FORCE" != "true" ]]; then
  fail ".env.prod conține valori placeholder necompletate. Folosește --force pentru a continua oricum."
fi

# Verifică DRY_RUN
DRY_RUN=$(grep '^DRY_RUN=' .env.prod | cut -d= -f2 | tr -d ' ')
if [[ "$DRY_RUN" == "true" ]]; then
  warn "DRY_RUN=true — sistemul NU va plasa ordine reale"
else
  echo -e "${RED}${BOLD}"
  echo "  ╔══════════════════════════════════════════════╗"
  echo "  ║  ⚠️  DRY_RUN=false — ORDINE REALE ACTIVE!   ║"
  echo "  ╚══════════════════════════════════════════════╝"
  echo -e "${RESET}"
  read -p "  Continui deploy pe LIVE? [yes/NO]: " confirm
  [[ "$confirm" == "yes" ]] || fail "Deploy anulat de utilizator."
fi
ok ".env.prod OK"

# ── 3. Backtest pre-deploy ──────────────────────────────────
if [[ "$SKIP_BACKTEST" == "false" ]]; then
  log "Rulare backtest pre-deploy (30 zile rapid)..."
  python3 -m venv .venv 2>/dev/null || true
  source .venv/bin/activate
  pip install -q -r requirements.txt

  python -m backtesting.backtest_engine \
    --symbol BTCUSDT --tf 15m --days 30 --no-testnet --no-futures \
    --output-json /tmp/backtest_check.json 2>&1 | tail -5

  # Citește rezultatele
  PF=$(python3 -c "import json; d=json.load(open('/tmp/backtest_check.json')); print(d.get('profit_factor',0))" 2>/dev/null || echo 0)
  if python3 -c "exit(0 if float('$PF') >= 1.1 else 1)" 2>/dev/null; then
    ok "Backtest OK — profit factor: $PF"
  else
    warn "Profit factor $PF < 1.1 — sistem potențial ne-profitabil"
    read -p "  Continui oricum? [yes/NO]: " confirm
    [[ "$confirm" == "yes" ]] || fail "Deploy anulat — backtest slab."
  fi
else
  warn "--skip-backtest activ — backtest omis"
fi

# ── 4. Verificare SSL certs ─────────────────────────────────
log "Verificare SSL..."
if [[ ! -f nginx/ssl/fullchain.pem ]] || [[ ! -f nginx/ssl/privkey.pem ]]; then
  warn "Certificatele SSL lipsesc din nginx/ssl/. Generez self-signed pentru test..."
  mkdir -p nginx/ssl
  openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout nginx/ssl/privkey.pem \
    -out nginx/ssl/fullchain.pem \
    -subj "/C=RO/O=NexusTrader/CN=localhost" 2>/dev/null
  warn "Self-signed cert generat. Folosește Let's Encrypt pentru producție reală."
else
  ok "SSL certs găsite"
fi

# ── 5. Build și start containere ────────────────────────────
log "Build imagini Docker..."
docker compose -f docker-compose.prod.yml build --no-cache
ok "Build complet"

log "Stop containere vechi (dacă există)..."
docker compose -f docker-compose.prod.yml down --remove-orphans 2>/dev/null || true

log "Start containere producție..."
docker compose -f docker-compose.prod.yml up -d

# ── 6. Health check post-deploy ─────────────────────────────
log "Aștept pornirea serviciilor (30s)..."
sleep 30

for i in {1..10}; do
  STATUS=$(curl -sf http://localhost/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "down")
  if [[ "$STATUS" == "ok" ]]; then
    ok "API health check: OK"
    break
  fi
  [[ $i -eq 10 ]] && fail "API nu a pornit corect după 10 retry-uri. Verifică: docker compose -f docker-compose.prod.yml logs nexus-trader"
  log "Retry $i/10 — aștept 10s..."
  sleep 10
done

# ── 7. Verificare reconciliere ──────────────────────────────
log "Verificare reconciliere Binance..."
RECON=$(curl -sf http://localhost/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('reconciled','false'))" 2>/dev/null || echo "false")
if [[ "$RECON" == "true" ]]; then
  ok "Reconciliere completă — trading activat"
else
  warn "Reconciliere în curs sau eșuată — trading BLOCAT până la completare"
fi

# ── 8. Summary ──────────────────────────────────────────────
echo -e "\n${BOLD}${GREEN}═══════════════════════════════════════════${RESET}"
echo -e "${BOLD}  ✅ Deploy complet!${RESET}"
echo -e "${BOLD}═══════════════════════════════════════════${RESET}"
echo ""
echo -e "  API:      ${BLUE}https://localhost/api/v1/health${RESET}"
echo -e "  Grafana:  ${BLUE}https://localhost/grafana${RESET}"
echo -e "  Logs:     docker compose -f docker-compose.prod.yml logs -f"
echo -e "  Stop:     docker compose -f docker-compose.prod.yml down"
echo ""
[[ "$DRY_RUN" == "true" ]] && echo -e "${YELLOW}  ⚠️  DRY_RUN=true — Activează DRY_RUN=false după validare 48h${RESET}\n"
