'use client'

import { DashboardShell } from '@/components/layout/DashboardShell'
import { useDashboard }   from '@/hooks/useDashboard'
import { PositionRow }    from '@/components/ui/PositionRow'
import { fmt }            from '@/lib/format'

export default function PositionsPage() {
  const { state: { positions, account, loading } } = useDashboard()
  const totalPnl = positions.reduce((s, p) => s + p.unrealized_pnl, 0)

  return (
    <DashboardShell>
      <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-6)' }}>

        {/* Header row */}
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
          <div>
            <h1 style={{ fontSize:'var(--text-lg)', fontWeight:700 }}>Open Positions</h1>
            <p style={{ color:'var(--color-text-muted)', fontSize:'var(--text-sm)', marginTop:'var(--space-1)' }}>
              {positions.length} active · Unrealized PnL: <span style={{ fontFamily:'var(--font-mono)', fontWeight:600, color: totalPnl >= 0 ? 'var(--color-profit)' : 'var(--color-loss)' }}>{fmt.pnl(totalPnl)}</span>
            </p>
          </div>
        </div>

        {/* Positions table */}
        <div className="card" style={{ padding:0 }}>
          {loading ? (
            <div style={{ padding:'var(--space-8)' }}>
              {[1,2,3].map(i => <div key={i} className="skeleton" style={{height:48, marginBottom:'var(--space-2)'}} />)}
            </div>
          ) : positions.length === 0 ? (
            <div className="empty-state">
              <div style={{ fontSize:'2.5rem' }}>📊</div>
              <h3>No open positions</h3>
              <p>When the engine opens positions, they'll appear here with live PnL.</p>
            </div>
          ) : (
            <div style={{ overflowX:'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    {['Symbol','Side','Quantity','Entry Price','Current','Unrealized PnL','Stop Loss','TP1','TP2','Leverage','Opened','Status'].map(h=><th key={h}>{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {positions.map(p => (
                    <PositionRow key={p.id} position={p} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Account summary */}
        {account && (
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(180px,1fr))', gap:'var(--space-4)' }}>
            {[
              { label:'Total Equity',   v: fmt.usd(account.total_equity) },
              { label:'Available',      v: fmt.usd(account.available_balance) },
              { label:'Used Margin',    v: fmt.usd(account.used_margin) },
              { label:'Unrealized PnL', v: fmt.pnl(account.unrealized_pnl) },
            ].map(({ label, v }) => (
              <div key={label} className="card card-sm">
                <div className="stat-label">{label}</div>
                <div className="stat-value" style={{ marginTop:'var(--space-1)', fontSize:'var(--text-base)' }}>{v}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </DashboardShell>
  )
}
