/** ─── KpiGrid — top KPI cards row ──────────────────────────────────────── */
'use client';
import React, { useEffect, useRef } from 'react';
import type { AccountInfo, RiskMetrics } from '@/types/trading';

interface KpiCardProps {
  label:   string;
  value:   string;
  sub?:    string;
  color?:  string;
  delay?:  number;
}

function KpiCard({ label, value, sub, color = 'var(--text)', delay = 0 }: KpiCardProps) {
  const ref = useRef<HTMLDivElement>(null);
  const prev = useRef<string>(value);

  useEffect(() => {
    if (prev.current !== value && ref.current) {
      ref.current.classList.remove('num-update');
      void ref.current.offsetWidth; // reflow
      ref.current.classList.add('num-update');
    }
    prev.current = value;
  }, [value]);

  return (
    <div
      className="card animate-fade-up"
      style={{
        animationDelay: `${delay}ms`,
        display: 'flex', flexDirection: 'column', gap: 4,
        minWidth: 0,
      }}
    >
      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
        {label}
      </span>
      <div ref={ref} style={{ fontSize: 'var(--text-xl)', fontWeight: 700, color, fontFamily: 'var(--font-mono)', letterSpacing: '-0.03em', lineHeight: 1 }}>
        {value}
      </div>
      {sub && <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2 }}>{sub}</span>}
    </div>
  );
}

function KpiSkeleton() {
  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div className="skeleton" style={{ height: 12, width: '60%' }} />
      <div className="skeleton" style={{ height: 28, width: '80%' }} />
      <div className="skeleton" style={{ height: 10, width: '50%' }} />
    </div>
  );
}

function fmtUSD(n: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(n);
}
function fmtPct(n: number) { return `${(n * 100).toFixed(2)}%`; }
function fmtNum(n: number, d = 2) { return n.toFixed(d); }

interface Props {
  account: AccountInfo | null;
  metrics: RiskMetrics | null;
  loading: boolean;
}

export function KpiGrid({ account, metrics, loading }: Props) {
  if (loading) {
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
        {Array.from({ length: 8 }).map((_, i) => <KpiSkeleton key={i} />)}
      </div>
    );
  }

  const pnlToday   = account?.realized_pnl_today ?? 0;
  const unreal     = account?.unrealized_pnl     ?? 0;
  const equity     = account?.total_equity        ?? 0;
  const avail      = account?.available_balance   ?? 0;
  const winRate    = metrics?.win_rate             ?? 0;
  const pf         = metrics?.profit_factor        ?? 0;
  const sharpe     = metrics?.sharpe_ratio         ?? 0;
  const drawdown   = metrics?.current_drawdown     ?? 0;

  const cards: KpiCardProps[] = [
    {
      label: 'Total Equity',
      value: fmtUSD(equity),
      sub: `Available: ${fmtUSD(avail)}`,
      color: 'var(--text)',
    },
    {
      label: 'PnL Today',
      value: fmtUSD(pnlToday),
      sub: pnlToday >= 0 ? 'Realized' : 'Realized loss',
      color: pnlToday >= 0 ? 'var(--green)' : 'var(--red)',
    },
    {
      label: 'Unrealized PnL',
      value: fmtUSD(unreal),
      color: unreal >= 0 ? 'var(--green)' : 'var(--red)',
    },
    {
      label: 'Win Rate',
      value: fmtPct(winRate),
      sub: `${metrics?.winning_trades ?? 0}W / ${metrics?.losing_trades ?? 0}L`,
      color: winRate >= 0.5 ? 'var(--green)' : 'var(--yellow)',
    },
    {
      label: 'Profit Factor',
      value: fmtNum(pf),
      color: pf >= 1.5 ? 'var(--green)' : pf >= 1 ? 'var(--yellow)' : 'var(--red)',
    },
    {
      label: 'Sharpe Ratio',
      value: fmtNum(sharpe, 3),
      color: sharpe >= 1 ? 'var(--green)' : sharpe >= 0 ? 'var(--yellow)' : 'var(--red)',
    },
    {
      label: 'Drawdown',
      value: fmtPct(drawdown),
      sub: `Max: ${fmtPct(metrics?.max_drawdown ?? 0)}`,
      color: drawdown > 0.08 ? 'var(--red)' : drawdown > 0.04 ? 'var(--yellow)' : 'var(--text)',
    },
    {
      label: 'Total Trades',
      value: String(metrics?.total_trades ?? 0),
      sub: `Consec. losses: ${metrics?.consecutive_losses ?? 0}`,
      color: 'var(--text)',
    },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
      {cards.map((c, i) => (
        <KpiCard key={c.label} {...c} delay={i * 40} />
      ))}
    </div>
  );
}
