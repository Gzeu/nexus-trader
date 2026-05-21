'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { AICopilot } from '@/components/AICopilot'

const NAV = [
  { href: '/',          label: 'Overview',   icon: GridIcon },
  { href: '/positions', label: 'Positions',  icon: TrendIcon },
  { href: '/signals',   label: 'Signals',    icon: BoltIcon },
  { href: '/journal',   label: 'Journal',    icon: BookIcon },
  { href: '/risk',      label: 'Risk',       icon: ShieldIcon },
  { href: '/settings',  label: 'Settings',   icon: CogIcon },
]

// Latimea panoului AI — ajustabila
const AI_PANEL_WIDTH = 320

export function DashboardShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')
  const [aiOpen, setAiOpen] = useState(false)

  useEffect(() => {
    const saved = (localStorage.getItem('nt-theme') ?? 'dark') as 'dark' | 'light'
    setTheme(saved)
    document.documentElement.setAttribute('data-theme', saved)
  }, [])

  function toggleTheme() {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    document.documentElement.setAttribute('data-theme', next)
    localStorage.setItem('nt-theme', next)
  }

  return (
    <div className="dashboard-shell" style={{
      // Adauga coloana AI la dreapta cand panelul e deschis
      gridTemplateColumns: aiOpen
        ? `var(--sidebar-width) 1fr ${AI_PANEL_WIDTH}px`
        : 'var(--sidebar-width) 1fr',
    }}>
      {/* ── Sidebar ──────────────────────────────────────────────────────────────────── */}
      <aside className="dashboard-sidebar" style={{
        background: 'var(--color-surface)',
        borderRight: '1px solid var(--color-border)',
        display: 'flex', flexDirection: 'column',
        position: 'sticky', top: 0, height: '100dvh',
        overflow: 'hidden',
      }}>
        {/* Logo */}
        <div style={{ padding: 'var(--space-4) var(--space-5)', borderBottom: '1px solid var(--color-border)', display:'flex', alignItems:'center', gap:'var(--space-3)', height:'var(--header-height)' }}>
          <NexusLogo />
          <div>
            <div style={{ fontWeight: 700, fontSize: 'var(--text-sm)', lineHeight: 1.2, letterSpacing: '-0.01em' }}>NEXUS</div>
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-faint)', letterSpacing: '0.08em' }}>TRADER</div>
          </div>
        </div>

        {/* Nav */}
        <nav style={{ flex: 1, padding: 'var(--space-3) var(--space-2)', display:'flex', flexDirection:'column', gap:'var(--space-1)' }}>
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href
            return (
              <Link key={href} href={href} style={{
                display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
                padding: 'var(--space-2) var(--space-3)',
                borderRadius: 'var(--radius-md)',
                fontSize: 'var(--text-sm)',
                fontWeight: active ? 600 : 400,
                color: active ? 'var(--color-primary)' : 'var(--color-text-muted)',
                background: active ? 'var(--color-primary-dim)' : 'transparent',
                border: active ? '1px solid var(--color-primary-border)' : '1px solid transparent',
                textDecoration: 'none',
                transition: 'all var(--t-fast)',
              }}>
                <Icon size={16} />
                {label}
              </Link>
            )
          })}
        </nav>

        {/* Bottom: AI toggle + theme toggle */}
        <div style={{ padding: 'var(--space-4)', borderTop: '1px solid var(--color-border)', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          {/* AI Copilot toggle button */}
          <button
            onClick={() => setAiOpen(o => !o)}
            className="btn btn-ghost btn-sm"
            style={{
              width: '100%',
              justifyContent: 'flex-start',
              color: aiOpen ? 'var(--color-primary)' : undefined,
              background: aiOpen ? 'var(--color-primary-dim)' : undefined,
              border: aiOpen ? '1px solid var(--color-primary-border)' : '1px solid transparent',
            }}
          >
            <SparkleIcon size={14} />
            AI Copilot
            {aiOpen && (
              <span style={{ marginLeft: 'auto', fontSize: 'var(--text-xs)', color: 'var(--color-primary)', background: 'var(--color-primary-dim)', padding: '1px 6px', borderRadius: 'var(--radius-full)' }}>ON</span>
            )}
          </button>

          <button onClick={toggleTheme} className="btn btn-ghost btn-sm" style={{ width: '100%', justifyContent: 'flex-start' }}>
            {theme === 'dark' ? <SunIcon size={14} /> : <MoonIcon size={14} />}
            {theme === 'dark' ? 'Light mode' : 'Dark mode'}
          </button>
        </div>
      </aside>

      {/* ── Header ───────────────────────────────────────────────────────────────────── */}
      <header className="dashboard-header" style={{
        background: 'var(--color-surface)',
        borderBottom: '1px solid var(--color-border)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 var(--space-6)',
        position: 'sticky', top: 0, zIndex: 30,
      }}>
        <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)', fontWeight: 500 }}>
          {NAV.find(n => n.href === pathname)?.label ?? 'Dashboard'}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
          <StatusPill />
        </div>
      </header>

      {/* ── Main ────────────────────────────────────────────────────────────────────────── */}
      <main className="dashboard-main" style={{ padding: 'var(--space-6)' }}>
        <div className="animate-fade-up">{children}</div>
      </main>

      {/* ── AI Copilot Panel ─────────────────────────────────────────────────────────────── */}
      {aiOpen && (
        <aside
          className="dashboard-ai-panel"
          style={{
            gridRow: '1 / -1',     // ocupa toata inaltimea (header + main)
            gridColumn: '3',
            height: '100dvh',
            position: 'sticky',
            top: 0,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <AICopilot onClose={() => setAiOpen(false)} />
        </aside>
      )}
    </div>
  )
}

// ─── Status pill (connects to health endpoint) ─────────────────────────────────────────

function StatusPill() {
  const [status, setStatus] = useState<'live'|'paused'|'offline'>('offline')
  useEffect(() => {
    const check = async () => {
      try {
        const r = await fetch((process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1') + '/health')
        if (!r.ok) { setStatus('offline'); return }
        const d = await r.json()
        setStatus(d.is_paused ? 'paused' : 'live')
      } catch { setStatus('offline') }
    }
    check()
    const id = setInterval(check, 5000)
    return () => clearInterval(id)
  }, [])
  const label = { live: 'Live', paused: 'Paused', offline: 'Offline' }[status]
  return (
    <div style={{ display:'flex', alignItems:'center', gap:'var(--space-2)', padding:'var(--space-1) var(--space-3)', background:'var(--color-surface-3)', borderRadius:'var(--radius-full)', border:'1px solid var(--color-border)' }}>
      <span className={`status-dot ${status}`} />
      <span style={{ fontSize:'var(--text-xs)', fontWeight:500, color:'var(--color-text-muted)' }}>{label}</span>
    </div>
  )
}

// ─── Inline SVG Icons ──────────────────────────────────────────────────────────────────────────

function Icon({ d, size=16 }: { d: string, size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d={d}/></svg>
}
function GridIcon(p: {size?:number})   { return <svg width={p.size??16} height={p.size??16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg> }
function TrendIcon(p: {size?:number})  { return <Icon d="M3 17l6-6 4 4 8-8" size={p.size} /> }
function BoltIcon(p: {size?:number})   { return <Icon d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" size={p.size} /> }
function BookIcon(p: {size?:number})   { return <Icon d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" size={p.size} /> }
function ShieldIcon(p: {size?:number}) { return <Icon d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" size={p.size} /> }
function CogIcon(p: {size?:number})    { return <svg width={p.size??16} height={p.size??16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg> }
function SunIcon(p: {size?:number})    { return <svg width={p.size??16} height={p.size??16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg> }
function MoonIcon(p: {size?:number})   { return <Icon d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" size={p.size} /> }
function SparkleIcon(p: {size?:number}) {
  return (
    <svg width={p.size??16} height={p.size??16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2L14.5 9.5L22 12L14.5 14.5L12 22L9.5 14.5L2 12L9.5 9.5L12 2Z" />
    </svg>
  )
}

function NexusLogo() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-label="Nexus Trader">
      <rect width="32" height="32" rx="8" fill="currentColor" style={{color:'var(--color-primary-dim)'}}/>
      <path d="M8 22 L14 10 L16 15 L18 10 L24 22" stroke="var(--color-primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
      <circle cx="16" cy="15" r="2" fill="var(--color-primary)"/>
    </svg>
  )
}
