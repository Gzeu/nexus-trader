#!/usr/bin/env bash
if [ -f /tmp/nexus_pids ]; then
  read -r BACKEND_PID FRONTEND_PID < /tmp/nexus_pids
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  rm /tmp/nexus_pids
  echo "[✓] Nexus Trader stopped"
else
  pkill -f 'uvicorn backend.main' 2>/dev/null || true
  pkill -f 'next dev'             2>/dev/null || true
  echo "[✓] Processes killed"
fi
