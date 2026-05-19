'use client'

import { DashboardShell } from '@/components/layout/DashboardShell'
import { useState, useEffect } from 'react'
import { fmt } from '@/lib/format'
import type { Trade } from '@/types'

export default function JournalPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string|null>(null)
  const [sort, setSort] = useState<'date'|'pnl'|'r'>('date')

  useEffect(() => {
    const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'
    fetch(`${BASE}/journal?limit=100`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(d => { setTrades(d); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  const sorted = [...trades].sort((a, b) => {
    if (sort === 'pnl')  return b.realized_pnl - a.realized_pnl
    if (sort === 'r')    return (b.r_multiple ?? 0) - (a.r_multiple ?? 0)
    return new Date(b.closed_at).getTime() - new Date(a.closed_at).getTime()
  })

  const totalPnl = trades.reduce((s, t) => s + t.realized_pnl, 0)
  const wins     = trades.filter(t => t.realized_pnl > 0).length

  return (
    <DashboardShell>
      <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-6)' }}>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', flexWrap:'wrap', gap:'var(--space-3)' }}>
          <div>
            <h1 style={{ fontSize:'var(--text-lg)', fontWeight:700 }}>Trade Journal</h1>
            <p style={{ color:'var(--color-text-muted)', fontSize:'var(--text-sm)', marginTop:'var(--space-1)' }}>
              {trades.length} trades · Total PnL: <span style={{ fontFamily:'var(--font-mono)', fontWeight:700, color: totalPnl >= 0 ? 'var(--color-profit)' : 'var(--color-loss)' }}>{fmt.pnl(totalPnl)}</span>
              {trades.length > 0 && <span style={{ marginLeft:'var(--space-3)', color:'var(--color-text-muted)' }}>· Win rate: {((wins/trades.length)*100).toFixed(1)}%</span>}
            </p>
          </div>
          <div style={{ display:'flex', gap:'var(--space-2)', alignItems:'center' }}>
            <span style={{ fontSize:'var(--text-xs)', color:'var(--color-text-muted)' }}>Sort:</span>
            {(['date','pnl','r'] as const).map(s => (
              <button key={s} onClick={() => setSort(s)}
                className={`badge ${sort===s ? 'badge-primary' : 'badge-neutral'}`}
                style={{ cursor:'pointer', border:'none' }}>
                {s === 'date' ? 'Date' : s === 'pnl' ? 'PnL' : 'R-Multiple'}
              </button>
            ))}
          </div>
        </div>

        {error && <div className="alert alert-error"><span>⚠</span><span>{error}</span></div>}

        <div className="card" style={{ padding:0 }}>
          {loading ? (
            <div style={{ padding:'var(--space-8)' }}>
              {[1,2,3,4,5].map(i=><div key={i} className="skeleton" style={{height:44,marginBottom:'var(--space-2)'}}/>)}
            </div>
          ) : sorted.length === 0 ? (
            <div className="empty-state">
              <div style={{ fontSize:'2.5rem' }}>📒</div>
              <h3>No trades recorded</h3>
              <p>Completed trades will appear here with full PnL breakdown.</p>
            </div>
          ) : (
            <div style={{ overflowX:'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    {['Symbol','Side','Entry','Exit','Qty','PnL','R-Multiple','Exit Reason','Duration','Date'].map(h=><th key={h}>{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {sorted.map(t => (
                    <tr key={t.id}>
                      <td style={{ fontWeight:600, fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)' }}>{t.symbol}</td>
                      <td><span className={`badge ${t.side==='BUY' ? 'badge-profit' : 'badge-loss'}`}>{t.side}</span></td>
                      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)' }}>{fmt.price(t.entry_price)}</td>
                      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)' }}>{fmt.price(t.exit_price)}</td>
                      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)' }}>{fmt.qty(t.quantity)}</td>
                      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)', fontWeight:700, color: t.realized_pnl>=0 ? 'var(--color-profit)' : 'var(--color-loss)' }}>
                        {fmt.pnl(t.realized_pnl)}
                      </td>
                      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)', fontWeight:600, color: (t.r_multiple??0)>=0 ? 'var(--color-profit)' : 'var(--color-loss)' }}>
                        {t.r_multiple != null ? fmt.r(t.r_multiple) : '—'}
                      </td>
                      <td><span className="badge badge-neutral" style={{fontSize:'0.65rem'}}>{t.exit_reason}</span></td>
                      <td style={{ fontSize:'var(--text-xs)', color:'var(--color-text-muted)', fontFamily:'var(--font-mono)' }}>
                        {t.duration_seconds != null ? fmt.duration(t.duration_seconds) : '—'}
                      </td>
                      <td style={{ fontSize:'var(--text-xs)', color:'var(--color-text-muted)', whiteSpace:'nowrap' }}>
                        {fmt.date(t.closed_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </DashboardShell>
  )
}
