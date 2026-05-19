'use client'
import { useState } from 'react'
import { useSignals } from '@/hooks/useSignals'
import { useMetrics } from '@/hooks/useMetrics'
import { useWS } from '@/hooks/useWS'
import { SignalCard } from '@/components/signals/SignalCard'
import { MetricsPanel } from '@/components/metrics/MetricsPanel'
import { TrendingUp, Activity, RefreshCw } from 'lucide-react'
import clsx from 'clsx'

type Tab = 'signals' | 'metrics'

export function Sidebar() {
  const [tab, setTab] = useState<Tab>('signals')
  const { signals, isLoading, refresh } = useSignals(30)
  const { metrics } = useMetrics()
  const [newCount, setNewCount] = useState(0)

  useWS('signal_created',  () => { refresh(); if (tab !== 'signals') setNewCount(v => v + 1) })
  useWS('signal_rejected', () => refresh())
  useWS('order_filled',    () => refresh())

  const handleTabChange = (t: Tab) => {
    setTab(t)
    if (t === 'signals') setNewCount(0)
  }

  return (
    <div
      className="flex flex-col overflow-hidden"
      style={{ width: 272, height: '100%', background: 'var(--color-surface)' }}
    >
      {/* ── Tab bar ── */}
      <div
        className="flex shrink-0"
        style={{ borderBottom: '1px solid var(--color-divider)', height: 34 }}
      >
        <button
          onClick={() => handleTabChange('signals')}
          className={clsx(
            'flex-1 flex items-center justify-center gap-1.5',
            'text-xs font-medium transition-colors relative',
            tab === 'signals' ? 'text-primary' : 'text-muted hover:text-text'
          )}
          style={{
            borderBottom: tab === 'signals' ? '2px solid var(--color-primary)' : '2px solid transparent',
            cursor: 'pointer', border: 'none', background: 'transparent',
            borderBottomWidth: 2,
          }}
        >
          <Activity size={11} />
          Signals
          {newCount > 0 && (
            <span
              className="anim-count"
              style={{
                background: 'var(--color-primary)', color: '#fff',
                fontSize: 9, fontWeight: 700, padding: '1px 5px',
                borderRadius: 10, minWidth: 16, textAlign: 'center',
              }}
            >{newCount}</span>
          )}
        </button>
        <button
          onClick={() => handleTabChange('metrics')}
          className={clsx(
            'flex-1 flex items-center justify-center gap-1.5',
            'text-xs font-medium transition-colors',
            tab === 'metrics' ? 'text-primary' : 'text-muted hover:text-text'
          )}
          style={{
            borderBottom: tab === 'metrics' ? '2px solid var(--color-primary)' : '2px solid transparent',
            cursor: 'pointer', border: 'none', background: 'transparent',
            borderBottomWidth: 2,
          }}
        >
          <TrendingUp size={11} />
          Metrics
        </button>
      </div>

      {/* ── Content ── */}
      <div className="flex-1 overflow-y-auto">
        {tab === 'signals' && (
          <div style={{ padding: '8px 8px' }}>
            {/* Refresh row */}
            <div className="flex items-center justify-between mb-2">
              <span style={{ fontSize: 10, color: 'var(--color-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Recent signals
              </span>
              <button
                onClick={refresh}
                className="btn btn-ghost btn-sm"
                style={{ padding: '2px 6px' }}
                data-tooltip="Refresh"
              >
                <RefreshCw size={10} />
              </button>
            </div>

            {isLoading && (
              <div className="space-y-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="skeleton" style={{ height: 72 }} />
                ))}
              </div>
            )}

            {!isLoading && signals.length === 0 && (
              <div
                className="flex flex-col items-center"
                style={{ padding: '40px 16px', textAlign: 'center', color: 'var(--color-muted)' }}
              >
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" style={{ marginBottom: 12, color: 'var(--color-faint)' }}>
                  <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.5"/>
                  <path d="M8.5 12.5l2.5 2.5 4.5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                <div style={{ fontSize: 12, marginBottom: 4 }}>No signals yet</div>
                <div style={{ fontSize: 11, color: 'var(--color-faint)' }}>Waiting for strategy output</div>
              </div>
            )}

            <div className="space-y-1.5">
              {signals.map(s => (
                <SignalCard key={s.id} signal={s} />
              ))}
            </div>
          </div>
        )}

        {tab === 'metrics' && <MetricsPanel metrics={metrics ?? null} />}
      </div>
    </div>
  )
}
