'use client'
import { useState, useRef, useEffect } from 'react'
import { ChevronDown, BarChart2, PanelLeft, Keyboard, RefreshCw, Settings } from 'lucide-react'
import { useRouter } from 'next/navigation'
import clsx from 'clsx'

const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT', 'XRPUSDT', 'DOGEUSDT', 'AVAXUSDT']
const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '4h', '1d']

interface HeaderProps {
  symbol?: string
  timeframe?: string
  onSymbolChange?: (s: string) => void
  onTimeframeChange?: (t: string) => void
  sidebarOpen?: boolean
  onToggleSidebar?: () => void
  onShowShortcuts?: () => void
}

export function Header({
  symbol = 'BTCUSDT',
  timeframe = '15m',
  onSymbolChange,
  onTimeframeChange,
  sidebarOpen = true,
  onToggleSidebar,
  onShowShortcuts,
}: HeaderProps) {
  const [showSymbols, setShowSymbols] = useState(false)
  const [search, setSearch] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const router = useRouter()

  const filtered = SYMBOLS.filter(s => s.toLowerCase().includes(search.toLowerCase()))

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node))
        setShowSymbols(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleRefresh = async () => {
    setRefreshing(true)
    await new Promise(r => setTimeout(r, 800))
    setRefreshing(false)
    window.location.reload()
  }

  return (
    <div
      className="flex items-center gap-2 px-3"
      style={{
        height: 42,
        background: 'var(--color-surface)',
        borderBottom: '1px solid var(--color-divider)',
        flexShrink: 0,
      }}
    >
      {/* ── Sidebar toggle ── */}
      <button
        onClick={onToggleSidebar}
        className={clsx(
          'btn btn-ghost btn-sm',
          !sidebarOpen && 'opacity-50'
        )}
        data-tooltip="Toggle sidebar (B)"
        aria-label="Toggle sidebar"
      >
        <PanelLeft size={14} />
      </button>

      {/* ── Logo ── */}
      <div className="flex items-center gap-1.5 px-2 mr-1" style={{ borderRight: '1px solid var(--color-divider)', paddingRight: 12 }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-label="Nexus Trader">
          <polygon points="12,2 22,19 2,19" stroke="var(--color-primary)" strokeWidth="2" fill="none" strokeLinejoin="round"/>
          <line x1="12" y1="8" x2="12" y2="14" stroke="var(--color-primary)" strokeWidth="2" strokeLinecap="round"/>
          <circle cx="12" cy="17" r="1" fill="var(--color-primary)"/>
        </svg>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text)', letterSpacing: '-0.02em' }}>Nexus</span>
      </div>

      {/* ── Symbol selector ── */}
      <div className="relative" ref={dropdownRef}>
        <button
          onClick={() => { setShowSymbols(v => !v); setSearch('') }}
          className="flex items-center gap-1.5 btn btn-ghost"
          style={{ fontWeight: 600, minWidth: 110, justifyContent: 'space-between' }}
        >
          <span className="flex items-center gap-1.5">
            <BarChart2 size={12} style={{ color: 'var(--color-primary)' }} />
            <span className="mono" style={{ fontSize: 13 }}>{symbol}</span>
          </span>
          <ChevronDown size={11} style={{ color: 'var(--color-muted)' }} />
        </button>

        {showSymbols && (
          <div
            className="absolute top-full left-0 mt-1 z-50 anim-slide-up"
            style={{
              background: 'var(--color-surface2)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-lg)',
              boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
              minWidth: 160,
              overflow: 'hidden',
            }}
          >
            <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--color-divider)' }}>
              <input
                autoFocus
                className="input"
                style={{ padding: '4px 8px', fontSize: 12 }}
                placeholder="Search..."
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>
            {filtered.map(s => (
              <button
                key={s}
                onClick={() => { onSymbolChange?.(s); setShowSymbols(false) }}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  width: '100%', padding: '7px 12px', fontSize: 12, textAlign: 'left',
                  background: s === symbol ? 'var(--color-primary-dim)' : 'transparent',
                  color: s === symbol ? 'var(--color-primary)' : 'var(--color-text)',
                  fontWeight: s === symbol ? 600 : 400,
                  transition: 'background var(--transition)',
                  cursor: 'pointer', border: 'none', fontFamily: 'var(--font-mono)',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = s === symbol ? 'var(--color-primary-dim)' : 'var(--color-surface3)')}
                onMouseLeave={e => (e.currentTarget.style.background = s === symbol ? 'var(--color-primary-dim)' : 'transparent')}
              >
                <span>{s}</span>
                {s === symbol && <span style={{ fontSize: 10, color: 'var(--color-primary)' }}>●</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Timeframe selector ── */}
      <div className="flex items-center gap-0.5">
        {TIMEFRAMES.map(tf => (
          <button
            key={tf}
            onClick={() => onTimeframeChange?.(tf)}
            style={{
              padding: '3px 7px', borderRadius: 'var(--radius-sm)',
              fontSize: 11, fontWeight: tf === timeframe ? 600 : 400,
              background: tf === timeframe ? 'var(--color-primary)' : 'transparent',
              color: tf === timeframe ? '#fff' : 'var(--color-muted)',
              transition: 'all var(--transition)', cursor: 'pointer', border: 'none',
              fontFamily: 'var(--font-mono)',
            }}
            onMouseEnter={e => { if (tf !== timeframe) { e.currentTarget.style.background = 'var(--color-surface3)'; e.currentTarget.style.color = 'var(--color-text)' } }}
            onMouseLeave={e => { if (tf !== timeframe) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--color-muted)' } }}
          >{tf}</button>
        ))}
      </div>

      {/* ── Spacer ── */}
      <div className="flex-1" />

      {/* ── Right actions ── */}
      <div className="flex items-center gap-1">
        <button
          className="btn btn-ghost btn-sm"
          onClick={handleRefresh}
          data-tooltip="Reload page"
          aria-label="Reload"
        >
          <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
        </button>
        <button
          className="btn btn-ghost btn-sm"
          onClick={onShowShortcuts}
          data-tooltip="Keyboard shortcuts (?)"
          aria-label="Shortcuts"
        >
          <Keyboard size={12} />
        </button>
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => router.push('/settings')}
          data-tooltip="Settings"
          aria-label="Settings"
        >
          <Settings size={12} />
        </button>
      </div>
    </div>
  )
}
