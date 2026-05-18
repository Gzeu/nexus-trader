#!/usr/bin/env bash
# ============================================================
# Nexus Trader — Ubuntu Server Setup (one-time)
# Testată pe Ubuntu 22.04 LTS / 24.04 LTS
# Usage: sudo bash scripts/setup_ubuntu.sh
# ============================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; RESET='\033[0m'
ok()  { echo -e "${GREEN}✅ $*${RESET}"; }
log() { echo -e "${BLUE}▶ $*${RESET}"; }
warn(){ echo -e "${YELLOW}⚠️  $*${RESET}"; }

[[ $EUID -eq 0 ]] || { echo "Rulează cu sudo"; exit 1; }

# ── 1. System update ────────────────────────────────────────
log "Update sistem..."
apt-get update -qq && apt-get upgrade -y -qq
apt-get install -y -qq \
  curl wget git htop nano ufw fail2ban \
  python3.11 python3.11-venv python3.11-dev python3-pip \
  build-essential libssl-dev libffi-dev libpq-dev \
  openssl ca-certificates gnupg lsb-release
ok "Sistem actualizat"

# ── 2. Docker ────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  log "Instalare Docker..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
    tee /etc/apt/sources.list.d/docker.list > /dev/null
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
  ok "Docker instalat"
else
  ok "Docker deja instalat"
fi

# Adaugă user curent la grupul docker
USERNAME=${SUDO_USER:-$(logname 2>/dev/null || echo ubuntu)}
usermod -aG docker "$USERNAME" 2>/dev/null || true

# ── 3. Firewall (UFW) ───────────────────────────────────────
log "Configurare firewall UFW..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp   comment 'HTTP'
ufw allow 443/tcp  comment 'HTTPS'
# Blochează accesul direct la porturi interne din internet
ufw deny 8000/tcp  comment 'API direct — doar prin nginx'
ufw deny 6379/tcp  comment 'Redis direct'
ufw deny 9090/tcp  comment 'Prometheus direct'
ufw deny 3000/tcp  comment 'Grafana direct'
ufw --force enable
ok "Firewall configurat"

# ── 4. Fail2ban ─────────────────────────────────────────────
log "Configurare Fail2ban..."
cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port    = ssh
logpath = %(sshd_log)s

[nginx-http-auth]
enabled = true
EOF
systemctl enable --now fail2ban
ok "Fail2ban configurat"

# ── 5. Swap (important pentru VPS cu RAM mic) ───────────────
if [[ ! -f /swapfile ]]; then
  log "Creare swap 2GB..."
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl vm.swappiness=10
  echo 'vm.swappiness=10' >> /etc/sysctl.conf
  ok "Swap 2GB creat"
else
  ok "Swap deja configurat"
fi

# ── 6. Directoare și permisiuni ─────────────────────────────
log "Creare structură directoare..."
mkdir -p /opt/nexus-trader
chown "$USERNAME:$USERNAME" /opt/nexus-trader

# ── 7. Systemd service pentru auto-restart ──────────────────
log "Creare systemd service..."
APP_DIR="/opt/nexus-trader"
cat > /etc/systemd/system/nexus-trader.service << EOF
[Unit]
Description=Nexus Trader — Automated Trading System
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=$USERNAME
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
TimeoutStartSec=120
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable nexus-trader.service
ok "Systemd service creat și activat la boot"

# ── 8. Logrotate ────────────────────────────────────────────
log "Configurare logrotate..."
cat > /etc/logrotate.d/nexus-trader << 'EOF'
/opt/nexus-trader/journal/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root root
}
EOF
ok "Logrotate configurat"

# ── 9. Cron pentru backup automat ───────────────────────────
log "Configurare backup cron..."
cat > /etc/cron.d/nexus-backup << EOF
# Backup journal zilnic la 03:00
0 3 * * * $USERNAME /opt/nexus-trader/scripts/backup.sh >> /var/log/nexus-backup.log 2>&1
EOF
ok "Backup cron configurat"

echo ""
ok "Setup Ubuntu complet!"
echo ""
echo "  Pași următori:"
echo "  1. Mută repo-ul în /opt/nexus-trader:"
echo "     sudo cp -r . /opt/nexus-trader && cd /opt/nexus-trader"
echo "  2. Copiază și completează .env.prod:"
echo "     cp .env.prod.example .env.prod && nano .env.prod"
echo "  3. Rulează deploy:"
echo "     bash scripts/deploy.sh"
echo ""
warn "Re-login sau: newgrp docker — pentru a folosi docker fără sudo"
