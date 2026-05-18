'use client'
import type { Signal } from '@/hooks/useSignals'
import clsx from 'clsx'
import { TrendingUp, TrendingDown, Minus, AlertCircle } from 'lucide-react'

const ACTION_STYLES: Record<string, { color: string; bg: string; icon: React.ReactNode }> = {
  BUY:     { color: 'text-long',    bg: 'bg-long/10',    icon: <TrendingUp  size={12} /> },
  SELL:    { color: 'text-short',   bg: 'bg-short/10',   icon: <TrendingDown size={12} /> },
  HOLD:    { color: 'text-muted',   bg: 'bg-surface2',   icon: <Minus size={12} /> },
  CLOSE:   { color: 'text-warning', bg: 'bg-warning/10', icon: <Minus size={12} /> },
  REVERSE: { color: 'text-gold',    bg: 'bg-gold/10',    icon: <TrendingDown size={12} /> },
}

const STATUS_COLOR: Record<string, string> = {
  EXECUTED: 'text-success',
  REJECTED: 'text-error',
  PENDING:  'text-gold',
  EXPIRED:  'text-faint',
}

export function SignalCard({ signal }: { signal: Signal }) {
  const style = ACTION_STYLES[signal.action] ?? ACTION_STYLES.HOLD
  const confidence = Math.round(signal.confidence * 100)

  return (
    <div className="p-2.5 rounded bg-surface2 border border-border/50 text-xs space-y-1.5 hover:border-border transition-colors">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className={clsx('flex items-center gap-1 font-semibold px-1.5 py-0.5 rounded', style.color, style.bg)}>
            {style.icon}{signal.action}
          </span>
          <span className="font-mono font-semibold text-text">{signal.symbol}</span>
        </div>
        <span className={clsx('text-2xs font-medium', STATUS_COLOR[signal.status] ?? 'text-muted')}>
          {signal.status}
        </span>
      </div>

      {/* Confidence bar */}
      <div className="flex items-center gap-2">
        <div className="flex-1 h-1 rounded-full bg-surface overflow-hidden">
          <div
            className={clsx('h-full rounded-full transition-all', confidence >= 75 ? 'bg-success' : confidence >= 60 ? 'bg-gold' : 'bg-warning')}
            style={{ width: `${confidence}%` }}
          />
        </div>
        <span className="text-muted tabular">{confidence}%</span>
      </div>

      {/* Prices */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-2xs tabular">
        <span className="text-faint">Entry</span>
        <span className="text-text text-right">{signal.entry_price?.toFixed(2) ?? '—'}</span>
        <span className="text-faint">SL</span>
        <span className="text-error text-right">{signal.stop_loss?.toFixed(2) ?? '—'}</span>
        <span className="text-faint">TP1</span>
        <span className="text-success text-right">{signal.take_profit_1?.toFixed(2) ?? '—'}</span>
      </div>

      {/* Reason + veto */}
      {signal.veto_reason && (
        <div className="flex items-center gap-1 text-error text-2xs">
          <AlertCircle size={10} />{signal.veto_reason}
        </div>
      )}

      {/* Time + TF */}
      <div className="flex justify-between text-faint text-2xs">
        <span>{signal.timeframe}</span>
        <span>{new Date(signal.created_at).toLocaleTimeString()}</span>
      </div>
    </div>
  )
}
