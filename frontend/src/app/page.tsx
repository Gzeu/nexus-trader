'use client'

import { useState, useEffect, useCallback } from 'react'
import dynamic from 'next/dynamic'
import { Suspense } from 'react'
import { Header } from '@/components/layout/Header'
import { Sidebar } from '@/components/layout/Sidebar'
import { BottomPanel } from '@/components/layout/BottomPanel'
import { StatusBar } from '@/components/layout/StatusBar'
import { ChartSkeleton } from '@/components/chart/ChartSkeleton'
import { ToastContainer } from '@/components/ui/ToastContainer'
import { KeyboardShortcuts } from '@/components/ui/KeyboardShortcuts'

const TradingChart = dynamic(
  () => import('@/components/chart/TradingChart'),
  { ssr: false, loading: () => <ChartSkeleton /> }
)

export default function TradingTerminal() {
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [timeframe, setTimeframe] = useState('15m')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [showShortcuts, setShowShortcuts] = useState(false)

  // Global keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return
      switch (e.key) {
        case '?': setShowShortcuts(v => !v); break
        case 'b': case 'B': setSidebarOpen(v => !v); break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return (
    <div className="flex flex-col h-screen overflow-hidden" style={{ background: 'var(--color-bg)' }}>
      {/* Toast notifications overlay */}
      <ToastContainer />

      {/* Keyboard shortcuts modal */}
      {showShortcuts && <KeyboardShortcuts onClose={() => setShowShortcuts(false)} />}

      {/* Top status bar */}
      <StatusBar />

      {/* Main header */}
      <Header
        symbol={symbol}
        timeframe={timeframe}
        onSymbolChange={setSymbol}
        onTimeframeChange={setTimeframe}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen(v => !v)}
        onShowShortcuts={() => setShowShortcuts(true)}
      />

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar with transition */}
        <div
          className="shrink-0 transition-all duration-200 overflow-hidden"
          style={{
            width: sidebarOpen ? 272 : 0,
            borderRight: sidebarOpen ? '1px solid var(--color-divider)' : 'none',
          }}
        >
          {sidebarOpen && <Sidebar />}
        </div>

        {/* Chart + bottom panel */}
        <div className="flex flex-col flex-1 overflow-hidden">
          <div className="flex-1 overflow-hidden">
            <Suspense fallback={<ChartSkeleton />}>
              <TradingChart symbol={symbol} timeframe={timeframe} />
            </Suspense>
          </div>
          <BottomPanel />
        </div>
      </div>
    </div>
  )
}
