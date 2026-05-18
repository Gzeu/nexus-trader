'use client'

import dynamic from 'next/dynamic'
import { Suspense } from 'react'
import { Header } from '@/components/layout/Header'
import { Sidebar } from '@/components/layout/Sidebar'
import { BottomPanel } from '@/components/layout/BottomPanel'
import { StatusBar } from '@/components/layout/StatusBar'
import { ChartSkeleton } from '@/components/chart/ChartSkeleton'

// TradingView chart must be client-only (no SSR)
const TradingChart = dynamic(
  () => import('@/components/chart/TradingChart'),
  { ssr: false, loading: () => <ChartSkeleton /> }
)

export default function TradingTerminal() {
  return (
    <div className="flex flex-col h-screen overflow-hidden bg-bg">
      {/* Top status bar — connection + equity + mode */}
      <StatusBar />

      {/* Main header — symbol selector, timeframe, mode toggle */}
      <Header />

      {/* Main content area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar — signals feed + risk controls */}
        <Sidebar />

        {/* Chart + bottom panel */}
        <div className="flex flex-col flex-1 overflow-hidden">
          <div className="flex-1 overflow-hidden">
            <Suspense fallback={<ChartSkeleton />}>
              <TradingChart />
            </Suspense>
          </div>

          {/* Bottom panel — positions, orders, journal */}
          <BottomPanel />
        </div>
      </div>
    </div>
  )
}
