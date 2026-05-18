import useSWR from 'swr'
import { apiFetch } from '@/lib/config'

export interface Position {
  symbol: string
  side: 'LONG' | 'SHORT'
  quantity: number
  entry_price: number
  current_price: number
  unrealized_pnl: number
  realized_pnl: number
  stop_loss: number
  take_profit_1: number
  take_profit_2: number
  opened_at: string
  market_mode: 'SPOT' | 'FUTURES'
  leverage: number
}

export function usePositions() {
  const { data, error, isLoading, mutate } = useSWR<Position[]>(
    '/positions',
    () => apiFetch<Position[]>('/positions'),
    { refreshInterval: 2_000, revalidateOnFocus: false }
  )
  return {
    positions: data ?? [],
    error,
    isLoading,
    refresh: mutate,
  }
}
