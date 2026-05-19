'use client'

import { useDashboard } from '@/hooks/useDashboard'
import { StatCard }      from '@/components/ui/StatCard'
import { PositionRow }   from '@/components/ui/PositionRow'
import { SignalRow }     from '@/components/ui/SignalRow'
import { RiskPanel }     from '@/components/ui/RiskPanel'
import { fmt }           from '@/lib/format'

export function OverviewPage() {
  const { state } = useDashboard()
  const { health, account, positions, signals, metrics, loading, error } = state

  if (error) return (
    <div className="alert alert-error" style={{maxWidth:480}}>
      <span>⚠</span>
      <div><strong>Backend unreachable</strong><br/><span style={{fontSize:'var(--text-xs)'}}>{error}</span></div>
    </div>
  )

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-6)' }}>

      {/* ── Dry Run / Testnet banners ──────────────────────── */}
      {health?.dry_run && (
        <div className="alert alert-warning">
          <span>🔒</span>
          <span><strong>DRY RUN</strong> — No real orders are being placed. Set <code>DRY_RUN=false</code> to go live.</span>
        </div>
      )}
      {health?.testnet && (
        <div className="alert alert-info">
          <span>🧪</span>
          <span><strong>TESTNET</strong> — Connected to Binance Testnet.</span>
        </div>
      )}
      {health?.is_paused && (
        <div className="alert alert-error">
          <span>⏸</span>
          <span><strong>TRADING PAUSED</strong> — {metrics?.pause_reason ?? 'Risk limit reached'}</span>
        </div>
      )}

      {/* ── KPI Row ────────────────────────────────────────── */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(200px,1fr))', gap:'var(--space-4)' }}>
        <StatCard label="Total Equity"     loading={loading} value={account ? fmt.usd(account.total_equity)     : '—'} />
        <StatCard label="Available"        loading={loading} value={account ? fmt.usd(account.available_balance) : '—'} />
        <StatCard label="Today's PnL"      loading={loading} value={account ? fmt.pnl(account.realized_pnl_today) : '—'}
          change={account ? account.realized_pnl_today : undefined} />
        <StatCard label="Unrealized PnL"   loading={loading} value={account ? fmt.pnl(account.unrealized_pnl)    : '—'}
          change={account ? account.unrealized_pnl : undefined} />
        <StatCard label="Open Positions"   loading={loading} value={String(positions.length)} />
        <StatCard label="Win Rate"         loading={loading} value={metrics ? fmt.pct(metrics.win_rate)      : '—'} />
        <StatCard label="Profit Factor"    loading={loading} value={metrics ? metrics.profit_factor.toFixed(2) : '—'} />
        <StatCard label="Sharpe Ratio"     loading={loading} value={metrics ? metrics.sharpe_ratio.toFixed(2)  : '—'} />
      </div>

      {/* ── Main 2-col grid ────────────────────────────────── */}
      <div style={{ display:'grid', gridTemplateColumns:'1fr 340px', gap:'var(--space-6)', alignItems:'start' }}>

        {/* Left col */}
        <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-6)' }}>

          {/* Open Positions */}
          <section className="card">
            <SectionHeader title="Open Positions" count={positions.length} />
            {positions.length === 0
              ? <EmptyState icon="📊" title="No open positions" desc="Signals will open positions automatically" />
              : (
                <div style={{ overflowX:'auto', marginTop:'var(--space-3)' }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        {['Symbol','Side','Qty','Entry','Current','PnL','SL','TP1','Actions'].map(h => <th key={h}>{h}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {positions.map(p => <PositionRow key={p.id} position={p} />)}
                    </tbody>
                  </table>
                </div>
              )
            }
          </section>

          {/* Recent Signals */}
          <section className="card">
            <SectionHeader title="Recent Signals" count={signals.length} />
            {signals.length === 0
              ? <EmptyState icon="⚡" title="No signals yet" desc="The strategy engine will emit signals here" />
              : (
                <div style={{ overflowX:'auto', marginTop:'var(--space-3)' }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        {['Symbol','Action','Confidence','Entry','SL','TP1','RR','Timeframe','Reason'].map(h => <th key={h}>{h}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {signals.slice(0,15).map(s => <SignalRow key={s.id} signal={s} />)}
                    </tbody>
                  </table>
                </div>
              )
            }
          </section>
        </div>

        {/* Right col: Risk Panel */}
        <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-4)' }}>
          <RiskPanel metrics={metrics} health={health} loading={loading} />
          <EmergencyControls />
        </div>
      </div>
    </div>
  )
}

function SectionHeader({ title, count }: { title: string; count: number }) {
  return (
    <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'var(--space-1)' }}>
      <h2 style={{ fontWeight:600, fontSize:'var(--text-base)' }}>{title}</h2>
      {count > 0 && <span className="badge badge-neutral">{count}</span>}
    </div>
  )
}

function EmptyState({ icon, title, desc }: { icon:string; title:string; desc:string }) {
  return (
    <div className="empty-state">
      <div style={{ fontSize:'2rem' }}>{icon}</div>
      <h3>{title}</h3>
      <p>{desc}</p>
    </div>
  )
}

function EmergencyControls() {
  const [busy, setBusy] = useState(false)
  const { api } = require('@/lib/api')
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try { await fn() } finally { setBusy(false) }
  }
  return (
    <section className="card">
      <div style={{ fontWeight:600, fontSize:'var(--text-sm)', marginBottom:'var(--space-3)' }}>Emergency Controls</div>
      <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-2)' }}>
        <button className="btn btn-danger btn-sm" disabled={busy} onClick={() => act(api.emergencyStop)}>🛑 Emergency Stop</button>
        <button className="btn btn-ghost  btn-sm" disabled={busy} onClick={() => act(api.cancelAll)}>✕ Cancel All Orders</button>
        <button className="btn btn-ghost  btn-sm" disabled={busy} onClick={() => act(api.closeAll)}>⬜ Close All Positions</button>
        <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => act(api.resumeTrading)}>▶ Resume Trading</button>
      </div>
    </section>
  )
}

import { useState } from 'react'
