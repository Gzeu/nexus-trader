/**
 * api.ts — Single typed API client for Nexus Trader.
 *
 * FIX #6: All requests now go through apiFetch() from config.ts.
 *   - Single base URL: NEXT_PUBLIC_API_BASE (replaces NEXT_PUBLIC_API_URL)
 *   - X-API-Key header sent on every request automatically
 *   - wsUrl() reads from config.wsUrl
 *
 * .env.local required vars:
 *   NEXT_PUBLIC_API_BASE=http://localhost:8000/api/v1
 *   NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
 *   NEXT_PUBLIC_API_KEY=   # leave empty if backend auth is disabled
 */
import { apiFetch, config } from './config';
import type {
  AccountInfo, HealthStatus, Order,
  Position, RiskMetrics, StrategySignal,
} from '@/types/trading';

export const api = {
  health:    () => apiFetch<HealthStatus>('/health'),
  account:   () => apiFetch<AccountInfo>('/account'),
  metrics:   () => apiFetch<RiskMetrics>('/metrics'),
  positions: () => apiFetch<Position[]>('/positions'),
  signals:   (limit = 20) => apiFetch<StrategySignal[]>(`/signals?limit=${limit}`),
  orders:    () => apiFetch<Order[]>('/orders'),

  placeOrder:    (body: unknown) =>
    apiFetch<Order>('/place_order', { method: 'POST', body: JSON.stringify(body) }),
  emergencyStop: () =>
    apiFetch<{ ok: boolean }>('/emergency_stop', { method: 'POST' }),
  resumeTrading: () =>
    apiFetch<{ ok: boolean }>('/resume_trading', { method: 'POST' }),
  cancelAll: () =>
    apiFetch<{ ok: boolean }>('/cancel_all', { method: 'POST' }),
  closeAll:  () =>
    apiFetch<{ ok: boolean }>('/close_all', { method: 'POST' }),
};

/** WS URL from unified config */
export function wsUrl(): string {
  return config.wsUrl;
}
