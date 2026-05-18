'use client'
import type { Position } from '@/hooks/usePositions'
import { apiFetch } from '@/lib/config'
import clsx from 'clsx'
import { X } from 'lucide-react'

interface Props {
  position: Position
  onClose?: () => void
}

export function PositionRow({ position: p, onClose }: Props) {
  const pnlColor = p.unrealized_pnl >= 0 ? 'text-success' : 'text-error'
  const sideColor = p.side === 'LONG' ? 'text-long' : 'text-short'

  const handleClose = async () => {
    if (!confirm(`Close ${p.symbol} ${p.side} position?`)) return
    try {
      await apiFetch('/signals/webhook', {
        method: 'POST',
        body: JSON.stringify({
          secret: process.env.NEXT_PUBLIC_API_KEY,
          symbol: p.symbol,
          action: 'CLOSE',
          stop_loss: 0,
          take_profit_1: 0,
          take_profit_2: 0,
          confidence: 1.0,
          reason: 'Manual close from UI',
        }),
      })
      setTimeout(() => onClose?.(), 500)
    } catch (e) { console.error(e) }
  }

  return (
    <tr className="border-b border-divider/50 hover:bg-surface2/50 transition-colors">
      <td className="px-3 py-2 font-mono font-medium text-text">{p.symbol}</td>
      <td className={clsx('px-3 py-2 font-semibold', sideColor)}>{p.side}</td>
      <td className="px-3 py-2 text-text">{p.quantity.toFixed(6)}</td>
      <td className="px-3 py-2">{p.entry_price.toFixed(2)}</td>
      <td className="px-3 py-2">{p.current_price.toFixed(2)}</td>
      <td className={clsx('px-3 py-2 font-medium', pnlColor)}>
        {p.unrealized_pnl >= 0 ? '+' : ''}{p.unrealized_pnl.toFixed(2)}
      </td>
      <td className="px-3 py-2 text-error">{p.stop_loss.toFixed(2)}</td>
      <td className="px-3 py-2 text-success">{p.take_profit_1.toFixed(2)}</td>
      <td className="px-3 py-2 text-muted">{new Date(p.opened_at).toLocaleTimeString()}</td>
      <td className="px-3 py-2">
        <button
          onClick={handleClose}
          className="p-1 rounded hover:bg-error/20 text-muted hover:text-error transition-colors"
          title="Close position"
        >
          <X size={12} />
        </button>
      </td>
    </tr>
  )
}
