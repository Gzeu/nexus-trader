/**
 * config.ts — Central config for frontend.
 * All values come from NEXT_PUBLIC_* env vars.
 */
export const config = {
  apiBase:    process.env.NEXT_PUBLIC_API_BASE    ?? 'http://localhost:8000/api/v1',
  wsUrl:      process.env.NEXT_PUBLIC_WS_URL      ?? 'ws://localhost:8000/ws',
  apiKey:     process.env.NEXT_PUBLIC_API_KEY     ?? '',
  marketMode: (process.env.NEXT_PUBLIC_MARKET_MODE ?? 'SPOT') as 'SPOT' | 'FUTURES',
} as const

/** Typed fetch wrapper with auth header */
export async function apiFetch<T = unknown>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const url = `${config.apiBase}${path}`
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(config.apiKey ? { 'X-API-Key': config.apiKey } : {}),
    ...(init?.headers ?? {}),
  }
  const res = await fetch(url, { ...init, headers })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}
