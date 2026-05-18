'use client'
import { useState } from 'react'
import { usePositions } from '@/hooks/usePositions'
import { useWS } from '@/hooks/useWS'
import { PositionRow } from '@/components/positions/PositionRow'
import { apiFetch } from '@/lib/config'
import clsx from 'clsx'

type Tab = 'positions' | 'orders' | 'journal'

export function BottomPanel() {
  const [tab, setTab] = useState<Tab>('positions')
  const { positions, isLoading, refresh } = usePositions()

  useWS('position_opened',  () => refresh())
  useWS('position_updated', () => refresh())
  useWS('position_closed',  () => refresh())

  const handleCloseAll = async () => {
    if (!confirm('Close ALL open positions?')) return
    await apiFetch('/close_all', { method: 'POST' }).catch(console.error)
    setTimeout(refresh, 500)
  }

  const handleCancelAll = async () => {
    await apiFetch('/cancel_all', { method: 'POST' }).catch(console.error)
  }

  return (
    <div className="h-48 border-t border-divider bg-surface flex flex-col">
      {/* Tab bar */}
      <div className="flex items-center border-b border-divider px-2">
        {(['positions', 'orders', 'journal'] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              'px-4 py-2 text-xs font-medium capitalize transition-colors',
              t === tab ? 'text-primary border-b-2 border-primary' : 'text-muted hover:text-text'
            )}
          >
            {t}
            {t === 'positions' && positions.length > 0 && (
              <span className="ml-1.5 px-1.5 py-0.5 rounded-full bg-primary/20 text-primary text-2xs">{positions.length}</span>
            )}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2 pr-2">
          <button onClick={handleCancelAll} className="text-2xs text-muted hover:text-warning transition-colors">Cancel All</button>
          <button onClick={handleCloseAll}  className="text-2xs text-muted hover:text-error  transition-colors">Close All</button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {tab === 'positions' && (
          <table className="w-full text-xs tabular">
            <thead className="sticky top-0 bg-surface">
              <tr className="text-faint text-left">
                {['Symbol','Side','Qty','Entry','Current','Unr. PnL','SL','TP1','Opened','Action'].map(h => (
                  <th key={h} className="px-3 py-1.5 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr><td colSpan={10} className="px-3 py-6 text-center text-muted">Loading...</td></tr>
              )}
              {!isLoading && positions.length === 0 && (
                <tr><td colSpan={10} className="px-3 py-6 text-center text-muted">No open positions</td></tr>
              )}
              {positions.map(p => <PositionRow key={p.symbol} position={p} onClose={refresh} />)}
            </tbody>
          </table>
        )}
        {tab === 'orders' && (
          <div className="flex items-center justify-center h-full text-muted text-xs">Order history via journal</div>
        )}
        {tab === 'journal' && (
          <div className="flex items-center justify-center h-full text-muted text-xs">Trade journal — export from /api/v1/signals</div>
        )}
      </div>
    </div>
  )
}
