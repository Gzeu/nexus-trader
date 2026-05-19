#!/usr/bin/env bash
# =============================================================================
# Start backend + frontend in dev mode (split terminal via tmux or background)
# Usage: ./scripts/start_dev.sh
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'

# Activate venv if not already active
if [ -z "${VIRTUAL_ENV:-}" ]; then
  source .venv/bin/activate
fi

# Safety check
if grep -q 'DRY_RUN=false' .env 2>/dev/null; then
  echo -e "${YELLOW}[!] WARNING: DRY_RUN=false in .env — real orders will be placed!${NC}"
  read -rp "Continue? [y/N] " confirm
  [[ "$confirm" == [yY] ]] || exit 1
fi

echo -e "${CYAN}Starting Nexus Trader (dev mode)...${NC}"

# Check if tmux is available for split panes
if command -v tmux &>/dev/null && [ -z "${TMUX:-}" ]; then
  echo -e "${GREEN}Opening tmux session with 3 panes...${NC}"
  tmux new-session -d -s nexus -x 220 -y 50
  tmux send-keys -t nexus "source .venv/bin/activate && uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000" Enter
  tmux split-window -h -t nexus
  tmux send-keys -t nexus "cd frontend && npm run dev" Enter
  tmux split-window -v -t nexus:0.1
  tmux send-keys -t nexus "echo 'Logs pane — tail -f /tmp/nexus.log'" Enter
  tmux select-pane -t nexus:0.0
  tmux attach-session -t nexus
else
  # Fallback: background processes + log files
  echo -e "${GREEN}Starting backend on :8000 ...${NC}"
  uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 \
    --log-level info > /tmp/nexus_backend.log 2>&1 &
  BACKEND_PID=$!
  echo "  Backend PID: $BACKEND_PID  (logs: /tmp/nexus_backend.log)"

  sleep 2  # Wait for backend to be ready

  echo -e "${GREEN}Starting frontend on :3000 ...${NC}"
  cd frontend && npm run dev > /tmp/nexus_frontend.log 2>&1 &
  FRONTEND_PID=$!
  cd ..
  echo "  Frontend PID: $FRONTEND_PID  (logs: /tmp/nexus_frontend.log)"

  echo -e ""
  echo -e "${GREEN}Both services started.${NC}"
  echo -e "  Backend:  http://localhost:8000"
  echo -e "  Frontend: http://localhost:3000"
  echo -e "  API docs: http://localhost:8000/docs"
  echo -e ""
  echo -e "  Stop all: kill $BACKEND_PID $FRONTEND_PID"
  echo -e "  Or:       ./scripts/stop_dev.sh"

  # Save PIDs for stop script
  echo "$BACKEND_PID $FRONTEND_PID" > /tmp/nexus_pids

  # Follow backend log
  tail -f /tmp/nexus_backend.log
fi
