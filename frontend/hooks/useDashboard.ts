"use client";
/**
 * useDashboard — central data hook.
 * Fetches all backend data in parallel with Promise.allSettled
 * (never fails hard on partial error). Polls every 15s.
 * Instantly refreshes after any WS event or user action.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, BalanceSummary, HealthStatus, JournalPage, Position, RiskMetrics, StrategySignal } from "@/lib/api";
import { useWebSocket, WsStatus } from "@/hooks/useWebSocket";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws";
const POLL_MS = 15_000;

export interface DashboardState {
  health:   HealthStatus | null;
  balance:  BalanceSummary | null;
  metrics:  RiskMetrics | null;
  positions: Position[];
  signals:  StrategySignal[];
  journal:  JournalPage | null;
  journalPage: number;

  loading: boolean;
  lastRefresh: Date | null;
  wsStatus: WsStatus;

  refresh: () => void;
  setJournalPage: (p: number) => void;
  emergencyStop: () => Promise<void>;
  resumeTrading: () => Promise<void>;
  cancelAll: () => Promise<void>;
  closeAll: () => Promise<void>;
  reconcile: () => Promise<void>;
}

export function useDashboard(): DashboardState {
  const [health,    setHealth]    = useState<HealthStatus | null>(null);
  const [balance,   setBalance]   = useState<BalanceSummary | null>(null);
  const [metrics,   setMetrics]   = useState<RiskMetrics | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [signals,   setSignals]   = useState<StrategySignal[]>([]);
  const [journal,   setJournal]   = useState<JournalPage | null>(null);
  const [journalPage, setJournalPage] = useState(1);
  const [loading,   setLoading]   = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAll = useCallback(async (page = journalPage) => {
    setLoading(true);
    const [h, b, m, pos, sig, j] = await Promise.allSettled([
      api.health(),
      api.balance(),
      api.metrics(),
      api.positions(),
      api.signals(),
      api.journal(page),
    ]);
    if (h.status   === "fulfilled") setHealth(h.value);
    if (b.status   === "fulfilled") setBalance(b.value);
    if (m.status   === "fulfilled") setMetrics(m.value);
    if (pos.status === "fulfilled") setPositions(pos.value);
    if (sig.status === "fulfilled") setSignals(sig.value);
    if (j.status   === "fulfilled") setJournal(j.value);
    setLoading(false);
    setLastRefresh(new Date());
  }, [journalPage]);

  // Initial load + poll
  useEffect(() => {
    fetchAll();
    timerRef.current = setInterval(() => fetchAll(), POLL_MS);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [fetchAll]);

  // Journal page change
  const handlePageChange = useCallback((p: number) => {
    setJournalPage(p);
    fetchAll(p);
  }, [fetchAll]);

  // WebSocket live updates
  const { wsStatus } = useWebSocket(WS_URL, () => {
    fetchAll();
  });

  // Actions
  const wrap = (fn: () => Promise<unknown>) => async () => { await fn(); await fetchAll(); };

  return {
    health, balance, metrics, positions, signals, journal, journalPage,
    loading, lastRefresh, wsStatus,
    refresh:       () => fetchAll(),
    setJournalPage: handlePageChange,
    emergencyStop: wrap(api.emergencyStop),
    resumeTrading: wrap(api.resumeTrading),
    cancelAll:     wrap(api.cancelAll),
    closeAll:      wrap(api.closeAll),
    reconcile:     wrap(api.reconcile),
  };
}
