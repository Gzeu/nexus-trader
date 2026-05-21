'use client'

import { useEffect, useRef, useState } from 'react'
import { useAI } from '@/hooks/useAI'
import type { AIAction, AIMessage } from '@/types/ai'

// ─── Inline SVG icons ────────────────────────────────────────────────────────────────────

function SendIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  )
}

function StopIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <rect x="4" y="4" width="16" height="16" rx="2" />
    </svg>
  )
}

function SparkleIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2L14.5 9.5L22 12L14.5 14.5L12 22L9.5 14.5L2 12L9.5 9.5L12 2Z" />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14H6L5 6" />
      <path d="M10 11v6M14 11v6" />
      <path d="M9 6V4h6v2" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

function XIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

// ─── Action card cu confirmare ───────────────────────────────────────────────────────

const ACTION_COLORS: Record<string, string> = {
  place_order:     'var(--color-primary)',
  close_position:  'var(--color-warning)',
  close_all:       'var(--color-error)',
  cancel_all:      'var(--color-warning)',
  emergency_stop:  'var(--color-error)',
  resume_trading:  'var(--color-success)',
  patch_settings:  'var(--color-blue)',
}

const ACTION_ICONS: Record<string, string> = {
  place_order:     '📊',
  close_position:  '❌',
  close_all:       '🚨',
  cancel_all:      '🚫',
  emergency_stop:  '🚨',
  resume_trading:  '▶️',
  patch_settings:  '⚙️',
}

interface ActionCardProps {
  action: AIAction
  onConfirm: (action: AIAction) => Promise<void>
  executing: boolean
  disabled: boolean
}

function ActionCard({ action, onConfirm, executing, disabled }: ActionCardProps) {
  const [state, setState] = useState<'idle' | 'confirming' | 'done' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')
  const color = ACTION_COLORS[action.type] ?? 'var(--color-primary)'
  const icon = ACTION_ICONS[action.type] ?? '⚡'

  async function handleConfirm() {
    setState('confirming')
    const result = await onConfirm(action)
    if (result.success !== false) {
      setState('done')
    } else {
      setState('error')
      setErrorMsg((result as { error?: string }).error ?? 'Eroare')
    }
  }

  return (
    <div style={{
      marginTop: 'var(--space-2)',
      padding: 'var(--space-3)',
      background: 'var(--color-surface-offset)',
      border: `1px solid ${color}30`,
      borderLeft: `3px solid ${color}`,
      borderRadius: 'var(--radius-md)',
      fontSize: 'var(--text-xs)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-1)' }}>
        <span>{icon}</span>
        <span style={{ fontWeight: 600, color }}>{action.label}</span>
      </div>
      {action.description && (
        <p style={{ color: 'var(--color-text-muted)', marginBottom: 'var(--space-2)', lineHeight: 1.4 }}>
          {action.description}
        </p>
      )}

      {state === 'idle' && (
        <button
          onClick={handleConfirm}
          disabled={disabled || executing}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 'var(--space-1)',
            padding: 'var(--space-1) var(--space-3)',
            background: color, color: '#fff',
            border: 'none', borderRadius: 'var(--radius-sm)',
            fontSize: 'var(--text-xs)', fontWeight: 600,
            cursor: disabled ? 'not-allowed' : 'pointer',
            opacity: disabled ? 0.6 : 1,
            transition: 'opacity 150ms',
          }}
        >
          <CheckIcon /> Confirmă & Execută
        </button>
      )}

      {state === 'confirming' && (
        <span style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>⏳ Se execută...</span>
      )}

      {state === 'done' && (
        <span style={{ color: 'var(--color-success)', display: 'flex', alignItems: 'center', gap: 4 }}>
          <CheckIcon /> Executat cu succes
        </span>
      )}

      {state === 'error' && (
        <span style={{ color: 'var(--color-error)', display: 'flex', alignItems: 'center', gap: 4 }}>
          <XIcon /> {errorMsg}
        </span>
      )}
    </div>
  )
}

// ─── Mesaj individual ────────────────────────────────────────────────────────────────────────

interface MessageBubbleProps {
  message: AIMessage
  onExecuteAction: (action: AIAction) => Promise<void>
  executing: string | null
}

function MessageBubble({ message, onExecuteAction, executing }: MessageBubbleProps) {
  const isUser = message.role === 'user'

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: isUser ? 'flex-end' : 'flex-start',
      gap: 'var(--space-1)',
      marginBottom: 'var(--space-3)',
    }}>
      {/* Role label */}
      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-faint)', paddingInline: 'var(--space-1)' }}>
        {isUser ? 'Tu' : 'NexusAI'}
      </div>

      {/* Bubble */}
      <div style={{
        maxWidth: '90%',
        padding: 'var(--space-2) var(--space-3)',
        borderRadius: isUser ? 'var(--radius-lg) var(--radius-lg) var(--radius-sm) var(--radius-lg)' : 'var(--radius-lg) var(--radius-lg) var(--radius-lg) var(--radius-sm)',
        background: isUser ? 'var(--color-primary)' : 'var(--color-surface-2)',
        color: isUser ? '#fff' : 'var(--color-text)',
        border: isUser ? 'none' : '1px solid var(--color-border)',
        fontSize: 'var(--text-xs)',
        lineHeight: 1.6,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}>
        {message.content || (message.streaming ? '' : '—')}
        {message.streaming && (
          <span style={{ display: 'inline-block', width: '2px', height: '1em', background: 'currentColor', marginLeft: '2px', animation: 'blink 1s step-end infinite', verticalAlign: 'text-bottom' }} />
        )}
      </div>

      {/* Action cards */}
      {message.actions && message.actions.length > 0 && (
        <div style={{ width: '100%', maxWidth: '90%' }}>
          {message.actions.map((action, i) => (
            <ActionCard
              key={i}
              action={action}
              onConfirm={onExecuteAction}
              executing={!!executing}
              disabled={!!executing}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Sugestii rapide ────────────────────────────────────────────────────────────────────────

const QUICK_PROMPTS = [
  'Analizează starea contului meu',
  'Ce poziţii ar trebui să închid?',
  'Cum e drawdown-ul curent?',
  'Recomandă un trade pe BTCUSDT',
  'Opreşte trading-ul dacă e necesar',
]

// ─── Component principal ────────────────────────────────────────────────────────────────────

interface AICopilotProps {
  onClose: () => void
}

export function AICopilot({ onClose }: AICopilotProps) {
  const { messages, status, loading, executing, sendMessage, executeAction, clearHistory, stopStreaming } = useAI()
  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Auto-scroll la mesaje noi
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function handleSend() {
    if (!input.trim() || loading) return
    sendMessage(input)
    setInput('')
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const isDisabled = !status?.enabled

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: 'var(--color-surface)',
      borderLeft: '1px solid var(--color-border)',
    }}>
      {/* ── Header ──────────────────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: 'var(--space-3) var(--space-4)',
        borderBottom: '1px solid var(--color-border)',
        height: 'var(--header-height)',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <span style={{ color: 'var(--color-primary)' }}><SparkleIcon /></span>
          <div>
            <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>NexusAI</div>
            {status && (
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-faint)' }}>
                {status.enabled
                  ? `${status.provider === 'groq' ? 'Groq' : 'OpenAI'} · ${status.model || 'llama-3.3-70b'}`
                  : 'Dezactivat — setează AI_ENABLED=true'}
              </div>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
          {messages.length > 0 && (
            <button
              onClick={clearHistory}
              title="Şterge conversatia"
              style={{ color: 'var(--color-text-faint)', cursor: 'pointer', display: 'flex', alignItems: 'center', padding: 'var(--space-1)' }}
            >
              <TrashIcon />
            </button>
          )}
          <button
            onClick={onClose}
            style={{ color: 'var(--color-text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center', padding: 'var(--space-1)', fontSize: '18px', lineHeight: 1 }}
            aria-label="Închide AI Copilot"
          >
            ×
          </button>
        </div>
      </div>

      {/* ── Messages ───────────────────────────────────────────────────────────── */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: 'var(--space-4)',
        display: 'flex',
        flexDirection: 'column',
      }}>
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', marginTop: 'var(--space-8)' }}>
            <div style={{ fontSize: '32px', marginBottom: 'var(--space-3)' }}>✨</div>
            <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--space-1)' }}>NexusAI Copilot</div>
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', maxWidth: '22ch', margin: '0 auto var(--space-6)' }}>
              {isDisabled
                ? 'Configurează GROQ_API_KEY sau OPENAI_API_KEY în .env pentru a activa.'
                : 'Pune o întrebare sau alege un prompt rapid.'}
            </div>
            {!isDisabled && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                {QUICK_PROMPTS.map(prompt => (
                  <button
                    key={prompt}
                    onClick={() => sendMessage(prompt)}
                    style={{
                      padding: 'var(--space-2) var(--space-3)',
                      background: 'var(--color-surface-offset)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 'var(--radius-md)',
                      fontSize: 'var(--text-xs)',
                      color: 'var(--color-text-muted)',
                      cursor: 'pointer',
                      textAlign: 'left',
                      transition: 'all 150ms',
                    }}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {messages.map(msg => (
          <MessageBubble
            key={msg.id}
            message={msg}
            onExecuteAction={executeAction}
            executing={executing}
          />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* ── Input ────────────────────────────────────────────────────────────────── */}
      <div style={{
        padding: 'var(--space-3) var(--space-4)',
        borderTop: '1px solid var(--color-border)',
        flexShrink: 0,
      }}>
        <div style={{
          display: 'flex',
          gap: 'var(--space-2)',
          alignItems: 'flex-end',
          background: 'var(--color-surface-offset)',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-lg)',
          padding: 'var(--space-2)',
          transition: 'border-color 150ms',
        }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isDisabled ? 'AI dezactivat' : 'Scrie un mesaj... (Enter = trimite, Shift+Enter = linie nouă)'}
            disabled={isDisabled || loading}
            rows={1}
            style={{
              flex: 1,
              resize: 'none',
              background: 'transparent',
              border: 'none',
              outline: 'none',
              fontSize: 'var(--text-xs)',
              color: 'var(--color-text)',
              lineHeight: 1.5,
              maxHeight: '96px',
              overflowY: 'auto',
              padding: 'var(--space-1)',
            }}
          />
          <button
            onClick={loading ? stopStreaming : handleSend}
            disabled={isDisabled || (!loading && !input.trim())}
            style={{
              flexShrink: 0,
              width: '30px', height: '30px',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: loading ? 'var(--color-error)' : 'var(--color-primary)',
              color: '#fff',
              border: 'none',
              borderRadius: 'var(--radius-md)',
              cursor: isDisabled || (!loading && !input.trim()) ? 'not-allowed' : 'pointer',
              opacity: isDisabled || (!loading && !input.trim()) ? 0.5 : 1,
              transition: 'all 150ms',
            }}
            title={loading ? 'Stop' : 'Trimite'}
          >
            {loading ? <StopIcon /> : <SendIcon />}
          </button>
        </div>
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-faint)', marginTop: 'var(--space-1)', paddingInline: 'var(--space-1)' }}>
          Acţiunile propuse necesită confirmare explicită.
        </div>
      </div>

      <style>{`
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
      `}</style>
    </div>
  )
}
