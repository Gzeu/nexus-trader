import useSWR from 'swr'
import { apiFetch } from '@/lib/config'

export interface Signal {
  id: string
  symbol: string
  action: 'BUY' | 'SELL' | 'HOLD' | 'CLOSE' | 'REVERSE'
  confidence: number
  entry_price: number
  stop_loss: number
  take_profit_1: number
  take_profit_2: number
  timeframe: string
  reason: string
  created_at: string
  status: 'PENDING' | 'EXECUTED' | 'REJECTED' | 'EXPIRED'
  veto_reason?: string
}

export function useSignals(limit = 50) {
  const { data, error, isLoading, mutate } = useSWR<{ trades: Signal[]; total: number }>(
    `/signals?limit=${limit}`,
    () => apiFetch(`/signals?limit=${limit}`),
    { refreshInterval: 3_000, revalidateOnFocus: false }
  )
  return {
    signals:    data?.trades ?? [],
    total:      data?.total ?? 0,
    error,
    isLoading,
    refresh:    mutate,
  }
}
