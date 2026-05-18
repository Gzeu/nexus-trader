import useSWR from 'swr'
import { apiFetch } from '@/lib/config'

export interface HealthData {
  status: 'ok' | 'degraded' | 'error'
  reconciled: boolean
  dry_run: boolean
  testnet: boolean
  market_mode: string
  equity: number
  uptime_seconds: number
  open_positions: number
  daily_pnl: number
  paused: boolean
}

export function useHealth() {
  const { data, error, isLoading, mutate } = useSWR<HealthData>(
    '/health',
    () => apiFetch<HealthData>('/health'),
    { refreshInterval: 5_000, revalidateOnFocus: false }
  )
  return {
    health:    data,
    error,
    isLoading,
    refresh:   mutate,
    connected: !error && data?.status === 'ok',
  }
}
