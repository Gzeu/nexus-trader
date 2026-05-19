'use client';
import React from 'react';
import type { RiskMetrics } from '@/types/trading';
import { fmtUSD, fmtPct, pnlClass } from '@/lib/balance';

interface Props {
  metrics: RiskMetrics | null;
  loading: boolean;
}

function StatBlock({ label, value, color, sub }: { label: string; value: string; color?: string; sub?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3,
      padding: '12px 16px', background: 'var(--surface-2)',
      borderRadius: 'var(--r-md)', border: '1px solid var(--border)', flex: '1 1 140px', minWidth: 0 }}>
      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)',
        textTransform: 'uppercase', letterSpacing: '0.07em', fontWeight: 600 }}>
        {label}
      </span>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-lg)',
        fontWeight: 700, color: color ?? 'var(--text)', lineHeight: 1 }}>
        {value}
      </span>
      {sub && <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{sub}</span>}
    </div>
  );
}

export function PnlSummary({ metrics, loading }: Props) {
  if (loading) {
    return (
      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div className="skeleton" style={{ height: 14, width: 120 }} />
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {[1,2,3,4,5,6].map(i => (
            <div key={i} className="skeleton" style={{ height: 76, flex: '1 1 140px', borderRadius: 10 }} />
          ))}
        </div>
      </div>
    );
  }

  const m = metrics;

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2">
          <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>
          <polyline points="16 7 22 7 22 13"/>
        </svg>
        <span style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>Performance Summary</span>
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <StatBlock
          label="PnL Today"
          value={m ? fmtUSD(m.daily_pnl) : '—'}
          color={m ? pnlClass(m.daily_pnl) : undefined}
          sub={m ? `${m.total_trades} trades` : undefined}
        />
        <StatBlock
          label="Win Rate"
          value={m ? fmtPct(m.win_rate * 100, 1) : '—'}
          color={m && m.win_rate >= 0.5 ? 'var(--green)' : 'var(--yellow)'}
          sub={m ? `${m.winning_trades}W / ${m.losing_trades}L` : undefined}
        />
        <StatBlock
          label="Profit Factor"
          value={m ? m.profit_factor.toFixed(2) : '—'}
          color={m ? (m.profit_factor >= 1.5 ? 'var(--green)' : m.profit_factor >= 1 ? 'var(--yellow)' : 'var(--red)') : undefined}
        />
        <StatBlock
          label="Sharpe Ratio"
          value={m ? m.sharpe_ratio.toFixed(3) : '—'}
          color={m ? (m.sharpe_ratio >= 1 ? 'var(--green)' : m.sharpe_ratio >= 0 ? 'var(--yellow)' : 'var(--red)') : undefined}
        />
        <StatBlock
          label="Drawdown"
          value={m ? fmtPct(m.current_drawdown * 100, 2) : '—'}
          color={m ? (m.current_drawdown > 0.08 ? 'var(--red)' : m.current_drawdown > 0.04 ? 'var(--yellow)' : 'var(--text)') : undefined}
          sub={m ? `Max: ${fmtPct(m.max_drawdown * 100, 2)}` : undefined}
        />
        <StatBlock
          label="Expectancy"
          value={m ? fmtUSD(m.expectancy) : '—'}
          color={m ? pnlClass(m.expectancy) : undefined}
          sub="per trade"
        />
      </div>

      {/* R-multiple distribution mini bar */}
      {m && m.r_multiples.length > 0 && (
        <div style={{ paddingTop: 8, borderTop: '1px solid var(--border)' }}>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)',
            letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8 }}>
            R-Multiple Distribution
          </div>
          <div style={{ display: 'flex', gap: 3, alignItems: 'flex-end', height: 40 }}>
            {m.r_multiples.slice(-30).map((r, i) => {
              const h = Math.min(Math.abs(r) * 10, 40);
              return (
                <div key={i} style={{
                  width: 6, height: h, borderRadius: 2,
                  background: r >= 0 ? 'var(--green)' : 'var(--red)',
                  opacity: 0.7, flexShrink: 0,
                  transition: 'height 300ms ease',
                }} title={`R: ${r.toFixed(2)}`} />
              );
            })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)' }}>Last 30 trades</span>
            <span style={{ fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
              Avg R: {(m.r_multiples.slice(-30).reduce((s,v) => s+v,0) / Math.min(m.r_multiples.length, 30)).toFixed(2)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
