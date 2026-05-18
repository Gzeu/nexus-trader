'use client'
import { useState } from 'react'
import { ChevronDown, BarChart2 } from 'lucide-react'
import clsx from 'clsx'

const SYMBOLS   = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT', 'XRPUSDT']
const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '4h', '1d']

interface HeaderProps {
  symbol?: string
  timeframe?: string
  onSymbolChange?: (s: string) => void
  onTimeframeChange?: (t: string) => void
}

export function Header({
  symbol = 'BTCUSDT',
  timeframe = '15m',
  onSymbolChange,
  onTimeframeChange,
}: HeaderProps) {
  const [showSymbols, setShowSymbols] = useState(false)

  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-surface border-b border-divider">
      {/* Logo */}
      <div className="flex items-center gap-2 mr-2">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-label="Nexus Trader">
          <polygon points="12,2 22,19 2,19" stroke="#4f98a3" strokeWidth="2" fill="none" strokeLinejoin="round"/>
          <line x1="12" y1="8" x2="12" y2="14" stroke="#4f98a3" strokeWidth="2" strokeLinecap="round"/>
          <circle cx="12" cy="17" r="1" fill="#4f98a3"/>
        </svg>
        <span className="text-sm font-semibold text-text tracking-tight">Nexus</span>
      </div>

      {/* Symbol selector */}
      <div className="relative">
        <button
          onClick={() => setShowSymbols(v => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-surface2 border border-border text-sm font-semibold text-text hover:border-primary/50 transition-colors"
        >
          <BarChart2 size={14} className="text-primary" />
          {symbol}
          <ChevronDown size={12} className="text-muted" />
        </button>
        {showSymbols && (
          <div className="absolute top-full left-0 mt-1 z-50 bg-surface2 border border-border rounded shadow-lg min-w-[140px]">
            {SYMBOLS.map(s => (
              <button
                key={s}
                onClick={() => { onSymbolChange?.(s); setShowSymbols(false) }}
                className={clsx(
                  'w-full text-left px-3 py-2 text-sm hover:bg-surface transition-colors',
                  s === symbol ? 'text-primary font-semibold' : 'text-text'
                )}
              >{s}</button>
            ))}
          </div>
        )}
      </div>

      {/* Timeframe selector */}
      <div className="flex items-center gap-1">
        {TIMEFRAMES.map(tf => (
          <button
            key={tf}
            onClick={() => onTimeframeChange?.(tf)}
            className={clsx(
              'px-2.5 py-1 rounded text-xs font-medium transition-colors',
              tf === timeframe
                ? 'bg-primary text-bg'
                : 'text-muted hover:text-text hover:bg-surface2'
            )}
          >{tf}</button>
        ))}
      </div>
    </div>
  )
}
