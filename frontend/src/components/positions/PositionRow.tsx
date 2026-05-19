'use client'
import { useState } from 'react'
import { apiFetch } from '@/lib/config'
import { X, TrendingUp, TrendingDown } from 'lucide-react'

interface Position {
  id: string
  symbol: string
  side: 'BUY' | 'SELL'
  quantity: number
  entry_price: number
  current_price?: number
  unrealized_pnl?: number
  stop_loss: number
  take_profit_1: number
  tp1_hit?: boolean
  breakeven_set?: boolean
  is_dry_run?: boolean
}

export function PositionRow({ position: p, onClose }: { position: Position; onClose?: () => void }) {
  const [closing, setClosing] = useState(false)

  const pnl = p.unrealized_pnl ?? 0
  const pnlColor = pnl > 0 ? 'var(--color-success)' : pnl < 0 ? 'var(--color-error)' : 'var(--color-muted)'
  const pnlSign  = pnl > 0 ? '+' : ''

  const handleClose = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(`Close ${p.symbol} position?`)) return
    setClosing(true)
    try {
      await apiFetch(`/close_position/${p.id}`, { method: 'POST' })
      onClose?.()
    } catch (err) { console.error(err) }
    finally { setClosing(false) }
  }

  return (
    <tr className="anim-fade-in">
      <td>
        <div className="flex items-center gap-1.5">
          <span className="mono" style={{ fontWeight: 600 }}>{p.symbol}</span>
          {p.is_dry_run && <span className="badge badge-primary" style={{ fontSize: 8 }}>DRY</span>}
        </div>
      </td>
      <td>
        <span className={p.side === 'BUY' ? 'badge badge-buy' : 'badge badge-sell'}>
          {p.side === 'BUY' ? <TrendingUp size={9} /> : <TrendingDown size={9} />}
          {p.side}
        </span>
      </td>
      <td className="mono">{p.quantity}</td>
      <td className="mono">{p.entry_price.toFixed(2)}</td>
      <td className="mono" style={{ color: 'var(--color-muted)' }}>
        {p.current_price ? p.current_price.toFixed(2) : '—'}
      </td>
      <td className="mono" style={{ color: pnlColor, fontWeight: 600 }}>
        {pnlSign}{pnl.toFixed(2)}
      </td>
      <td className="mono" style={{ color: 'var(--color-error)' }}>{p.stop_loss.toFixed(2)}</td>
      <td className="mono" style={{ color: 'var(--color-success)' }}>
        <span>{p.take_profit_1.toFixed(2)}</span>
        {p.tp1_hit && <span className="badge badge-buy" style={{ marginLeft: 4, fontSize: 8 }}>HIT</span>}
      </td>
      <td>
        {p.breakeven_set
          ? <span className="badge" style={{ background: 'var(--color-gold-dim)', color: 'var(--color-gold)', fontSize: 9 }}>BE</span>
          : <span style={{ fontSize: 10, color: 'var(--color-muted)' }}>OPEN</span>}
      </td>
      <td>
        <button
          className="btn btn-sm btn-danger"
          onClick={handleClose}
          disabled={closing}
          style={{ padding: '2px 6px' }}
        >
          {closing ? '…' : <X size={10} />}
        </button>
      </td>
    </tr>
  )
}
