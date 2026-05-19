'use client'
import { X } from 'lucide-react'
import { useEffect } from 'react'

const SHORTCUTS = [
  { key: 'B', desc: 'Toggle sidebar' },
  { key: '?', desc: 'Show this help' },
  { key: 'Esc', desc: 'Close modals' },
  { key: '1–8', desc: 'Select timeframe (1m → 1d)' },
]

export function KeyboardShortcuts({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9000,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        className="anim-slide-up"
        style={{
          background: 'var(--color-surface2)', border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-lg)', padding: '20px 24px',
          minWidth: 320, boxShadow: '0 12px 40px rgba(0,0,0,0.6)',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text)' }}>Keyboard shortcuts</span>
          <button onClick={onClose} className="btn btn-ghost btn-sm"><X size={13} /></button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {SHORTCUTS.map(s => (
            <div key={s.key} className="flex items-center justify-between">
              <span style={{ fontSize: 12, color: 'var(--color-muted)' }}>{s.desc}</span>
              <kbd>{s.key}</kbd>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
