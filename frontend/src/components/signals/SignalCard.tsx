'use client'
import { useState } from 'react'
import { ChevronDown, ChevronRight, TrendingUp, TrendingDown, Minus } from 'lucide-react'

interface Signal {
  id: string
  symbol: string
  action: 'BUY' | 'SELL' | 'HOLD' | 'CLOSE' | 'REVERSE'
  confidence: number
  entry_type: string
  entry_price: number | null
  stop_loss: number
  take_profit_1: number
  take_profit_2: number
  timeframe: string
  reason: string
  created_at: string
  rr_ratio?: number | null
}

const ACTION_CONFIG: Record<string, { badge: string; icon: React.ReactNode; border: string }> = {
  BUY:     { badge: 'badge badge-buy',   icon: <TrendingUp  size={10} />, border: 'rgba(93,170,110,0.3)' },
  SELL:    { badge: 'badge badge-sell',  icon: <TrendingDown size={10} />, border: 'rgba(209,80,80,0.3)' },
  HOLD:    { badge: 'badge badge-hold',  icon: <Minus size={10} />, border: 'var(--color-border)' },
  CLOSE:   { badge: 'badge badge-close', icon: <Minus size={10} />, border: 'rgba(201,135,58,0.3)' },
  REVERSE: { badge: 'badge badge-primary', icon: <TrendingUp size={10} />, border: 'rgba(79,152,163,0.3)' },
}

export function SignalCard({ signal }: { signal: Signal }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = ACTION_CONFIG[signal.action] ?? ACTION_CONFIG.HOLD
  const conf = Math.round(signal.confidence * 100)
  const confColor = conf >= 75 ? 'var(--color-success)'
    : conf >= 50 ? 'var(--color-warning)'
    : 'var(--color-error)'
  const time = new Date(signal.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

  return (
    <div
      className="signal-card"
      style={{ borderColor: cfg.border, cursor: 'pointer' }}
      onClick={() => setExpanded(v => !v)}
    >
      {/* ── Header row ── */}
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5">
          <span className={cfg.badge}>{cfg.icon}{signal.action}</span>
          <span className="mono" style={{ fontSize: 12, fontWeight: 600 }}>{signal.symbol}</span>
          <span style={{ fontSize: 10, color: 'var(--color-muted)' }}>{signal.timeframe}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="mono" style={{ fontSize: 10, color: 'var(--color-muted)' }}>{time}</span>
          {expanded ? <ChevronDown size={10} style={{ color: 'var(--color-muted)' }} />
                    : <ChevronRight size={10} style={{ color: 'var(--color-muted)' }} />}
        </div>
      </div>

      {/* ── Confidence bar ── */}
      <div className="flex items-center gap-1.5 mb-1.5">
        <div className="conf-bar-track" style={{ flex: 1 }}>
          <div
            className="conf-bar-fill"
            style={{ width: `${conf}%`, background: confColor }}
          />
        </div>
        <span className="mono" style={{ fontSize: 10, color: confColor, minWidth: 28, textAlign: 'right' }}>
          {conf}%
        </span>
      </div>

      {/* ── Price row ── */}
      <div className="flex items-center gap-2">
        <span style={{ fontSize: 11 }}>
          <span style={{ color: 'var(--color-muted)' }}>@ </span>
          <span className="mono">{signal.entry_price != null ? signal.entry_price.toFixed(2) : 'MKT'}</span>
        </span>
        {signal.rr_ratio != null && (
          <span
            className="badge"
            style={{
              background: 'var(--color-surface3)',
              color: signal.rr_ratio >= 2 ? 'var(--color-success)' : signal.rr_ratio >= 1.5 ? 'var(--color-warning)' : 'var(--color-error)',
              fontSize: 9,
            }}
          >
            RR {signal.rr_ratio.toFixed(1)}
          </span>
        )}
      </div>

      {/* ── Expanded details ── */}
      {expanded && (
        <div
          className="anim-slide-up"
          style={{
            marginTop: 8, paddingTop: 8,
            borderTop: '1px solid var(--color-divider)',
            display: 'flex', flexDirection: 'column', gap: 3,
          }}
        >
          {[
            ['SL', signal.stop_loss?.toFixed(2)],
            ['TP1', signal.take_profit_1?.toFixed(2)],
            ['TP2', signal.take_profit_2?.toFixed(2)],
          ].map(([k, v]) => v && (
            <div key={k} className="flex items-center justify-between">
              <span style={{ fontSize: 10, color: 'var(--color-muted)' }}>{k}</span>
              <span className="mono" style={{ fontSize: 11 }}>{v}</span>
            </div>
          ))}
          {signal.reason && (
            <div style={{ fontSize: 10, color: 'var(--color-muted)', marginTop: 3 }}>
              {signal.reason}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
