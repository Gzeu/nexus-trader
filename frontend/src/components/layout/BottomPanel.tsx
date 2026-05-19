'use client'
import { useState, useRef, useCallback } from 'react'
import { usePositions } from '@/hooks/usePositions'
import { useOrders } from '@/hooks/useOrders'
import { useWS } from '@/hooks/useWS'
import { PositionRow } from '@/components/positions/PositionRow'
import { Layers, List, BookOpen, ChevronUp, ChevronDown, X } from 'lucide-react'
import clsx from 'clsx'

type Tab = 'positions' | 'orders' | 'journal'
const MIN_H = 36
const DEFAULT_H = 200
const MAX_H = 480

export function BottomPanel() {
  const [tab, setTab]   = useState<Tab>('positions')
  const [height, setHeight] = useState(DEFAULT_H)
  const [collapsed, setCollapsed] = useState(false)
  const dragRef = useRef<{ startY: number; startH: number } | null>(null)

  const { positions, refresh: refreshPos } = usePositions()
  const { orders,    refresh: refreshOrd } = useOrders()

  useWS('order_filled',      useCallback(() => { refreshPos(); refreshOrd() }, []))
  useWS('position_opened',   useCallback(() => refreshPos(), []))
  useWS('position_closed',   useCallback(() => refreshPos(), []))

  // Drag-to-resize
  const onMouseDown = (e: React.MouseEvent) => {
    e.preventDefault()
    dragRef.current = { startY: e.clientY, startH: height }
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return
      const delta = dragRef.current.startY - ev.clientY
      const next = Math.max(MIN_H, Math.min(MAX_H, dragRef.current.startH + delta))
      setHeight(next)
      if (next > MIN_H + 10) setCollapsed(false)
    }
    const onUp = () => {
      dragRef.current = null
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  const tabs: { id: Tab; label: string; icon: React.ReactNode; count?: number }[] = [
    { id: 'positions', label: 'Positions', icon: <Layers size={11} />,  count: positions.length },
    { id: 'orders',    label: 'Orders',    icon: <List size={11} />,    count: orders.length },
    { id: 'journal',   label: 'Journal',   icon: <BookOpen size={11} /> },
  ]

  return (
    <div
      style={{
        height: collapsed ? MIN_H : height,
        flexShrink: 0,
        borderTop: '1px solid var(--color-divider)',
        background: 'var(--color-surface)',
        display: 'flex', flexDirection: 'column',
        transition: collapsed ? 'height 150ms ease' : undefined,
      }}
    >
      {/* ── Drag handle ── */}
      <div className="resize-handle" onMouseDown={onMouseDown} />

      {/* ── Tab bar ── */}
      <div
        className="flex items-center shrink-0"
        style={{
          height: 32, paddingInline: 8,
          borderBottom: collapsed ? 'none' : '1px solid var(--color-divider)',
          gap: 4,
        }}
      >
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => { setTab(t.id); setCollapsed(false) }}
            className="flex items-center gap-1.5"
            style={{
              padding: '3px 8px', borderRadius: 'var(--radius-sm)',
              fontSize: 11, fontWeight: t.id === tab ? 600 : 400,
              color: t.id === tab ? 'var(--color-primary)' : 'var(--color-muted)',
              background: t.id === tab ? 'var(--color-primary-dim)' : 'transparent',
              border: 'none', cursor: 'pointer', transition: 'all var(--transition)',
            }}
          >
            {t.icon}
            {t.label}
            {(t.count ?? 0) > 0 && (
              <span
                style={{
                  background: t.id === tab ? 'var(--color-primary)' : 'var(--color-surface3)',
                  color: t.id === tab ? '#fff' : 'var(--color-muted)',
                  fontSize: 9, fontWeight: 700, padding: '1px 5px',
                  borderRadius: 10, minWidth: 16, textAlign: 'center',
                }}
              >{t.count}</span>
            )}
          </button>
        ))}

        <div style={{ flex: 1 }} />

        <button
          onClick={() => setCollapsed(v => !v)}
          className="btn btn-ghost btn-sm"
          data-tooltip={collapsed ? 'Expand' : 'Collapse'}
        >
          {collapsed ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
      </div>

      {/* ── Content ── */}
      {!collapsed && (
        <div className="flex-1 overflow-auto">
          {tab === 'positions' && (
            <table className="positions-table" style={{ width: '100%' }}>
              <thead>
                <tr>
                  {['Symbol','Side','Qty','Entry','Current','PnL','SL','TP1','Status',''].map(h => (
                    <th key={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.length === 0 && (
                  <tr>
                    <td colSpan={10} style={{ textAlign: 'center', padding: '20px 0', color: 'var(--color-muted)', fontSize: 12 }}>
                      No open positions
                    </td>
                  </tr>
                )}
                {positions.map(p => <PositionRow key={p.id} position={p} onClose={refreshPos} />)}
              </tbody>
            </table>
          )}

          {tab === 'orders' && (
            <table className="positions-table" style={{ width: '100%' }}>
              <thead>
                <tr>
                  {['Time','Symbol','Type','Side','Qty','Price','Status','ID'].map(h => <th key={h}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {orders.length === 0 && (
                  <tr>
                    <td colSpan={8} style={{ textAlign: 'center', padding: '20px 0', color: 'var(--color-muted)', fontSize: 12 }}>
                      No orders
                    </td>
                  </tr>
                )}
                {orders.map(o => (
                  <tr key={o.id} className="anim-fade-in">
                    <td className="mono" style={{ fontSize: 11, color: 'var(--color-muted)' }}>
                      {new Date(o.created_at).toLocaleTimeString()}
                    </td>
                    <td className="mono" style={{ fontWeight: 600 }}>{o.symbol}</td>
                    <td style={{ color: 'var(--color-muted)' }}>{o.order_type}</td>
                    <td>
                      <span className={o.side === 'BUY' ? 'badge badge-buy' : 'badge badge-sell'}>{o.side}</span>
                    </td>
                    <td className="mono">{o.quantity}</td>
                    <td className="mono">{o.price ?? '—'}</td>
                    <td>
                      <span style={{
                        fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
                        color: o.status === 'FILLED' ? 'var(--color-success)'
                          : o.status === 'REJECTED' ? 'var(--color-error)'
                          : o.status === 'DRY_RUN'  ? 'var(--color-primary)'
                          : 'var(--color-muted)',
                      }}>{o.status}</span>
                    </td>
                    <td className="mono" style={{ fontSize: 10, color: 'var(--color-faint)' }}>
                      {o.client_order_id?.slice(-8)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {tab === 'journal' && (
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--color-muted)', fontSize: 12 }}>
              <BookOpen size={28} style={{ margin: '0 auto 10px', color: 'var(--color-faint)' }} />
              <div>Trade journal — coming soon</div>
              <div style={{ fontSize: 11, color: 'var(--color-faint)', marginTop: 4 }}>CSV export available at <code>/api/v1/journal</code></div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
