/** ─── Nexus Trader — WebSocket hook with auto-reconnect ─────────────────── */
'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { WSEvent } from '@/types/trading';
import { wsUrl } from '@/lib/api';

export type WsStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

interface Options {
  onEvent?: (e: WSEvent) => void;
  maxRetries?: number;
  baseDelay?: number;
}

export function useWebSocket({ onEvent, maxRetries = 10, baseDelay = 1000 }: Options = {}) {
  const [status, setStatus] = useState<WsStatus>('disconnected');
  const wsRef       = useRef<WebSocket | null>(null);
  const retries     = useRef(0);
  const retryTimer  = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onEventRef  = useRef(onEvent);
  useEffect(() => { onEventRef.current = onEvent; }, [onEvent]);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    setStatus('connecting');
    const url = wsUrl();
    const ws  = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus('connected');
      retries.current = 0;
    };

    ws.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data as string) as WSEvent;
        onEventRef.current?.(event);
      } catch { /* ignore malformed */ }
    };

    ws.onerror = () => setStatus('error');

    ws.onclose = () => {
      setStatus('disconnected');
      if (retries.current < maxRetries) {
        const delay = Math.min(baseDelay * 2 ** retries.current, 30_000);
        retries.current++;
        retryTimer.current = setTimeout(connect, delay);
      }
    };
  }, [maxRetries, baseDelay]);

  useEffect(() => {
    connect();
    return () => {
      retryTimer.current && clearTimeout(retryTimer.current);
      wsRef.current?.close(1000, 'unmount');
    };
  }, [connect]);

  return { status };
}
