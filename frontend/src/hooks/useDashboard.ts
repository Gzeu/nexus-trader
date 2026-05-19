'use client'

import { useState, useCallback } from 'react'
import { api } from '@/lib/api'
import { usePolling } from './usePolling'
import { useWebSocket } from './useWebSocket'
import type { AccountInfo, HealthResponse, Position, StrategySignal, RiskMetrics, WSEvent } from '@/types'

export interface DashboardState {
  health:    HealthResponse | null
  account:   AccountInfo   | null
  positions: Position[]
  signals:   StrategySignal[]
  metrics:   RiskMetrics   | null
  loading:   boolean
  error:     string | null
  wsConnected: boolean
}

export function useDashboard() {
  const [state, setState] = useState<DashboardState>({
    health: null, account: null, positions: [], signals: [], metrics: null,
    loading: true, error: null, wsConnected: false,
  })

  const refresh = useCallback(async () => {
    try {
      const [health, account, positions, signals, metrics] = await Promise.all([
        api.health(),
        api.account(),
        api.positions(),
        api.signals(30),
        api.metrics(),
      ])
      setState(s => ({ ...s, health, account, positions, signals, metrics, loading: false, error: null }))
    } catch (e) {
      setState(s => ({ ...s, loading: false, error: (e as Error).message }))
    }
  }, [])

  // Poll every 5 seconds
  usePolling(refresh, 5_000)

  // WebSocket live updates
  const handleWS = useCallback((evt: WSEvent) => {
    if (evt.event === 'position_update' || evt.event === 'order_filled') {
      void api.positions().then(positions => setState(s => ({ ...s, positions })))
    }
    if (evt.event === 'signal_created') {
      const sig = evt.payload as unknown as StrategySignal
      setState(s => ({ ...s, signals: [sig, ...s.signals].slice(0, 50) }))
    }
    if (evt.event === 'metrics_update') {
      setState(s => ({ ...s, metrics: evt.payload as unknown as RiskMetrics }))
    }
  }, [])

  const { connected } = useWebSocket(handleWS)

  // reflect WS connection status
  useState(() => { setState(s => ({ ...s, wsConnected: connected })) })

  return { state, refresh }
}
