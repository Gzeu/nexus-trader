/**
 * api.ts — typed fetch wrapper for Nexus Trader backend
 * All methods are async and throw on non-2xx responses.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  // ── Health & Status ──────────────────────────────────────────────────────
  health:          ()  => request<import('@/types').HealthResponse>('/health'),
  metrics:         ()  => request<import('@/types').RiskMetrics>('/metrics'),
  account:         ()  => request<import('@/types').AccountInfo>('/account'),

  // ── Signals ───────────────────────────────────────────────────────────────
  signals:         (limit = 50) => request<import('@/types').StrategySignal[]>(`/signals?limit=${limit}`),

  // ── Positions & Orders ────────────────────────────────────────────────────
  positions:       ()  => request<import('@/types').Position[]>('/positions'),
  orders:          ()  => request<import('@/types').Order[]>('/orders'),

  // ── Safety Controls ───────────────────────────────────────────────────────
  emergencyStop:   ()  => request<{ ok: boolean }>('/emergency_stop',  { method: 'POST' }),
  resumeTrading:   ()  => request<{ ok: boolean }>('/resume_trading',  { method: 'POST' }),
  cancelAll:       ()  => request<{ ok: boolean }>('/cancel_all',      { method: 'POST' }),
  closeAll:        ()  => request<{ ok: boolean }>('/close_all',       { method: 'POST' }),

  // ── Manual Order ──────────────────────────────────────────────────────────
  placeOrder: (body: {
    symbol: string
    side: 'BUY' | 'SELL'
    quantity: number
    order_type?: string
    price?: number
    stop_loss?: number
    take_profit?: number
  }) => request<import('@/types').Order>('/place_order', { method: 'POST', body: JSON.stringify(body) }),
}
