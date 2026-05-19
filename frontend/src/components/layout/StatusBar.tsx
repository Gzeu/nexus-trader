'use client'
import { useHealth } from '@/hooks/useHealth'
import { useWS } from '@/hooks/useWS'
import { useState, useCallback } from 'react'
import { apiFetch } from '@/lib/config'
import { Wifi, WifiOff, Zap, ZapOff, AlertTriangle, PauseCircle } from 'lucide-react'
import clsx from 'clsx'

function AnimatedNumber({ value, prefix = '', suffix = '', decimals = 2 }: {
  value: number; prefix?: string; suffix?: string; decimals?: number
}) {
  return (
    <span className="tabular mono text-xs anim-count">
      {prefix}{value.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}{suffix}
    </span>
  )
}

export function StatusBar() {
  const { health, connected } = useHealth()
  const [wsConnected, setWsConnected] = useState(false)
  const [stopping, setStopping] = useState(false)

  useWS('connected',    useCallback(() => setWsConnected(true),  []))
  useWS('disconnected', useCallback(() => setWsConnected(false), []))

  const handleEmergencyStop = async () => {
    if (!confirm('⚡ EMERGENCY STOP — pause all automation and cancel pending orders?')) return
    setStopping(true)
    try {
      await apiFetch('/emergency_stop', { method: 'POST' })
    } catch (e) { console.error(e) } finally { setStopping(false) }
  }

  const equity   = health?.equity    ?? 0
  const dailyPnl = health?.daily_pnl ?? 0
  const pnlPos   = dailyPnl >= 0

  return (
    <div
      className="flex items-center justify-between px-3 tabular"
      style={{
        height: 32,
        background: 'var(--color-surface)',
        borderBottom: '1px solid var(--color-divider)',
        fontSize: 11,
      }}
    >
      {/* ── Left: connection status ── */}
      <div className="flex items-center gap-3">
        {/* API */}
        <div className={clsx('flex items-center gap-1', connected ? 'text-success' : 'text-error')}>
          {connected
            ? <><Wifi size={11} /><span>API</span><span className="pulse-live" style={{ fontSize: 7 }}>●</span></>
            : <><WifiOff size={11} /><span style={{ color: 'var(--color-error)' }}>API OFF</span></>}
        </div>
        {/* WS */}
        <div className={clsx('flex items-center gap-1', wsConnected ? 'text-success' : 'text-muted')}>
          {wsConnected
            ? <><Zap size={11} /><span>WS</span><span className="pulse-live" style={{ fontSize: 7 }}>●</span></>
            : <><ZapOff size={11} /><span style={{ color: 'var(--color-muted)' }}>WS</span></>}
        </div>
        {/* Warnings */}
        {health && !health.reconciled && (
          <div className="flex items-center gap-1" style={{ color: 'var(--color-warning)' }}>
            <AlertTriangle size={11} /><span>RECONCILING</span>
          </div>
        )}
        {health?.paused && (
          <div className="flex items-center gap-1" style={{ color: 'var(--color-gold)' }}>
            <PauseCircle size={11} /><span>PAUSED</span>
          </div>
        )}
      </div>

      {/* ── Center: equity + PnL ── */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-1.5">
          <span style={{ color: 'var(--color-muted)' }}>EQ</span>
          <AnimatedNumber value={equity} prefix="$" />
        </div>
        <div
          className="flex items-center gap-1"
          style={{ color: pnlPos ? 'var(--color-success)' : 'var(--color-error)' }}
        >
          <span style={{ color: 'var(--color-muted)', marginRight: 2 }}>D-PnL</span>
          <span className={pnlPos ? 'glow-green' : 'glow-red'}>
            {pnlPos ? '+' : ''}<AnimatedNumber value={dailyPnl} suffix=" USDT" />
          </span>
        </div>
        {(health?.open_positions ?? 0) > 0 && (
          <div className="flex items-center gap-1">
            <span style={{ color: 'var(--color-muted)' }}>POS</span>
            <span style={{ color: 'var(--color-primary)', fontWeight: 600 }}>{health!.open_positions}</span>
          </div>
        )}
      </div>

      {/* ── Right: badges + kill switch ── */}
      <div className="flex items-center gap-2">
        {health?.testnet && <span className="badge badge-gold">TESTNET</span>}
        {health?.dry_run && <span className="badge badge-primary">DRY RUN</span>}
        <span className="badge" style={{ background: 'var(--color-surface3)', color: 'var(--color-muted)' }}>
          {(health?.market_mode ?? 'SPOT').toUpperCase()}
        </span>
        <button
          onClick={handleEmergencyStop}
          disabled={stopping}
          className="btn btn-sm btn-danger"
          data-tooltip="Emergency stop — pause all automation"
        >
          {stopping ? '…' : '⚡'} STOP
        </button>
      </div>
    </div>
  )
}
