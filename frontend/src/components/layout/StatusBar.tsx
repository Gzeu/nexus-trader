'use client'
import { useHealth } from '@/hooks/useHealth'
import { useWS } from '@/hooks/useWS'
import { useState, useCallback } from 'react'
import { apiFetch } from '@/lib/config'
import { AlertTriangle, Wifi, WifiOff, Zap, ZapOff } from 'lucide-react'
import clsx from 'clsx'

export function StatusBar() {
  const { health, connected } = useHealth()
  const [wsConnected, setWsConnected] = useState(false)

  useWS('connected',    useCallback(() => setWsConnected(true),  []))
  useWS('disconnected', useCallback(() => setWsConnected(false), []))

  const handleEmergencyStop = async () => {
    if (!confirm('⚠️ Activate Emergency Stop? All automation will pause.')) return
    try {
      await apiFetch('/emergency_stop', { method: 'POST' })
    } catch (e) { console.error(e) }
  }

  const equity  = health?.equity  ?? 0
  const dailyPnl = health?.daily_pnl ?? 0
  const pnlColor = dailyPnl >= 0 ? 'text-success' : 'text-error'

  return (
    <div className="flex items-center justify-between px-4 py-1.5 bg-surface border-b border-divider text-xs tabular">
      {/* Left: connection status */}
      <div className="flex items-center gap-4">
        {/* API */}
        <div className={clsx('flex items-center gap-1.5', connected ? 'text-success' : 'text-error')}>
          {connected
            ? <><Wifi size={12} /><span>API</span><span className="pulse-dot">●</span></>
            : <><WifiOff size={12} /><span className="text-error">API OFF</span></>}
        </div>
        {/* WS */}
        <div className={clsx('flex items-center gap-1.5', wsConnected ? 'text-success' : 'text-muted')}>
          {wsConnected
            ? <><Zap size={12} /><span>WS</span></>
            : <><ZapOff size={12} /><span>WS</span></>}
        </div>
        {/* Reconciled */}
        {health && !health.reconciled && (
          <div className="flex items-center gap-1 text-warning">
            <AlertTriangle size={12} /><span>NOT RECONCILED</span>
          </div>
        )}
        {/* Paused */}
        {health?.paused && (
          <div className="flex items-center gap-1 text-warning">
            <AlertTriangle size={12} /><span>TRADING PAUSED</span>
          </div>
        )}
      </div>

      {/* Center: equity + daily P&L */}
      <div className="flex items-center gap-6">
        <span className="text-muted">Equity</span>
        <span className="text-text font-medium">${equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        <span className="text-muted">Daily P&L</span>
        <span className={pnlColor}>{dailyPnl >= 0 ? '+' : ''}{dailyPnl.toFixed(2)} USDT</span>
      </div>

      {/* Right: mode badges + emergency stop */}
      <div className="flex items-center gap-3">
        {health?.testnet && (
          <span className="px-2 py-0.5 rounded bg-gold/20 text-gold text-2xs font-semibold tracking-wider">TESTNET</span>
        )}
        {health?.dry_run && (
          <span className="px-2 py-0.5 rounded bg-primary/20 text-primary text-2xs font-semibold tracking-wider">DRY RUN</span>
        )}
        <span className="px-2 py-0.5 rounded bg-surface2 text-muted text-2xs font-semibold tracking-wider">
          {health?.market_mode ?? 'SPOT'}
        </span>
        <button
          onClick={handleEmergencyStop}
          className="px-2.5 py-1 rounded bg-error/10 text-error text-2xs font-semibold border border-error/30 hover:bg-error/20 transition-colors"
        >
          ⚡ STOP
        </button>
      </div>
    </div>
  )
}
