import useSWR from 'swr'
import { apiFetch } from '@/lib/config'

export interface Metrics {
  total_trades: number
  win_rate: number
  profit_factor: number
  sharpe_ratio: number
  max_drawdown: number
  total_pnl: number
  daily_pnl: number
  expectancy: number
  consecutive_losses: number
  open_positions: number
  equity: number
  peak_equity: number
  realized_pnl: number
  unrealized_pnl: number
}

export function useMetrics() {
  const { data, error, isLoading, mutate } = useSWR<Metrics>(
    '/analytics',
    () => apiFetch<Metrics>('/analytics'),
    { refreshInterval: 5_000, revalidateOnFocus: false }
  )
  return { metrics: data, error, isLoading, refresh: mutate }
}
