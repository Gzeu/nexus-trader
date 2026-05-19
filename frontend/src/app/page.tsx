/** ─── Dashboard page ───────────────────────────────────────────────────── */
'use client';
import React from 'react';
import { useDashboard } from '@/hooks/useDashboard';
import { StatusBar } from '@/components/StatusBar';
import { KpiGrid } from '@/components/KpiGrid';
import { PositionsTable } from '@/components/PositionsTable';
import { SignalsFeed } from '@/components/SignalsFeed';
import { EmergencyControls } from '@/components/EmergencyControls';
import { EquityCurve } from '@/components/EquityCurve';

export default function DashboardPage() {
  const {
    health, account, metrics, positions, signals,
    loading, lastUpdated, wsStatus,
    refresh,
    emergencyStop, resumeTrading, cancelAll, closeAll,
  } = useDashboard();

  return (
    <div style={{ minHeight: '100dvh', display: 'flex', flexDirection: 'column', background: 'var(--bg)' }}>
      {/* Top bar */}
      <StatusBar
        health={health}
        wsStatus={wsStatus}
        lastUpdated={lastUpdated}
        onRefresh={refresh}
      />

      {/* Main content */}
      <main style={{
        flex: 1, padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16,
        maxWidth: 1600, width: '100%', margin: '0 auto',
      }}>

        {/* KPI Row */}
        <section className="animate-fade-up">
          <KpiGrid account={account} metrics={metrics} loading={loading} />
        </section>

        {/* Equity + Controls */}
        <section style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 16 }}
          className="animate-fade-up" data-delay="60">

          {/* Equity curve card */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--purple)" strokeWidth="2">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
              </svg>
              <span style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>Equity Curve</span>
              {metrics && (
                <span className="badge badge-muted" style={{ marginLeft: 'auto' }}>
                  {metrics.total_trades} trades
                </span>
              )}
            </div>
            <EquityCurve
              data={metrics?.equity_curve ?? []}
              width={600}
              height={100}
            />
            {/* Mini stats row */}
            <div style={{ display: 'flex', gap: 20, paddingTop: 4, borderTop: '1px solid var(--border)' }}>
              {[
                { label: 'Expectancy', value: metrics ? `$${metrics.expectancy.toFixed(2)}` : '—' },
                { label: 'Max DD',     value: metrics ? `${(metrics.max_drawdown*100).toFixed(2)}%` : '—' },
                { label: 'Consec. Loss', value: String(metrics?.consecutive_losses ?? '—') },
              ].map(item => (
                <div key={item.label} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)', letterSpacing: '0.07em', textTransform: 'uppercase' }}>
                    {item.label}
                  </span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', fontWeight: 600 }}>
                    {item.value}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Controls */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <EmergencyControls
              isPaused={health?.is_paused ?? false}
              onEmergency={emergencyStop}
              onResume={resumeTrading}
              onCancelAll={cancelAll}
              onCloseAll={closeAll}
            />

            {/* Account mini-card */}
            <div className="card" style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 2 }}>Account</div>
              {loading ? (
                [1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 12 }} />)
              ) : [
                { label: 'Equity',    value: account ? `$${account.total_equity.toFixed(2)}` : '—' },
                { label: 'Available', value: account ? `$${account.available_balance.toFixed(2)}` : '—' },
                { label: 'Margin',    value: account ? `$${account.used_margin.toFixed(2)}` : '—' },
              ].map(row => (
                <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{row.label}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', fontWeight: 600 }}>{row.value}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Positions table */}
        <section className="animate-fade-up" style={{ animationDelay: '120ms' }}>
          <PositionsTable positions={positions} loading={loading} />
        </section>

        {/* Signals feed */}
        <section className="animate-fade-up" style={{ animationDelay: '160ms' }}>
          <SignalsFeed signals={signals} loading={loading} />
        </section>

      </main>

      {/* Footer */}
      <footer style={{
        padding: '10px 20px',
        borderTop: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        fontSize: 'var(--text-xs)', color: 'var(--text-faint)',
      }}>
        <span>NexusTrader v2 · {health?.market_mode?.toUpperCase() ?? '—'} Mode</span>
        <span style={{ fontFamily: 'var(--font-mono)' }}>
          {health?.dry_run ? 'DRY RUN · ' : ''}
          {health?.testnet ? 'TESTNET' : 'MAINNET'}
        </span>
      </footer>
    </div>
  );
}
