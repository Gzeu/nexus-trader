#!/usr/bin/env bash
# =============================================================================
# Nexus Trader — Ubuntu Setup Script
# Tested on Ubuntu 22.04 LTS / 24.04 LTS
# Run: chmod +x scripts/setup_ubuntu.sh && ./scripts/setup_ubuntu.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }
step() { echo -e "\n${CYAN}━━━ $1 ━━━${NC}"; }

step "System packages"
sudo apt-get update -qq
sudo apt-get install -y \
  curl wget git build-essential \
  python3 python3-pip python3-venv python3-dev \
  libssl-dev libffi-dev \
  redis-server \
  sqlite3 \
  jq httpie
log "System packages installed"

step "Python version check"
PY=$(python3 --version 2>&1)
log "$PY"
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
  log "Python >= 3.11 OK"
else
  warn "Python < 3.11 detected. Installing 3.12 via deadsnakes PPA..."
  sudo add-apt-repository ppa:deadsnakes/ppa -y
  sudo apt-get update -qq
  sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
  sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1
  log "Python 3.12 installed"
fi

step "Node.js (v20 LTS) for frontend"
if ! command -v node &>/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
  log "Node.js $(node --version) installed"
else
  log "Node.js already present: $(node --version)"
fi

step "Python virtual environment"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  log ".venv created"
fi
source .venv/bin/activate
pip install --upgrade pip wheel setuptools -q
log "venv activated"

step "Backend Python dependencies"
pip install -r requirements.txt -q
log "Backend deps installed"

step "Backtesting dependencies"
pip install -r backtesting/requirements_backtest.txt -q
log "Backtesting deps installed"

step "Frontend Node dependencies"
cd frontend && npm install --silent && cd ..
log "Frontend deps installed"

step ".env file"
if [ ! -f ".env" ]; then
  cp .env.example .env
  warn ".env created from .env.example — edit it with your keys!"
else
  log ".env already exists"
fi

if [ ! -f "frontend/.env.local" ]; then
  cat > frontend/.env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
EOF
  log "frontend/.env.local created"
fi

step "Redis"
if systemctl is-active --quiet redis-server; then
  log "Redis already running"
else
  sudo systemctl start redis-server
  sudo systemctl enable redis-server
  log "Redis started"
fi

step "Validate .env DRY_RUN / TESTNET"
if grep -q 'DRY_RUN=true' .env && grep -q 'TESTNET=true' .env; then
  log "DRY_RUN=true and TESTNET=true — safe for local testing"
else
  warn "Make sure DRY_RUN=true and TESTNET=true in .env before testing!"
fi

echo -e "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Nexus Trader setup complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e ""
echo -e "  Next steps:"
echo -e "  1. Edit ${YELLOW}.env${NC} — add BINANCE_API_KEY + BINANCE_API_SECRET"
echo -e "  2. ${CYAN}source .venv/bin/activate${NC}"
echo -e "  3. Run tests:  ${CYAN}./scripts/test.sh${NC}"
echo -e "  4. Start all:  ${CYAN}./scripts/start_dev.sh${NC}"
echo -e ""
