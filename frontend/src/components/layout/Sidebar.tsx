'use client'
import { useState } from 'react'
import { useSignals } from '@/hooks/useSignals'
import { useMetrics } from '@/hooks/useMetrics'
import { useWS } from '@/hooks/useWS'
import { SignalCard } from '@/components/signals/SignalCard'
import { MetricsPanel } from '@/components/metrics/MetricsPanel'
import clsx from 'clsx'

type Tab = 'signals' | 'metrics'

export function Sidebar() {
  const [tab, setTab] = useState<Tab>('signals')
  const { signals, isLoading, refresh } = useSignals(30)
  const { metrics } = useMetrics()

  // Refresh signals on new signal via WS
  useWS('signal_created',  () => refresh())
  useWS('signal_rejected', () => refresh())
  useWS('order_filled',    () => refresh())

  return (
    <div className="flex flex-col w-64 shrink-0 bg-surface border-r border-divider overflow-hidden">
      {/* Tab bar */}
      <div className="flex border-b border-divider">
        {(['signals', 'metrics'] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              'flex-1 py-2 text-xs font-medium capitalize transition-colors',
              t === tab ? 'text-primary border-b-2 border-primary' : 'text-muted hover:text-text'
            )}
          >{t}</button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {tab === 'signals' && (
          <div className="p-2 space-y-2">
            {isLoading && (
              Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-20 rounded bg-surface2 animate-pulse" />
              ))
            )}
            {!isLoading && signals.length === 0 && (
              <div className="flex flex-col items-center py-12 text-muted text-xs">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" className="mb-3 text-faint">
                  <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.5"/>
                  <path d="M12 8v4M12 16h.01" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                </svg>
                <span>No signals yet</span>
                <span className="text-faint mt-1">Waiting for strategy output</span>
              </div>
            )}
            {signals.map(s => (
              <SignalCard key={s.id} signal={s} />
            ))}
          </div>
        )}
        {tab === 'metrics' && (
          <MetricsPanel metrics={metrics ?? null} />
        )}
      </div>
    </div>
  )
}
