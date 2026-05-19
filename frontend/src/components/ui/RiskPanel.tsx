'use client'

import type { HealthResponse, RiskMetrics } from '@/types'
import { fmt } from '@/lib/format'

interface Props {
  metrics: RiskMetrics | null
  health:  HealthResponse | null
  loading: boolean
}

export function RiskPanel({ metrics: m, health: h, loading }: Props) {
  if (loading) return (
    <div className="card" style={{ display:'flex', flexDirection:'column', gap:'var(--space-3)' }}>
      {[1,2,3,4].map(i => <div key={i} className="skeleton" style={{height:32}} />)}
    </div>
  )

  const ddPct   = m ? m.current_drawdown * 100 : 0
  const maxDdPct= m ? m.max_drawdown     * 100 : 0
  const dailyPct= m ? Math.abs(m.daily_pnl / 1000) * 100 : 0 // approx

  const ddColor  = ddPct   < 4  ? 'risk-low' : ddPct   < 8  ? 'risk-medium' : 'risk-high'
  const dlyColor = dailyPct< 1  ? 'risk-low' : dailyPct< 2  ? 'risk-medium' : 'risk-high'

  return (
    <section className="card">
      <div style={{ fontWeight:600, fontSize:'var(--text-sm)', marginBottom:'var(--space-4)' }}>Risk Dashboard</div>

      <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-4)' }}>

        {/* System status */}
        <RiskRow label="System" value={
          <div style={{ display:'flex', alignItems:'center', gap:'var(--space-2)' }}>
            <span className={`status-dot ${h?.is_paused ? 'paused' : 'live'}`} />
            <span style={{ fontSize:'var(--text-xs)', fontWeight:500 }}>
              {h?.is_paused ? 'PAUSED' : 'ACTIVE'}
            </span>
          </div>
        } />

        {/* Reconciliation */}
        <RiskRow label="Reconciliation" value={
          <span className={`badge ${h?.is_reconciled ? 'badge-profit' : 'badge-error'}`}>
            {h?.is_reconciled ? '✓ Synced' : '✗ Not synced'}
          </span>
        } />

        {/* Mode */}
        <RiskRow label="Mode" value={
          <div style={{ display:'flex', gap:'var(--space-1)' }}>
            <span className="badge badge-neutral">{h?.market_mode?.toUpperCase() ?? '—'}</span>
            {h?.dry_run  && <span className="badge badge-warning">DRY</span>}
            {h?.testnet  && <span className="badge badge-info">TEST</span>}
          </div>
        } />

        <div className="separator" style={{ margin:'var(--space-2) 0' }} />

        {/* Drawdown */}
        <div>
          <div style={{ display:'flex', justifyContent:'space-between', marginBottom:'var(--space-2)' }}>
            <span style={{ fontSize:'var(--text-xs)', color:'var(--color-text-muted)', fontWeight:500 }}>Current DD</span>
            <span style={{ fontSize:'var(--text-xs)', fontFamily:'var(--font-mono)', fontWeight:600, color: ddPct > 8 ? 'var(--color-loss)' : 'var(--color-text)' }}>
              {ddPct.toFixed(2)}% / {maxDdPct.toFixed(2)}%
            </span>
          </div>
          <div className="risk-bar-track">
            <div className={`risk-bar-fill ${ddColor}`} style={{ width:`${Math.min(ddPct/12*100,100)}%` }} />
          </div>
        </div>

        {/* Daily PnL */}
        <RiskRow label="Daily PnL" value={
          <span style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)', fontWeight:600,
            color: m && m.daily_pnl >= 0 ? 'var(--color-profit)' : 'var(--color-loss)' }}>
            {m ? fmt.pnl(m.daily_pnl) : '—'}
          </span>
        } />

        {/* Stats */}
        <div className="separator" style={{ margin:'var(--space-2) 0' }} />
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'var(--space-3)' }}>
          <MiniStat label="Win Rate"      value={m ? fmt.pct(m.win_rate)           : '—'} />
          <MiniStat label="Profit Factor" value={m ? m.profit_factor.toFixed(2)    : '—'} />
          <MiniStat label="Expectancy"    value={m ? fmt.usd(m.expectancy)         : '—'} />
          <MiniStat label="Sharpe"        value={m ? m.sharpe_ratio.toFixed(2)     : '—'} />
          <MiniStat label="Total Trades"  value={m ? String(m.total_trades)        : '—'} />
          <MiniStat label="Consec. Losses" value={m ? String(m.consecutive_losses) : '—'}
            alert={m ? m.consecutive_losses >= 2 : false} />
        </div>
      </div>
    </section>
  )
}

function RiskRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
      <span style={{ fontSize:'var(--text-xs)', color:'var(--color-text-muted)', fontWeight:500 }}>{label}</span>
      {value}
    </div>
  )
}

function MiniStat({ label, value, alert }: { label:string; value:string; alert?:boolean }) {
  return (
    <div style={{
      background:'var(--color-surface-3)',
      borderRadius:'var(--radius-md)',
      padding:'var(--space-2) var(--space-3)',
      border: alert ? '1px solid var(--color-loss-border)' : '1px solid var(--color-border)',
    }}>
      <div style={{ fontSize:'var(--text-xs)', color:'var(--color-text-faint)', marginBottom:2 }}>{label}</div>
      <div style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)', fontWeight:600, color: alert ? 'var(--color-loss)' : 'var(--color-text)' }}>{value}</div>
    </div>
  )
}
