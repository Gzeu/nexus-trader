'use client'

import { DashboardShell } from '@/components/layout/DashboardShell'
import { useState, useEffect } from 'react'

export default function SettingsPage() {
  const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'
  const [health, setHealth] = useState<Record<string,unknown>|null>(null)

  useEffect(() => {
    fetch(`${BASE}/health`).then(r=>r.json()).then(setHealth).catch(()=>{})
  }, [])

  return (
    <DashboardShell>
      <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-6)', maxWidth:640 }}>
        <div>
          <h1 style={{ fontSize:'var(--text-lg)', fontWeight:700 }}>Settings</h1>
          <p style={{ color:'var(--color-text-muted)', fontSize:'var(--text-sm)', marginTop:'var(--space-1)' }}>
            Configure backend connection and UI preferences.
          </p>
        </div>

        {/* Backend connection */}
        <section className="card">
          <div style={{ fontWeight:600, fontSize:'var(--text-sm)', marginBottom:'var(--space-4)' }}>Backend Connection</div>
          <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-3)' }}>
            <div>
              <label className="form-label">API URL</label>
              <input className="form-input" defaultValue={BASE} readOnly />
            </div>
            <div>
              <label className="form-label">WebSocket URL</label>
              <input className="form-input" defaultValue={process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws'} readOnly />
            </div>
          </div>
        </section>

        {/* System info */}
        {health && (
          <section className="card">
            <div style={{ fontWeight:600, fontSize:'var(--text-sm)', marginBottom:'var(--space-4)' }}>System Info</div>
            <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-2)' }}>
              {Object.entries(health).map(([k,v]) => (
                <div key={k} style={{ display:'flex', justifyContent:'space-between', padding:'var(--space-2) var(--space-3)', background:'var(--color-surface-3)', borderRadius:'var(--radius-md)' }}>
                  <span style={{ fontSize:'var(--text-xs)', color:'var(--color-text-muted)' }}>{k}</span>
                  <span style={{ fontSize:'var(--text-xs)', fontFamily:'var(--font-mono)', fontWeight:500 }}>{String(v)}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* .env guide */}
        <section className="card">
          <div style={{ fontWeight:600, fontSize:'var(--text-sm)', marginBottom:'var(--space-3)' }}>Configuration (.env)</div>
          <p style={{ fontSize:'var(--text-xs)', color:'var(--color-text-muted)', marginBottom:'var(--space-3)' }}>
            All backend settings are controlled via the <code style={{fontFamily:'var(--font-mono)',background:'var(--color-surface-3)',padding:'0 4px',borderRadius:'var(--radius-sm)'}}>backend/.env</code> file. Restart the backend after changes.
          </p>
          <div style={{ display:'flex', flexDirection:'column', gap:'var(--space-2)' }}>
            {[
              ['DRY_RUN',     'true/false — simulate orders without sending to exchange'],
              ['TESTNET',     'true/false — use Binance Testnet'],
              ['MARKET_MODE', 'spot / futures'],
              ['SYMBOLS',     'comma-separated list, e.g. BTCUSDT,ETHUSDT'],
              ['RISK_PER_TRADE', '0.01 = 1% equity per trade'],
              ['MAX_DRAWDOWN', '0.12 = 12% → emergency stop'],
              ['MAX_DAILY_LOSS', '0.03 = 3% → auto-pause'],
            ].map(([k,d]) => (
              <div key={k} style={{ padding:'var(--space-2) var(--space-3)', background:'var(--color-surface-3)', borderRadius:'var(--radius-md)', borderLeft:'2px solid var(--color-primary)' }}>
                <code style={{ fontSize:'var(--text-xs)', fontFamily:'var(--font-mono)', color:'var(--color-primary)', fontWeight:600 }}>{k}</code>
                <p style={{ fontSize:'var(--text-xs)', color:'var(--color-text-muted)', marginTop:2, maxWidth:'100%' }}>{d}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </DashboardShell>
  )
}
