'use client'

import { DashboardShell } from '@/components/layout/DashboardShell'
import { useDashboard }   from '@/hooks/useDashboard'
import { RiskPanel }      from '@/components/ui/RiskPanel'
import { fmt }            from '@/lib/format'

export default function RiskPage() {
  const { state: { metrics: m, health: h, loading }, refresh } = useDashboard()

  return (
    <DashboardShell>
      <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-6)' }}>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
          <div>
            <h1 style={{ fontSize:'var(--text-lg)', fontWeight:700 }}>Risk Management</h1>
            <p style={{ color:'var(--color-text-muted)', fontSize:'var(--text-sm)', marginTop:'var(--space-1)' }}>Live risk metrics and engine controls</p>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={refresh}>↻ Refresh</button>
        </div>

        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:'var(--space-4)', alignItems:'start' }}>
          {/* Left: Risk panel */}
          <div style={{ gridColumn:'span 1' }}>
            <RiskPanel metrics={m} health={h} loading={loading} />
          </div>

          {/* Middle: R-multiple distribution */}
          <div className="card" style={{ gridColumn:'span 1' }}>
            <div style={{ fontWeight:600, fontSize:'var(--text-sm)', marginBottom:'var(--space-4)' }}>R-Multiple Distribution</div>
            {loading || !m?.r_multiples?.length
              ? <div className="empty-state"><p style={{fontSize:'var(--text-xs)'}}>No closed trades yet</p></div>
              : (
                <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-2)' }}>
                  {m.r_multiples.slice(-20).map((r, i) => (
                    <div key={i} style={{ display:'flex', alignItems:'center', gap:'var(--space-3)' }}>
                      <div style={{ width:48, fontSize:'var(--text-xs)', fontFamily:'var(--font-mono)', textAlign:'right',
                        color: r >= 0 ? 'var(--color-profit)' : 'var(--color-loss)', fontWeight:600 }}>
                        {fmt.r(r)}
                      </div>
                      <div style={{ flex:1, height:8, background:'var(--color-surface-3)', borderRadius:'var(--radius-full)', overflow:'hidden' }}>
                        <div style={{
                          height:'100%',
                          width:`${Math.min(Math.abs(r)/5*100,100)}%`,
                          background: r >= 0 ? 'var(--color-profit)' : 'var(--color-loss)',
                          borderRadius:'var(--radius-full)',
                        }}/>
                      </div>
                    </div>
                  ))}
                </div>
              )
            }
          </div>

          {/* Right: Performance stats */}
          <div className="card" style={{ gridColumn:'span 1' }}>
            <div style={{ fontWeight:600, fontSize:'var(--text-sm)', marginBottom:'var(--space-4)' }}>Performance Stats</div>
            {loading || !m
              ? <div style={{display:'flex',flexDirection:'column',gap:'var(--space-2)'}}>{[1,2,3,4,5,6].map(i=><div key={i} className="skeleton" style={{height:28}}/>)}</div>
              : (
                <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-3)' }}>
                  {[
                    { l:'Total Trades',    v:m.total_trades },
                    { l:'Winning',         v:m.winning_trades, color:'var(--color-profit)' },
                    { l:'Losing',          v:m.losing_trades,  color:'var(--color-loss)' },
                    { l:'Win Rate',        v:fmt.pct(m.win_rate) },
                    { l:'Profit Factor',   v:m.profit_factor.toFixed(2) },
                    { l:'Expectancy',      v:fmt.usd(m.expectancy) },
                    { l:'Sharpe Ratio',    v:m.sharpe_ratio.toFixed(2) },
                    { l:'Max DD',          v:fmt.pct(m.max_drawdown), color: m.max_drawdown > 0.08 ? 'var(--color-loss)' : undefined },
                    { l:'Current DD',      v:fmt.pct(m.current_drawdown), color: m.current_drawdown > 0.04 ? 'var(--color-warning)' : undefined },
                    { l:'Daily PnL',       v:fmt.pnl(m.daily_pnl), color: m.daily_pnl >= 0 ? 'var(--color-profit)' : 'var(--color-loss)' },
                    { l:'Consec. Losses',  v:m.consecutive_losses, color: m.consecutive_losses >= 2 ? 'var(--color-warning)' : undefined },
                  ].map(({ l, v, color }) => (
                    <div key={l} style={{ display:'flex', justifyContent:'space-between', padding:'var(--space-2) var(--space-3)', background:'var(--color-surface-3)', borderRadius:'var(--radius-md)' }}>
                      <span style={{ fontSize:'var(--text-xs)', color:'var(--color-text-muted)' }}>{l}</span>
                      <span style={{ fontSize:'var(--text-xs)', fontFamily:'var(--font-mono)', fontWeight:600, color: color ?? 'var(--color-text)' }}>{v}</span>
                    </div>
                  ))}
                </div>
              )
            }
          </div>
        </div>
      </div>
    </DashboardShell>
  )
}
