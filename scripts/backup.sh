#!/usr/bin/env bash
# ============================================================
# Nexus Trader — Daily Backup Script
# Rulat automat de cron la 03:00
# ============================================================
set -euo pipefail

BACKUP_DIR="/opt/nexus-trader/backups"
DATE=$(date +%Y%m%d_%H%M%S)
APP_DIR="/opt/nexus-trader"

mkdir -p "$BACKUP_DIR"

# Backup journal SQLite
if [[ -f "$APP_DIR/journal/trades.db" ]]; then
  cp "$APP_DIR/journal/trades.db" "$BACKUP_DIR/trades_${DATE}.db"
  echo "[$(date)] Backup DB: trades_${DATE}.db"
fi

# Backup CSV-uri
if ls "$APP_DIR/journal/"*.csv &>/dev/null; then
  tar -czf "$BACKUP_DIR/journal_csv_${DATE}.tar.gz" -C "$APP_DIR/journal" *.csv 2>/dev/null || true
  echo "[$(date)] Backup CSV: journal_csv_${DATE}.tar.gz"
fi

# Backup backtest results
if [[ -d "$APP_DIR/backtesting/results" ]]; then
  tar -czf "$BACKUP_DIR/backtest_${DATE}.tar.gz" -C "$APP_DIR/backtesting" results/ 2>/dev/null || true
fi

# Sterge backup-uri mai vechi de 30 zile
find "$BACKUP_DIR" -type f -mtime +30 -delete

# Sumă fișiere backup
echo "[$(date)] Backup complet. Fișiere: $(ls -1 $BACKUP_DIR | wc -l)"
