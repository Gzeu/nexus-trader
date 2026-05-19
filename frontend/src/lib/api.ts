/** ─── Nexus Trader — API client (typed fetch wrappers) ─────────────────── */
import type { AccountInfo, HealthStatus, Order, Position, RiskMetrics, StrategySignal } from '@/types/trading';

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const API  = `${BASE}/api/v1`;

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  health:        () => get<HealthStatus>('/health'),
  account:       () => get<AccountInfo>('/account'),
  metrics:       () => get<RiskMetrics>('/metrics'),
  positions:     () => get<Position[]>('/positions'),
  signals:       (limit = 20) => get<StrategySignal[]>(`/signals?limit=${limit}`),
  orders:        () => get<Order[]>('/orders'),

  placeOrder:    (body: unknown) => post<Order>('/place_order', body),
  emergencyStop: () => post<{ ok: boolean }>('/emergency_stop'),
  resumeTrading: () => post<{ ok: boolean }>('/resume_trading'),
  cancelAll:     () => post<{ ok: boolean }>('/cancel_all'),
  closeAll:      () => post<{ ok: boolean }>('/close_all'),
};

export function wsUrl(): string {
  const base = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000';
  return `${base}/api/v1/ws`;
}
