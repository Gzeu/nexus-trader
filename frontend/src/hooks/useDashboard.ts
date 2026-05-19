/** ─── Nexus Trader — Dashboard data hook ───────────────────────────────── */
'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { useWebSocket } from './useWebSocket';
import type {
  AccountInfo, HealthStatus, Position,
  RiskMetrics, StrategySignal, WSEvent,
} from '@/types/trading';

export interface DashboardState {
  health:      HealthStatus | null;
  account:     AccountInfo  | null;
  metrics:     RiskMetrics  | null;
  positions:   Position[];
  signals:     StrategySignal[];
  loading:     boolean;
  lastUpdated: Date | null;
  wsStatus:    import('./useWebSocket').WsStatus;
  refresh:     () => void;
  emergencyStop: () => Promise<void>;
  resumeTrading: () => Promise<void>;
  cancelAll:   () => Promise<void>;
  closeAll:    () => Promise<void>;
}

export function useDashboard(): DashboardState {
  const [health,    setHealth]    = useState<HealthStatus | null>(null);
  const [account,   setAccount]   = useState<AccountInfo  | null>(null);
  const [metrics,   setMetrics]   = useState<RiskMetrics  | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [signals,   setSignals]   = useState<StrategySignal[]>([]);
  const [loading,   setLoading]   = useState(true);
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

  const onWsEvent = useCallback((e: WSEvent) => {
    if (e.event === 'position_opened' || e.event === 'position_closed' ||
        e.event === 'order_filled'   || e.event === 'tp_hit'          ||
        e.event === 'signal_created' || e.event === 'risk_event') {
      void fetchAll();
    }
  }, [fetchAll]);

  const { status: wsStatus } = useWebSocket({ onEvent: onWsEvent });

  useEffect(() => {
    void fetchAll();
    pollRef.current = setInterval(fetchAll, 15_000);
    return () => { pollRef.current && clearInterval(pollRef.current); };
  }, [fetchAll]);

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
