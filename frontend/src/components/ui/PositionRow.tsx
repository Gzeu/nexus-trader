'use client'

import type { Position } from '@/types'
import { fmt } from '@/lib/format'

export function PositionRow({ position: p }: { position: Position }) {
  const pnlColor = p.unrealized_pnl >= 0 ? 'var(--color-profit)' : 'var(--color-loss)'

  return (
    <tr>
      <td>
        <div style={{ fontWeight:600, fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)' }}>{p.symbol}</div>
        {p.is_dry_run && <span className="badge badge-neutral" style={{marginTop:2}}>dry</span>}
      </td>
      <td>
        <span className={`badge ${p.side === 'BUY' ? 'badge-profit' : 'badge-loss'}`}>{p.side}</span>
      </td>
      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)' }}>{fmt.qty(p.quantity)}</td>
      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)' }}>{fmt.price(p.entry_price)}</td>
      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)' }}>{p.current_price > 0 ? fmt.price(p.current_price) : '—'}</td>
      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)', color: pnlColor, fontWeight:600 }}>
        {fmt.pnl(p.unrealized_pnl)}
      </td>
      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)', color:'var(--color-loss)' }}>{fmt.price(p.stop_loss)}</td>
      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)', color:'var(--color-profit)' }}>
        {fmt.price(p.take_profit_1)}
        {p.tp1_hit && <span className="badge badge-profit" style={{marginLeft:4}}>✓</span>}
      </td>
      <td>
        <div style={{ display:'flex', gap:'var(--space-1)' }}>
          {p.tp1_hit && !p.tp2_hit && <span className="badge badge-primary">BE</span>}
          {p.breakeven_set && <span className="badge badge-neutral">BE✓</span>}
        </div>
      </td>
    </tr>
  )
}
