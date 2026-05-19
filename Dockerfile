# ─────────────────────────────────────────────
# Stage 1: builder
# ─────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# System deps for numpy / aiosqlite
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────
# Stage 2: runtime
# ─────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy source
COPY backend/ ./backend/
COPY broker_adapter/ ./broker_adapter/

# Journal data volume
VOLUME ["/app/journal_data"]

# Env defaults (override via docker-compose or .env)
ENV DRY_RUN=true \
    TESTNET=true \
    LOG_LEVEL=INFO \
    PORT=8000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
