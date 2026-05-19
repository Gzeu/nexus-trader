'use client'
import { useEffect, useState, useCallback } from 'react'
import { useWS } from '@/hooks/useWS'
import { CheckCircle, AlertTriangle, XCircle, Info, X } from 'lucide-react'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id: string
  type: ToastType
  title: string
  message?: string
  duration?: number
}

let _addToast: ((t: Omit<Toast, 'id'>) => void) | null = null

export function addToast(t: Omit<Toast, 'id'>) {
  _addToast?.(t)
}

const ICONS = {
  success: <CheckCircle size={14} style={{ color: 'var(--color-success)', flexShrink: 0 }} />,
  error:   <XCircle     size={14} style={{ color: 'var(--color-error)',   flexShrink: 0 }} />,
  warning: <AlertTriangle size={14} style={{ color: 'var(--color-warning)', flexShrink: 0 }} />,
  info:    <Info        size={14} style={{ color: 'var(--color-primary)', flexShrink: 0 }} />,
}

function ToastItem({ toast, onRemove }: { toast: Toast; onRemove: (id: string) => void }) {
  useEffect(() => {
    const t = setTimeout(() => onRemove(toast.id), toast.duration ?? 4500)
    return () => clearTimeout(t)
  }, [toast.id, toast.duration, onRemove])

  return (
    <div className={`toast toast-${toast.type}`}>
      {ICONS[toast.type]}
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text)' }}>{toast.title}</div>
        {toast.message && (
          <div style={{ fontSize: 11, color: 'var(--color-muted)', marginTop: 2 }}>{toast.message}</div>
        )}
      </div>
      <button
        onClick={() => onRemove(toast.id)}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-muted)', padding: 2 }}
      >
        <X size={12} />
      </button>
    </div>
  )
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([])

  const add = useCallback((t: Omit<Toast, 'id'>) => {
    const id = Math.random().toString(36).slice(2)
    setToasts(prev => [...prev.slice(-4), { ...t, id }])
  }, [])

  const remove = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  // Register global handler
  useEffect(() => { _addToast = add; return () => { _addToast = null } }, [add])

  // WS-driven toasts
  useWS('order_filled',    useCallback((p: any) => add({ type: 'success', title: 'Order filled', message: `${p?.symbol} ${p?.side} @ ${p?.avg_fill_price ?? 'market'}` }), [add]))
  useWS('signal_rejected', useCallback((p: any) => add({ type: 'warning', title: 'Signal rejected', message: p?.veto ?? '' }), [add]))
  useWS('risk_event',      useCallback((p: any) => {
    if (p?.severity === 'CRITICAL')
      add({ type: 'error', title: '⚡ Risk Event', message: p?.detail ?? '', duration: 8000 })
    else
      add({ type: 'warning', title: 'Risk Warning', message: p?.detail ?? '' })
  }, [add]))
  useWS('position_closed', useCallback((p: any) => add({ type: 'info', title: 'Position closed', message: `${p?.symbol} — ${p?.exit_reason ?? 'closed'}` }), [add]))

  if (toasts.length === 0) return null

  return (
    <div
      style={{
        position: 'fixed', bottom: 16, right: 16,
        zIndex: 9999, display: 'flex', flexDirection: 'column',
        gap: 8, pointerEvents: 'none',
      }}
    >
      {toasts.map(t => (
        <ToastItem key={t.id} toast={t} onRemove={remove} />
      ))}
    </div>
  )
}
