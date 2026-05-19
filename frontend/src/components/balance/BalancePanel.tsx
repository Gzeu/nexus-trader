'use client';
import React, { useMemo } from 'react';
import type { AccountInfo } from '@/types/trading';
import { buildAllocation, buildSnapshot, fmtPct, fmtUSD, pnlClass } from '@/lib/balance';
import { AllocationDonut } from './AllocationDonut';

interface Props {
  account: AccountInfo | null;
  loading: boolean;
}

function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '7px 0', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)',
        fontWeight: 600, color: color ?? 'var(--text)' }}>{value}</span>
    </div>
  );
}

export function BalancePanel({ account, loading }: Props) {
  const snapshot   = useMemo(() => account ? buildSnapshot(account) : null, [account]);
  const allocation = useMemo(() => snapshot ? buildAllocation(snapshot.assets) : [], [snapshot]);

  if (loading) {
    return (
      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div className="skeleton" style={{ height: 14, width: 120 }} />
        <div style={{ display: 'flex', gap: 20 }}>
          <div className="skeleton" style={{ width: 160, height: 160, borderRadius: '50%' }} />
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[1,2,3,4,5].map(i => <div key={i} className="skeleton" style={{ height: 12 }} />)}
          </div>
        </div>
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-faint)' }}>
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"
          style={{ margin: '0 auto 10px' }}>
          <rect x="2" y="7" width="20" height="14" rx="2"/>
          <path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>
          <line x1="12" y1="12" x2="12" y2="16"/>
          <line x1="10" y1="14" x2="14" y2="14"/>
        </svg>
        <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>No account data</div>
        <div style={{ fontSize: 'var(--text-xs)', marginTop: 4 }}>Check backend connection & API keys</div>
      </div>
    );
  }

  const pnlToday = snapshot.realized_pnl_today;
  const unreal   = snapshot.unrealized_pnl;

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--yellow)" strokeWidth="2">
          <circle cx="12" cy="12" r="10"/>
          <path d="M12 6v6l4 2"/>
        </svg>
        <span style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>Balance Overview</span>
        <span className="badge badge-muted" style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)' }}>
          {new Date(snapshot.fetched_at).toLocaleTimeString()}
        </span>
      </div>

      {/* Donut + Stats */}
      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <AllocationDonut slices={allocation} totalEquity={snapshot.total_equity} size={160} />

        <div style={{ flex: 1, minWidth: 180 }}>
          <Row label="Total Equity"     value={fmtUSD(snapshot.total_equity)} />
          <Row label="Available"        value={fmtUSD(snapshot.available_balance)} />
          <Row label="Used Margin"      value={fmtUSD(snapshot.used_margin)} />
          <Row label="PnL Today"        value={fmtUSD(pnlToday)}   color={pnlClass(pnlToday)} />
          <Row label="Unrealized PnL"   value={fmtUSD(unreal)}     color={pnlClass(unreal)} />
          <Row label="Open Positions"   value={String(snapshot.assets.filter(a => a.asset !== 'USDT').length)} />
        </div>
      </div>

      {/* Legend */}
      {allocation.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 14px', paddingTop: 4,
          borderTop: '1px solid var(--border)' }}>
          {allocation.map(s => (
            <div key={s.asset} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: s.color, flexShrink: 0 }} />
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{s.asset}</span>
              <span style={{ fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', color: 'var(--text-faint)' }}>
                {s.pct.toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
