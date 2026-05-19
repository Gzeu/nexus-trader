'use client'

interface Props {
  label: string
  value: string
  change?: number
  loading?: boolean
  highlight?: boolean
}

export function StatCard({ label, value, change, loading, highlight }: Props) {
  const isPositive = change !== undefined && change >= 0
  const isNegative = change !== undefined && change < 0

  return (
    <div className="card" style={{
      borderColor: highlight ? 'var(--color-primary-border)' : undefined,
      background:  highlight ? 'var(--color-primary-dim)'   : undefined,
    }}>
      <div className="stat-label">{label}</div>
      {loading
        ? <div className="skeleton" style={{ height:'2rem', marginTop:'var(--space-2)', borderRadius:'var(--radius-sm)' }} />
        : <div className="stat-value" style={{ marginTop:'var(--space-2)', color: isPositive ? 'var(--color-profit)' : isNegative ? 'var(--color-loss)' : undefined }}>
            {value}
          </div>
      }
      {change !== undefined && !loading && (
        <div className={`stat-change ${isPositive ? 'up' : 'down'}`}>
          {isPositive ? '▲' : '▼'} {Math.abs(change).toFixed(2)}
        </div>
      )}
    </div>
  )
}
