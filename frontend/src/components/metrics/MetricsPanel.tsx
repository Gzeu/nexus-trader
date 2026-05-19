'use client'
import type { Metrics } from '@/hooks/useMetrics'
import clsx from 'clsx'

interface Props { metrics: Metrics | null }

function MetricRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex justify-between items-center py-1.5 border-b border-divider last:border-0">
      <span className="text-muted text-xs">{label}</span>
      <span className={clsx('text-xs font-medium tabular', color ?? 'text-text')}>{value}</span>
    </div>
  )
}

export function MetricsPanel({ metrics }: Props) {
  if (!metrics) {
    return (
      <div className="p-4 space-y-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="h-6 rounded bg-surface2 animate-pulse" />
        ))}
      </div>
    )
  }

  const m = metrics
  const pnlColor = (m.total_pnl ?? 0) >= 0 ? 'text-success' : 'text-error'
  const dailyColor = (m.daily_pnl ?? 0) >= 0 ? 'text-success' : 'text-error'
  const ddColor = (m.max_drawdown ?? 0) > 0.08 ? 'text-error' : (m.max_drawdown ?? 0) > 0.04 ? 'text-warning' : 'text-success'

  return (
    <div className="p-3">
      <p className="text-2xs text-faint uppercase tracking-wider mb-3">Performance</p>
      <MetricRow label="Equity"          value={`$${m.equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}`} />
      <MetricRow label="Total P&L"       value={`${(m.total_pnl ?? 0) >= 0 ? '+' : ''}${(m.total_pnl ?? 0).toFixed(2)} USDT`} color={pnlColor} />
      <MetricRow label="Daily P&L"       value={`${(m.daily_pnl ?? 0) >= 0 ? '+' : ''}${(m.daily_pnl ?? 0).toFixed(2)} USDT`} color={dailyColor} />
      <MetricRow label="Unrealized P&L"  value={`${(m.unrealized_pnl ?? 0) >= 0 ? '+' : ''}${(m.unrealized_pnl ?? 0).toFixed(2)}`} />

      <p className="text-2xs text-faint uppercase tracking-wider mt-4 mb-3">Stats</p>
      <MetricRow label="Win Rate"        value={`${((m.win_rate ?? 0) * 100).toFixed(1)}%`}  color={(m.win_rate ?? 0) >= 0.5 ? 'text-success' : 'text-warning'} />
      <MetricRow label="Profit Factor"   value={(m.profit_factor ?? 0).toFixed(2)}          color={(m.profit_factor ?? 0) >= 1.5 ? 'text-success' : 'text-warning'} />
      <MetricRow label="Sharpe Ratio"    value={(m.sharpe_ratio ?? 0).toFixed(2)}           color={(m.sharpe_ratio ?? 0) >= 1 ? 'text-success' : 'text-muted'} />
      <MetricRow label="Expectancy"      value={`${(m.expectancy ?? 0).toFixed(2)} USDT`} />
      <MetricRow label="Max Drawdown"    value={`${((m.max_drawdown ?? 0) * 100).toFixed(2)}%`} color={ddColor} />
      <MetricRow label="Total Trades"    value={String(m.total_trades)} />
      <MetricRow label="Open Positions"  value={String(m.open_positions)} />
      <MetricRow label="Consec. Losses"  value={String(m.consecutive_losses)} color={m.consecutive_losses >= 3 ? 'text-warning' : 'text-text'} />
    </div>
  )
}
