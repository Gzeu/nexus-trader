/** ─── SignalsFeed — live signals list ───────────────────────────────────── */
'use client';
import React from 'react';
import type { StrategySignal } from '@/types/trading';

interface Props {
  signals: StrategySignal[];
  loading: boolean;
}

const ACTION_BADGE: Record<string, string> = {
  BUY:     'badge-green',
  SELL:    'badge-red',
  HOLD:    'badge-muted',
  CLOSE:   'badge-yellow',
  REVERSE: 'badge-blue',
};

function ConfidenceBar({ value }: { value: number }) {
  const pct = value * 100;
  const color = value >= 0.7 ? 'var(--green)' : value >= 0.5 ? 'var(--yellow)' : 'var(--red)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width: 60, height: 4, background: 'var(--surface-3)', borderRadius: 99, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 99, transition: 'width 300ms ease' }} />
      </div>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color }}>
        {pct.toFixed(0)}%
      </span>
    </div>
  );
}

export function SignalsFeed({ signals, loading }: Props) {
  if (loading) {
    return (
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)' }}>
          <div className="skeleton" style={{ height: 14, width: 100 }} />
        </div>
        {[1,2,3,4].map(i => (
          <div key={i} style={{ padding: '12px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', gap: 12, alignItems: 'center' }}>
            <div className="skeleton" style={{ height: 10, width: 70 }} />
            <div className="skeleton" style={{ height: 18, width: 40, borderRadius: 99 }} />
            <div className="skeleton" style={{ height: 10, width: 100 }} />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '14px 20px', borderBottom: '1px solid var(--border)',
      }}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2">
          <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/>
        </svg>
        <span style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>Strategy Signals</span>
        {signals.length > 0 && <span className="badge badge-green">{signals.length}</span>}
      </div>

      {signals.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '32px 20px', color: 'var(--text-faint)' }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"
            style={{ margin: '0 auto 10px' }}>
            <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/>
          </svg>
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>No signals yet</div>
        </div>
      ) : (
        <div style={{ maxHeight: 380, overflowY: 'auto' }}>
          {signals.map((s, i) => (
            <div
              key={s.id}
              className="animate-fade-in"
              style={{
                padding: '12px 20px',
                borderBottom: i < signals.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
                display: 'grid',
                gridTemplateColumns: '90px 60px 1fr 80px 80px',
                gap: 12, alignItems: 'center',
                animationDelay: `${i * 30}ms`,
              }}
            >
              <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)' }}>
                {s.symbol}
              </span>
              <span className={`badge ${ACTION_BADGE[s.action] ?? 'badge-muted'}`}>
                {s.action}
              </span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {s.reason}
                </div>
                {s.rr_ratio && (
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)' }}>
                    RR: <span style={{ color: s.rr_ratio >= 1.5 ? 'var(--green)' : 'var(--yellow)' }}>{s.rr_ratio.toFixed(2)}</span>
                    {' · '}{s.timeframe}
                  </div>
                )}
              </div>
              <ConfidenceBar value={s.confidence} />
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)', fontFamily: 'var(--font-mono)', textAlign: 'right' }}>
                {new Date(s.created_at).toLocaleTimeString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
