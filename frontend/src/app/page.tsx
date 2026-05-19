/** ─── NexusTrader Dashboard — Tabbed Layout ──────────────────────────────── */
'use client';
import React, { useState } from 'react';
import dynamic from 'next/dynamic';
import { useDashboard } from '@/hooks/useDashboard';
import { StatusBar }        from '@/components/StatusBar';
import { KpiGrid }          from '@/components/KpiGrid';
import { PositionsTable }   from '@/components/PositionsTable';
import { SignalsFeed }      from '@/components/SignalsFeed';
import { EmergencyControls } from '@/components/EmergencyControls';
import { EquityCurve }      from '@/components/EquityCurve';
import { BalancePanel }     from '@/components/balance/BalancePanel';
import { AssetsTable }      from '@/components/balance/AssetsTable';
import { PnlSummary }       from '@/components/balance/PnlSummary';
import { SettingsPanel }    from '@/components/settings/SettingsPanel';
import { ChartSkeleton }    from '@/components/chart/ChartSkeleton';

// SSR=false — Lightweight Charts uses window/document
const TradingChart = dynamic(
  () => import('@/components/chart/TradingChart').then(m => m.TradingChart),
  { ssr: false, loading: () => <ChartSkeleton height={400} /> }
);

type Tab = 'overview' | 'chart' | 'balance' | 'positions' | 'signals' | 'settings';

/** Safely format a nullable number, returning '—' when missing. */
function fmt(value: number | null | undefined, decimals = 2, prefix = '', suffix = ''): string {
  if (value == null || !isFinite(value)) return '—';
  return `${prefix}${value.toFixed(decimals)}${suffix}`;
}

const TABS: { id: Tab; label: string; icon: JSX.Element }[] = [
  { id: 'overview',  label: 'Overview',  icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg> },
  { id: 'chart',     label: 'Chart',     icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg> },
  { id: 'balance',   label: 'Balance',   icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg> },
  { id: 'positions', label: 'Positions', icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg> },
  { id: 'signals',   label: 'Signals',   icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg> },
  { id: 'settings',  label: 'Settings',  icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg> },
];

export default function DashboardPage() {
  const [tab, setTab] = useState<Tab>('overview');
  // Shared chart state between Overview mini-chart and full Chart tab
  const [chartSymbol,    setChartSymbol]    = useState('BTCUSDT');
  const [chartTimeframe, setChartTimeframe] = useState('15m');

  const {
    health, account, metrics, positions, signals,
    loading, lastUpdated, wsStatus,
    refresh,
    emergencyStop, resumeTrading, cancelAll, closeAll,
  } = useDashboard();

  return (
    <div style={{ minHeight: '100dvh', display: 'flex', flexDirection: 'column', background: 'var(--bg)' }}>

      {/* ── Status Bar ───────────────────────────────────────────────────── */}
      <StatusBar health={health} wsStatus={wsStatus} lastUpdated={lastUpdated} onRefresh={refresh} />

      {/* ── Tab Navigation ──────────────────────────────────────────────── */}
      <nav style={{ display: 'flex', gap: 2, padding: '0 20px', background: 'var(--surface)', borderBottom: '1px solid var(--border)', overflowX: 'auto' }}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '10px 14px', background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 'var(--text-sm)', fontWeight: 500,
              color: tab === t.id ? 'var(--text)' : 'var(--text-muted)',
              borderBottom: tab === t.id ? '2px solid var(--blue)' : '2px solid transparent',
              marginBottom: -1,
              transition: 'color 150ms ease, border-color 150ms ease',
              whiteSpace: 'nowrap',
            }}
          >
            {t.icon}
            {t.label}
            {t.id === 'positions' && positions.length > 0 && (
              <span className="badge badge-blue" style={{ fontSize: 10, padding: '1px 6px' }}>{positions.length}</span>
            )}
            {t.id === 'signals' && signals.length > 0 && (
              <span className="badge badge-green" style={{ fontSize: 10, padding: '1px 6px' }}>{signals.length}</span>
            )}
          </button>
        ))}
      </nav>

      {/* ── Page Content ─────────────────────────────────────────────────── */}
      <main style={{ flex: 1, padding: '16px 20px', maxWidth: 1600, width: '100%', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>

        {/* ══ OVERVIEW ═════════════════════════════════════════════════ */}
        {tab === 'overview' && (
          <>
            <section className="animate-fade-up">
              <KpiGrid account={account} metrics={metrics} loading={loading} />
            </section>

            {/* Mini chart + sidebar */}
            <section style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 16 }} className="animate-fade-up">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                <TradingChart
                  symbol={chartSymbol}
                  timeframe={chartTimeframe}
                  positions={positions}
                  height={400}
                  showRsi={false}
                  onSymbolChange={setChartSymbol}
                  onTimeframeChange={setChartTimeframe}
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <EmergencyControls
                  isPaused={health?.is_paused ?? false}
                  onEmergency={emergencyStop}
                  onResume={resumeTrading}
                  onCancelAll={cancelAll}
                  onCloseAll={closeAll}
                />

                {/* Equity mini card */}
                <div className="card" style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--purple)" strokeWidth="2">
                      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
                    </svg>
                    <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)', letterSpacing: '0.07em', textTransform: 'uppercase' }}>Equity Curve</span>
                    {metrics?.total_trades != null && (
                      <span className="badge badge-muted" style={{ marginLeft: 'auto', fontSize: 10 }}>{metrics.total_trades} trades</span>
                    )}
                  </div>
                  <EquityCurve data={metrics?.equity_curve ?? []} width={280} height={70} />
                  <div style={{ display: 'flex', gap: 12, paddingTop: 4, borderTop: '1px solid var(--border)' }}>
                    {[
                      { label: 'Expect.',    value: fmt(metrics?.expectancy,   2, '$') },
                      { label: 'Max DD',     value: fmt(metrics?.max_drawdown != null ? metrics.max_drawdown * 100 : null, 2, '', '%') },
                      { label: 'C.Loss',     value: metrics?.consecutive_losses != null ? String(metrics.consecutive_losses) : '—' },
                    ].map(item => (
                      <div key={item.label} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)', letterSpacing: '0.07em', textTransform: 'uppercase' }}>{item.label}</span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', fontWeight: 600 }}>{item.value}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Account mini card */}
                <div className="card" style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)', letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 2 }}>Account</div>
                  {loading ? [1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 12 }} />) : [
                    { label: 'Equity',    value: fmt(account?.total_equity,      2, '$') },
                    { label: 'Available', value: fmt(account?.available_balance, 2, '$') },
                    { label: 'Margin',    value: fmt(account?.used_margin,       2, '$') },
                  ].map(row => (
                    <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{row.label}</span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', fontWeight: 600 }}>{row.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section className="animate-fade-up" style={{ animationDelay: '80ms' }}>
              <PositionsTable positions={positions.slice(0, 5)} loading={loading} />
            </section>
          </>
        )}

        {/* ══ CHART ════════════════════════════════════════════════════ */}
        {tab === 'chart' && (
          <div className="animate-fade-up" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <TradingChart
              symbol={chartSymbol}
              timeframe={chartTimeframe}
              positions={positions}
              height={640}
              showRsi={true}
              onSymbolChange={setChartSymbol}
              onTimeframeChange={setChartTimeframe}
            />
            <PositionsTable positions={positions} loading={loading} />
          </div>
        )}

        {/* ══ BALANCE ══════════════════════════════════════════════════ */}
        {tab === 'balance' && (
          <div className="animate-fade-up" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: 16, alignItems: 'start' }}>
              <BalancePanel account={account} loading={loading} />
              <PnlSummary   metrics={metrics} loading={loading} />
            </div>
            <AssetsTable account={account} loading={loading} />
          </div>
        )}

        {/* ══ POSITIONS ════════════════════════════════════════════════ */}
        {tab === 'positions' && (
          <div className="animate-fade-up" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 16, alignItems: 'start' }}>
              <PositionsTable positions={positions} loading={loading} />
              <EmergencyControls
                isPaused={health?.is_paused ?? false}
                onEmergency={emergencyStop}
                onResume={resumeTrading}
                onCancelAll={cancelAll}
                onCloseAll={closeAll}
              />
            </div>
          </div>
        )}

        {/* ══ SIGNALS ══════════════════════════════════════════════════ */}
        {tab === 'signals' && (
          <div className="animate-fade-up">
            <SignalsFeed signals={signals} loading={loading} />
          </div>
        )}

        {/* ══ SETTINGS ═════════════════════════════════════════════════ */}
        {tab === 'settings' && (
          <div className="animate-fade-up">
            <SettingsPanel />
          </div>
        )}

      </main>

      {/* ── Footer ──────────────────────────────────────────────────── */}
      <footer style={{ padding: '10px 20px', borderTop: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 'var(--text-xs)', color: 'var(--text-faint)' }}>
        <span>NexusTrader v2 · {health?.market_mode?.toUpperCase() ?? '—'} Mode</span>
        <span style={{ fontFamily: 'var(--font-mono)' }}>
          {health?.dry_run ? 'DRY RUN · ' : ''}{health?.testnet ? 'TESTNET' : 'MAINNET'}
        </span>
      </footer>
    </div>
  );
}
