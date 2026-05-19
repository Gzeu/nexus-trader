'use client'

import type { StrategySignal } from '@/types'
import { fmt } from '@/lib/format'

const ACTION_STYLE: Record<string, string> = {
  BUY:     'badge-profit',
  SELL:    'badge-loss',
  HOLD:    'badge-neutral',
  CLOSE:   'badge-warning',
  REVERSE: 'badge-error',
}

export function SignalRow({ signal: s }: { signal: StrategySignal }) {
  const conf = s.confidence
  const confColor = conf >= 0.75 ? 'var(--color-profit)' : conf >= 0.5 ? 'var(--color-warning)' : 'var(--color-loss)'

  return (
    <tr>
      <td style={{ fontWeight:600, fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)' }}>{s.symbol}</td>
      <td><span className={`badge ${ACTION_STYLE[s.action] ?? 'badge-neutral'}`}>{s.action}</span></td>
      <td>
        <div style={{ display:'flex', alignItems:'center', gap:'var(--space-2)' }}>
          <div className="progress-track" style={{ width:48 }}>
            <div className="progress-fill" style={{ width:`${conf*100}%`, background:confColor }} />
          </div>
          <span style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)', color:confColor }}>
            {fmt.confidence(conf)}
          </span>
        </div>
      </td>
      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)' }}>
        {s.entry_price ? fmt.price(s.entry_price) : 'MKT'}
      </td>
      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)', color:'var(--color-loss)' }}>{fmt.price(s.stop_loss)}</td>
      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)', color:'var(--color-profit)' }}>{fmt.price(s.take_profit_1)}</td>
      <td style={{ fontFamily:'var(--font-mono)', fontSize:'var(--text-xs)', fontWeight:600 }}>
        {s.rr_ratio ? `${s.rr_ratio}:1` : '—'}
      </td>
      <td><span className="badge badge-neutral">{s.timeframe}</span></td>
      <td style={{ fontSize:'var(--text-xs)', color:'var(--color-text-muted)', maxWidth:200, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
        {s.reason}
      </td>
    </tr>
  )
}
