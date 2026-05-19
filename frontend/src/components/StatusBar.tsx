/** ─── StatusBar — top status strip ─────────────────────────────────────── */
'use client';
import React from 'react';
import type { WsStatus } from '@/hooks/useWebSocket';
import type { HealthStatus } from '@/types/trading';

interface Props {
  health:     HealthStatus | null;
  wsStatus:   WsStatus;
  lastUpdated: Date | null;
  onRefresh:  () => void;
}

const WS_LABEL: Record<WsStatus, string> = {
  connecting:   'Connecting…',
  connected:    'Live',
  disconnected: 'Disconnected',
  error:        'WS Error',
};
const WS_DOT: Record<WsStatus, string> = {
  connecting:   'dot dot-yellow',
  connected:    'dot dot-green',
  disconnected: 'dot dot-muted',
  error:        'dot dot-red',
};

export function StatusBar({ health, wsStatus, lastUpdated, onRefresh }: Props) {
  const fmt = (d: Date) =>
    d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  return (
    <header style={{
      display: 'flex', alignItems: 'center', gap: '12px',
      padding: '10px 20px',
      background: 'var(--surface)',
      borderBottom: '1px solid var(--border)',
      fontSize: 'var(--text-xs)',
      flexWrap: 'wrap',
    }}>
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginRight: 8 }}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
          <path d="M3 17l5-5 4 4 9-9" stroke="var(--green)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
          <circle cx="12" cy="12" r="10" stroke="var(--border-strong)" strokeWidth="1.2"/>
        </svg>
        <span style={{ fontWeight: 700, fontSize: 'var(--text-sm)', color: 'var(--text)', letterSpacing: '-0.02em' }}>
          Nexus<span style={{ color: 'var(--green)' }}>Trader</span>
        </span>
      </div>

      {/* Divider */}
      <div style={{ width: 1, height: 16, background: 'var(--border)', flexShrink: 0 }} />

      {/* WS status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <span className={WS_DOT[wsStatus]} />
        <span style={{ color: wsStatus === 'connected' ? 'var(--green)' : 'var(--text-muted)' }}>
          {WS_LABEL[wsStatus]}
        </span>
      </div>

      {health && (
        <>
          <div style={{ width: 1, height: 16, background: 'var(--border)', flexShrink: 0 }} />
          <span className={`badge ${health.is_reconciled ? 'badge-green' : 'badge-yellow'}`}>
            {health.is_reconciled ? '✓ Reconciled' : '⚠ Not reconciled'}
          </span>
          {health.dry_run && <span className="badge badge-yellow">DRY RUN</span>}
          {health.testnet && <span className="badge badge-blue">TESTNET</span>}
          {health.is_paused && <span className="badge badge-red">⏸ PAUSED</span>}
          <span className="badge badge-muted" style={{ textTransform: 'uppercase' }}>
            {health.market_mode}
          </span>
        </>
      )}

      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
        {lastUpdated && (
          <span style={{ color: 'var(--text-faint)', fontFamily: 'var(--font-mono)' }}>
            {fmt(lastUpdated)}
          </span>
        )}
        <button
          className="btn btn-ghost btn-sm"
          onClick={onRefresh}
          title="Refresh data"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <path d="M1 4v6h6M23 20v-6h-6"/>
            <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/>
          </svg>
          Refresh
        </button>
      </div>
    </header>
  );
}
