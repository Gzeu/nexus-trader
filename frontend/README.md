# Nexus Trader — Frontend

Next.js 14 trading terminal with TradingView Charting Library integration.

## Stack

- **Next.js 14** (App Router)
- **TradingView Charting Library** (self-hosted, requires license)
- **Broker Adapter** — `broker_adapter/tradingview_broker.ts` wired to FastAPI backend
- **SWR** — data fetching with auto-refresh
- **Tailwind CSS** — Nexus dark palette
- **Lucide React** — icons

## Quick Start

```bash
cd frontend
npm install
cp .env.local.example .env.local
# Edit .env.local — set your API URL + API key

# Place TradingView library in:
# frontend/public/charting_library/

npm run dev
# Open http://localhost:3000
```

## TradingView Library Setup

1. Request access at https://www.tradingview.com/HTML5-stock-forex-bitcoin-charting-library/
2. Download the library
3. Copy the `charting_library/` folder to `frontend/public/charting_library/`
4. Required: `charting_library.js`, `bundles/` directory

## Architecture

```
src/
├── app/
│   ├── layout.tsx          ← Root layout + fonts
│   ├── page.tsx            ← Main terminal page
│   └── globals.css         ← Tailwind + custom vars
├── components/
│   ├── chart/
│   │   ├── TradingChart.tsx ← TradingView widget + Binance datafeed + broker wiring
│   │   └── ChartSkeleton.tsx
│   ├── layout/
│   │   ├── StatusBar.tsx    ← Connection status + equity + emergency stop
│   │   ├── Header.tsx       ← Symbol selector + timeframe picker
│   │   ├── Sidebar.tsx      ← Signals feed + metrics panel
│   │   └── BottomPanel.tsx  ← Positions table + cancel/close all
│   ├── signals/
│   │   └── SignalCard.tsx   ← Individual signal with confidence bar
│   ├── metrics/
│   │   └── MetricsPanel.tsx ← Full stats panel
│   └── positions/
│       └── PositionRow.tsx  ← Position row with close button
├── hooks/
│   ├── useHealth.ts         ← /health polling (5s)
│   ├── usePositions.ts      ← /positions polling (2s)
│   ├── useMetrics.ts        ← /metrics polling (5s)
│   ├── useSignals.ts        ← /signals polling (3s)
│   └── useWS.ts             ← WebSocket event subscription
└── lib/
    ├── config.ts            ← Env vars + typed apiFetch()
    └── websocket.ts         ← Singleton WS client with auto-reconnect
```

## WebSocket Events

The frontend listens for these events from the backend:

| Event | Handler |
|---|---|
| `signal_created` | Refresh signals list + draw arrow on chart |
| `signal_rejected` | Refresh signals list |
| `order_filled` | Refresh signals + positions |
| `position_opened` | Refresh positions |
| `position_updated` | Refresh positions |
| `position_closed` | Refresh positions |
| `tp1_hit` / `tp2_hit` / `sl_hit` | Show notification |
| `emergency_stop` | Show notification |
| `connected` / `disconnected` | Update WS status indicator |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8000/api/v1` | FastAPI backend URL |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000/ws` | WebSocket URL |
| `NEXT_PUBLIC_API_KEY` | — | API secret key (matches `API_SECRET_KEY` in backend `.env`) |
| `NEXT_PUBLIC_MARKET_MODE` | `SPOT` | `SPOT` or `FUTURES` |
