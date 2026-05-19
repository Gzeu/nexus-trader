'use client'

import { DashboardShell } from '@/components/layout/DashboardShell'
import { useDashboard }   from '@/hooks/useDashboard'
import { SignalRow }      from '@/components/ui/SignalRow'
import { useState }       from 'react'
import type { Action }    from '@/types'

const ACTIONS: (Action | 'ALL')[] = ['ALL','BUY','SELL','HOLD','CLOSE','REVERSE']

export default function SignalsPage() {
  const { state: { signals, loading } } = useDashboard()
  const [filter, setFilter] = useState<Action | 'ALL'>('ALL')

  const filtered = filter === 'ALL' ? signals : signals.filter(s => s.action === filter)

  return (
    <DashboardShell>
      <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-6)' }}>

        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', flexWrap:'wrap', gap:'var(--space-3)' }}>
          <div>
            <h1 style={{ fontSize:'var(--text-lg)', fontWeight:700 }}>Strategy Signals</h1>
            <p style={{ color:'var(--color-text-muted)', fontSize:'var(--text-sm)', marginTop:'var(--space-1)' }}>
              {signals.length} signals · last 50
            </p>
          </div>
          {/* Filter chips */}
          <div style={{ display:'flex', gap:'var(--space-2)', flexWrap:'wrap' }}>
            {ACTIONS.map(a => (
              <button key={a} onClick={() => setFilter(a)}
                className={`badge ${filter===a ? 'badge-primary' : 'badge-neutral'}`}
                style={{ cursor:'pointer', border:'none', padding:'var(--space-1) var(--space-3)' }}>
                {a}
              </button>
            ))}
          </div>
        </div>

        <div className="card" style={{ padding:0 }}>
          {loading ? (
            <div style={{ padding:'var(--space-8)' }}>
              {[1,2,3,4].map(i=><div key={i} className="skeleton" style={{height:44,marginBottom:'var(--space-2)'}}/>)}
            </div>
          ) : filtered.length === 0 ? (
            <div className="empty-state">
              <div style={{ fontSize:'2.5rem' }}>⚡</div>
              <h3>No signals</h3>
              <p>Start the automation engine to receive strategy signals.</p>
            </div>
          ) : (
            <div style={{ overflowX:'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    {['Symbol','Action','Confidence','Entry','SL','TP1','TP2','RR','Timeframe','Reason','Time'].map(h=><th key={h}>{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(s => <SignalRow key={s.id} signal={s} />)}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </DashboardShell>
  )
}
