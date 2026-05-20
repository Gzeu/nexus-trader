/**
 * useDashboard.ts — Dashboard data hook.
 *
 * FIX #7: Uses useWebSocket (single WS connection, exponential backoff).
 * FIX #8:
 *   - debounce(fetchAll, 500ms) — WS event bursts collapse into one fetch.
 *   - Polling (15s) only active when WS is NOT connected (fallback mode).
 *     When WS reconnects, polling is cleared automatically.
 */
'use client';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { useWebSocket } from './useWebSocket';
import type {
  AccountInfo, HealthStatus, Position,
  RiskMetrics, StrategySignal, WSEvent,
} from '@/types/trading';

export interface DashboardState {
  health:        HealthStatus | null;
  account:       AccountInfo  | null;
  metrics:       RiskMetrics  | null;
  positions:     Position[];
  signals:       StrategySignal[];
  loading:       boolean;
  lastUpdated:   Date | null;
  wsStatus:      import('./useWebSocket').WsStatus;
  refresh:       () => void;
  emergencyStop: () => Promise<void>;
  resumeTrading: () => Promise<void>;
  cancelAll:     () => Promise<void>;
  closeAll:      () => Promise<void>;
}

/** Minimal debounce — no lodash dependency needed */
function debounce<T extends (...args: unknown[]) => unknown>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout> | null = null;
  return ((...args: unknown[]) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => { timer = null; fn(...args); }, ms);
  }) as T;
}

export function useDashboard(): DashboardState {
  const [health,      setHealth]      = useState<HealthStatus | null>(null);
  const [account,     setAccount]     = useState<AccountInfo  | null>(null);
  const [metrics,     setMetrics]     = useState<RiskMetrics  | null>(null);
  const [positions,   setPositions]   = useState<Position[]>([]);
  const [signals,     setSignals]     = useState<StrategySignal[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const [h, a, m, p, s] = await Promise.allSettled([
        api.health(), api.account(), api.metrics(),
        api.positions(), api.signals(30),
      ]);
      if (h.status === 'fulfilled') setHealth(h.value);
      if (a.status === 'fulfilled') setAccount(a.value);
      if (m.status === 'fulfilled') setMetrics(m.value);
      if (p.status === 'fulfilled') setPositions(p.value);
      if (s.status === 'fulfilled') setSignals(s.value);
      setLastUpdated(new Date());
    } finally {
      setLoading(false);
    }
  }, []);

  // FIX #8 — debounced fetch for WS events: 500ms window collapses bursts
  // useMemo keeps the debounced reference stable across renders
  const debouncedFetch = useMemo(
    () => debounce(fetchAll as (...args: unknown[]) => unknown, 500),
    [fetchAll],
  );

  const onWsEvent = useCallback((e: WSEvent) => {
    const relevant = new Set([
      'position_opened', 'position_closed',
      'order_filled',    'tp_hit',
      'signal_created',  'risk_event',
    ]);
    if (relevant.has(e.event)) void debouncedFetch();
  }, [debouncedFetch]);

  const { status: wsStatus } = useWebSocket({ onEvent: onWsEvent });

  // Initial fetch on mount
  useEffect(() => { void fetchAll(); }, [fetchAll]);

  // FIX #8 — polling only when WS is NOT connected
  // WS connected → clear poll; WS down → start 15s fallback poll
  useEffect(() => {
    if (wsStatus === 'connected') {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    if (!pollRef.current) {
      pollRef.current = setInterval(() => void fetchAll(), 15_000);
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [wsStatus, fetchAll]);

  const emergencyStop = async () => { await api.emergencyStop(); await fetchAll(); };
  const resumeTrading = async () => { await api.resumeTrading(); await fetchAll(); };
  const cancelAll     = async () => { await api.cancelAll();     await fetchAll(); };
  const closeAll      = async () => { await api.closeAll();      await fetchAll(); };

  return {
    health, account, metrics, positions, signals,
    loading, lastUpdated, wsStatus,
    refresh: fetchAll,
    emergencyStop, resumeTrading, cancelAll, closeAll,
  };
}
