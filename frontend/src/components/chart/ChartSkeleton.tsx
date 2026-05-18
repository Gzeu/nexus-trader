export function ChartSkeleton() {
  return (
    <div className="w-full h-full bg-surface flex items-center justify-center">
      <div className="flex flex-col items-center gap-3 text-muted">
        <div className="flex gap-1 items-end h-8">
          {[3,5,4,7,6,8,5,9,7,6,8,10,7].map((h, i) => (
            <div
              key={i}
              className="w-2 bg-primary/30 rounded-sm animate-pulse"
              style={{ height: `${h * 4}px`, animationDelay: `${i * 80}ms` }}
            />
          ))}
        </div>
        <span className="text-xs">Loading chart...</span>
      </div>
    </div>
  )
}
