export function ChartSkeleton() {
  return (
    <div
      style={{
        width: '100%', height: '100%',
        background: 'var(--color-surface)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexDirection: 'column', gap: 12,
      }}
    >
      {/* Animated candlestick bars */}
      <svg width="120" height="60" viewBox="0 0 120 60">
        {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => {
          const x = 8 + i * 15
          const h = [20, 32, 18, 40, 28, 35, 22, 30][i]
          const up = i % 3 !== 1
          return (
            <g key={i} style={{ opacity: 0.4 + i * 0.07 }}>
              <line x1={x} y1="5" x2={x} y2="55" stroke="var(--color-border)" strokeWidth="1" />
              <rect
                x={x - 4}
                y={(60 - h) / 2}
                width={8}
                height={h}
                rx={1}
                fill={up ? 'var(--color-success)' : 'var(--color-error)'}
                opacity={0.6}
              />
            </g>
          )
        })}
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
        <div className="skeleton" style={{ width: 120, height: 10 }} />
        <div className="skeleton" style={{ width: 80, height: 8, opacity: 0.6 }} />
      </div>
    </div>
  )
}
