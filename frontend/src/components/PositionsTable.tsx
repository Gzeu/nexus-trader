/** ─── PositionsTable — open positions with inline PnL ──────────────────── */
'use client';
import React, { useState } from 'react';
import type { Position } from '@/types/trading';

interface Props {
  positions: Position[];
  loading:   boolean;
  onClose?:  (id: string) => void;
}

function pnlColor(v: number) {
  return v > 0 ? 'var(--green)' : v < 0 ? 'var(--red)' : 'var(--text-muted)';
}

function fmtUSD(n: number) {
  const abs = Math.abs(n);
  const sign = n >= 0 ? '+' : '-';
  return `${sign}$${abs.toFixed(2)}`;
}

function PnlCell({ value }: { value: number }) {
  return (
    <span style={{ color: pnlColor(value), fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
      {fmtUSD(value)}
    </span>
  );
}

function ProgressBar({ position }: { position: Position }) {
  const range  = Math.abs(position.take_profit_2 - position.entry_price);
  const moved  = Math.abs(position.current_price - position.entry_price);
  const pct    = range > 0 ? Math.min((moved / range) * 100, 100) : 0;
  const isUp   = position.side === 'BUY'
    ? position.current_price >= position.entry_price
    : position.current_price <= position.entry_price;
  return (
    <div style={{ width: 80, height: 5, background: 'var(--surface-3)', borderRadius: 99, overflow: 'hidden' }}>
      <div style={{
        height: '100%', width: `${pct}%`, borderRadius: 99,
        background: isUp ? 'var(--green)' : 'var(--red)',
        transition: 'width 400ms ease',
      }} />
    </div>
  );
}

export function PositionsTable({ positions, loading, onClose }: Props) {
  const [sortBy, setSortBy] = useState<'pnl' | 'symbol' | 'opened'>('opened');

  const sorted = [...positions].sort((a, b) => {
    if (sortBy === 'pnl')    return b.total_pnl - a.total_pnl;
    if (sortBy === 'symbol') return a.symbol.localeCompare(b.symbol);
    return new Date(b.opened_at).getTime() - new Date(a.opened_at).getTime();
  });

  if (loading) {
    return (
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)' }}>
          <div className="skeleton" style={{ height: 14, width: 120 }} />
        </div>
        {[1,2,3].map(i => (
          <div key={i} style={{ display: 'flex', gap: 16, padding: '14px 20px', borderBottom: '1px solid var(--border)' }}>
            {[80,60,70,60,70,60].map((w, j) => (
              <div key={j} className="skeleton" style={{ height: 12, width: w }} />
            ))}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 20px', borderBottom: '1px solid var(--border)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--blue)" strokeWidth="2">
            <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
          </svg>
          <span style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>Open Positions</span>
          {positions.length > 0 && (
            <span className="badge badge-blue">{positions.length}</span>
          )}
        </div>
        {/* Sort */}
        <div style={{ display: 'flex', gap: 6 }}>
          {(['pnl', 'symbol', 'opened'] as const).map(k => (
            <button
              key={k}
              className={`btn btn-ghost btn-sm ${sortBy === k ? '' : ''}`}
              onClick={() => setSortBy(k)}
              style={sortBy === k ? { color: 'var(--blue)', borderColor: 'rgba(78,140,255,0.3)' } : {}}
            >
              {k}
            </button>
          ))}
        </div>
      </div>

      {positions.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-faint)' }}>
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2"
            style={{ margin: '0 auto 12px' }}>
            <circle cx="12" cy="12" r="10"/>
            <path d="M12 6v6l4 2"/>
          </svg>
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: 4 }}>No open positions</div>
          <div style={{ fontSize: 'var(--text-xs)' }}>Positions will appear here when the engine opens trades</div>
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Entry</th>
                <th>Current</th>
                <th>SL</th>
                <th>TP1 / TP2</th>
                <th>Progress</th>
                <th>Unreal. PnL</th>
                <th>Total PnL</th>
                <th>Opened</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(p => {
                const unrealizedPnl = p.unrealized_pnl ?? 0;
                return (
                  <tr key={p.id}>
                    <td>
                      <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{p.symbol}</span>
                      {p.is_dry_run && <span className="badge badge-yellow" style={{ marginLeft: 6 }}>DRY</span>}
                    </td>
                    <td>
                      <span className={`badge ${p.side === 'BUY' ? 'badge-green' : 'badge-red'}`}>
                        {p.side}
                      </span>
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{p.quantity}</td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{p.entry_price.toFixed(2)}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: p.current_price >= p.entry_price ? 'var(--green)' : 'var(--red)' }}>
                      {p.current_price.toFixed(2)}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--red)' }}>{p.stop_loss.toFixed(2)}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                      <span style={{ color: p.tp1_hit ? 'var(--green)' : undefined }}>{p.take_profit_1.toFixed(2)}</span>
                      {' / '}
                      <span style={{ color: p.tp2_hit ? 'var(--green)' : undefined }}>{p.take_profit_2.toFixed(2)}</span>
                    </td>
                    <td><ProgressBar position={p} /></td>
                    <td><PnlCell value={unrealizedPnl} /></td>
                    <td><PnlCell value={p.total_pnl} /></td>
                    <td style={{ color: 'var(--text-faint)', fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
                      {new Date(p.opened_at).toLocaleTimeString()}
                    </td>
                    <td>
                      {onClose && (
                        <button className="btn btn-danger btn-sm" onClick={() => onClose(p.id)}>
                          Close
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
