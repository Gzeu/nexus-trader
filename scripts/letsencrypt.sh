#!/usr/bin/env bash
# ============================================================
# Nexus Trader — Obținere certificat Let's Encrypt
# Usage: sudo bash scripts/letsencrypt.sh your-domain.com your@email.com
# ============================================================
set -euo pipefail

DOMAIN=${1:-""}
EMAIL=${2:-""}

[[ -z "$DOMAIN" ]] && { echo "Usage: $0 <domain> <email>"; exit 1; }
[[ -z "$EMAIL" ]]  && { echo "Usage: $0 <domain> <email>"; exit 1; }

# Instalare certbot
apt-get install -y certbot

# Oprire temporară nginx
docker compose -f docker-compose.prod.yml stop nginx 2>/dev/null || true

# Obținere cert
certbot certonly --standalone \
  -d "$DOMAIN" \
  --email "$EMAIL" \
  --agree-tos \
  --no-eff-email

# Copiază certurile în nginx/ssl/
mkdir -p nginx/ssl
cp /etc/letsencrypt/live/"$DOMAIN"/fullchain.pem nginx/ssl/
cp /etc/letsencrypt/live/"$DOMAIN"/privkey.pem nginx/ssl/
chmod 600 nginx/ssl/privkey.pem

# Actualizare nginx.conf cu domeniu
sed -i "s/YOUR_DOMAIN_OR_IP/$DOMAIN/g" nginx/conf.d/nexus.conf

# Restart nginx
docker compose -f docker-compose.prod.yml start nginx 2>/dev/null || true

# Auto-renewal cron
echo "0 12 * * * root certbot renew --quiet --post-hook 'cp /etc/letsencrypt/live/$DOMAIN/*.pem /opt/nexus-trader/nginx/ssl/ && docker compose -f /opt/nexus-trader/docker-compose.prod.yml exec nginx nginx -s reload'" \
  > /etc/cron.d/certbot-nexus

echo "✅ Certificat Let's Encrypt instalat pentru $DOMAIN"
echo "   Auto-renewal configurat la 12:00 zilnic"
