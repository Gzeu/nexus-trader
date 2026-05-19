'use client'
import { useRef, useEffect } from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

interface Metrics {
  total_trades?: number
  win_rate?: number
  profit_factor?: number
  sharpe_ratio?: number
  expectancy?: number
  max_drawdown?: number
  current_drawdown?: number
  daily_pnl?: number
  consecutive_losses?: number
  equity_curve?: number[]
  is_paused?: boolean
  pause_reason?: string
}

function KPI({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div
      className="card anim-count"
      style={{ padding: '8px 10px', marginBottom: 0 }}
    >
      <div style={{ fontSize: 9, color: 'var(--color-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>
        {label}
      </div>
      <div className="mono" style={{ fontSize: 16, fontWeight: 600, color: color ?? 'var(--color-text)' }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 10, color: 'var(--color-muted)', marginTop: 1 }}>{sub}</div>}
    </div>
  )
}

function EquityCurve({ data }: { data: number[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || data.length < 2) return
    const ctx = canvas.getContext('2d')!
    const W = canvas.offsetWidth
    const H = canvas.offsetHeight
    canvas.width  = W * devicePixelRatio
    canvas.height = H * devicePixelRatio
    ctx.scale(devicePixelRatio, devicePixelRatio)

    const min = Math.min(...data)
    const max = Math.max(...data)
    const range = max - min || 1
    const pad = { t: 8, b: 8, l: 4, r: 4 }
    const iW = W - pad.l - pad.r
    const iH = H - pad.t - pad.b

    const x = (i: number) => pad.l + (i / (data.length - 1)) * iW
    const y = (v: number) => pad.t + (1 - (v - min) / range) * iH

    // Zero line
    if (min < data[0] && max > data[0]) {
      ctx.beginPath()
      ctx.setLineDash([3, 3])
      ctx.strokeStyle = 'rgba(79,152,163,0.2)'
      ctx.lineWidth = 1
      ctx.moveTo(pad.l, y(data[0]))
      ctx.lineTo(W - pad.r, y(data[0]))
      ctx.stroke()
      ctx.setLineDash([])
    }

    // Gradient fill
    const isUp = data[data.length - 1] >= data[0]
    const grad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b)
    if (isUp) {
      grad.addColorStop(0,   'rgba(93,170,110,0.25)')
      grad.addColorStop(1,   'rgba(93,170,110,0)')
    } else {
      grad.addColorStop(0,   'rgba(209,80,80,0.25)')
      grad.addColorStop(1,   'rgba(209,80,80,0)')
    }

    ctx.beginPath()
    ctx.moveTo(x(0), y(data[0]))
    data.forEach((v, i) => { if (i > 0) ctx.lineTo(x(i), y(v)) })
    ctx.lineTo(x(data.length - 1), H - pad.b)
    ctx.lineTo(x(0), H - pad.b)
    ctx.closePath()
    ctx.fillStyle = grad
    ctx.fill()

    // Line
    ctx.beginPath()
    ctx.moveTo(x(0), y(data[0]))
    data.forEach((v, i) => { if (i > 0) ctx.lineTo(x(i), y(v)) })
    ctx.strokeStyle = isUp ? 'var(--color-success)' : 'var(--color-error)'
    ctx.lineWidth = 1.5
    ctx.stroke()

    // Last dot
    const lx = x(data.length - 1)
    const ly = y(data[data.length - 1])
    ctx.beginPath()
    ctx.arc(lx, ly, 3, 0, Math.PI * 2)
    ctx.fillStyle = isUp ? 'var(--color-success)' : 'var(--color-error)'
    ctx.fill()
  }, [data])

  return (
    <div style={{ padding: '0 8px 8px' }}>
      <div style={{ fontSize: 9, color: 'var(--color-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6, paddingTop: 8 }}>
        Equity curve
      </div>
      <canvas
        ref={canvasRef}
        className="equity-canvas"
        style={{ height: 72 }}
      />
    </div>
  )
}

export function MetricsPanel({ metrics }: { metrics: Metrics | null }) {
  if (!metrics) {
    return (
      <div style={{ padding: 16 }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="skeleton" style={{ height: 52, marginBottom: 6 }} />
        ))}
      </div>
    )
  }

  const wr    = ((metrics.win_rate ?? 0) * 100).toFixed(1)
  const pf    = (metrics.profit_factor ?? 0).toFixed(2)
  const sh    = (metrics.sharpe_ratio ?? 0).toFixed(2)
  const exp   = (metrics.expectancy ?? 0).toFixed(2)
  const dd    = ((metrics.max_drawdown ?? 0) * 100).toFixed(1)
  const cdd   = ((metrics.current_drawdown ?? 0) * 100).toFixed(1)
  const dpnl  = metrics.daily_pnl ?? 0
  const cl    = metrics.consecutive_losses ?? 0

  const wrColor = (metrics.win_rate ?? 0) >= 0.5 ? 'var(--color-success)' : 'var(--color-error)'
  const pfColor = (metrics.profit_factor ?? 0) >= 1 ? 'var(--color-success)' : 'var(--color-error)'
  const shColor = (metrics.sharpe_ratio ?? 0) >= 0 ? 'var(--color-primary)' : 'var(--color-error)'
  const dpnlColor = dpnl >= 0 ? 'var(--color-success)' : 'var(--color-error)'

  return (
    <div style={{ padding: 8 }}>
      {/* Risk banner if paused */}
      {metrics.is_paused && (
        <div
          style={{
            margin: '0 0 8px', padding: '6px 10px', borderRadius: 'var(--radius-md)',
            background: 'var(--color-warning-dim)', border: '1px solid rgba(201,135,58,0.4)',
            fontSize: 11, color: 'var(--color-warning)', fontWeight: 600,
          }}
        >
          ⏸ PAUSED — {metrics.pause_reason ?? 'Risk limit reached'}
        </div>
      )}

      {/* KPI grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 6 }}>
        <KPI label="Win Rate"  value={`${wr}%`}  color={wrColor} />
        <KPI label="P. Factor" value={pf}         color={pfColor} />
        <KPI label="Sharpe"    value={sh}         color={shColor} />
        <KPI label="Expectancy" value={`$${exp}`} />
        <KPI label="Max DD"    value={`${dd}%`}   color='var(--color-error)' sub={`Current: ${cdd}%`} />
        <KPI label="Daily PnL" value={`${dpnl >= 0 ? '+' : ''}${dpnl.toFixed(2)}`} color={dpnlColor} sub={`${metrics.total_trades ?? 0} trades`} />
      </div>

      {/* Consecutive losses warning */}
      {cl > 0 && (
        <div
          style={{
            margin: '0 0 8px', padding: '5px 10px', borderRadius: 'var(--radius-sm)',
            background: cl >= 2 ? 'var(--color-error-dim)' : 'var(--color-surface3)',
            border: `1px solid ${cl >= 2 ? 'rgba(209,80,80,0.3)' : 'var(--color-border)'}`,
            fontSize: 11, color: cl >= 2 ? 'var(--color-error)' : 'var(--color-muted)',
          }}
        >
          {cl >= 2 ? '⚠ ' : ''}{cl} consecutive loss{cl !== 1 ? 'es' : ''}
        </div>
      )}

      {/* Equity curve */}
      {(metrics.equity_curve?.length ?? 0) > 2 && (
        <EquityCurve data={metrics.equity_curve!} />
      )}
    </div>
  )
}
