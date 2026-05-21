'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch, config } from '@/lib/config'
import type { AIAction, AIMessage, AIStatus } from '@/types/ai'

/** Genereaza un ID unic simplu fara dependinte externe */
function uid(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

/**
 * Parseaza blocurile <action>...</action> din textul unui mesaj AI.
 * Returneaza { content: text_fara_actiuni, actions: AIAction[] }
 */
function parseActions(raw: string): { content: string; actions: AIAction[] } {
  const actions: AIAction[] = []
  const content = raw.replace(/<action>\s*([\s\S]*?)\s*<\/action>/g, (_match, json) => {
    try {
      const parsed = JSON.parse(json) as AIAction
      if (parsed.type && parsed.label) actions.push(parsed)
    } catch {
      // JSON invalid — ignoram silentios
    }
    return ''
  }).trim()
  return { content, actions }
}

export function useAI() {
  const [messages, setMessages] = useState<AIMessage[]>([])
  const [status, setStatus] = useState<AIStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [executing, setExecuting] = useState<string | null>(null) // action type in progress
  const abortRef = useRef<AbortController | null>(null)

  // ─ Fetch AI status la mount ───────────────────────────────────────────────────
  useEffect(() => {
    apiFetch<AIStatus>('/ai/status')
      .then(s => setStatus(s))
      .catch(() => setStatus({ enabled: false, provider: 'none', model: '', has_groq: false, has_openai: false }))
  }, [])

  // ─ Trimite mesaj cu streaming SSE ──────────────────────────────────────────
  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || loading) return

    // Adauga mesajul user in history
    const userMsg: AIMessage = {
      id: uid(),
      role: 'user',
      content: text.trim(),
      timestamp: new Date().toISOString(),
    }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    // Placeholder pentru raspunsul AI (streaming)
    const assistantId = uid()
    const assistantPlaceholder: AIMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      streaming: true,
    }
    setMessages(prev => [...prev, assistantPlaceholder])

    // Construieste history pentru API (fara mesajul assistant placeholder)
    const history = [...messages, userMsg].map(m => ({ role: m.role, content: m.content }))

    abortRef.current = new AbortController()

    try {
      const res = await fetch(`${config.apiBase}/ai/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(config.apiKey ? { 'X-API-Key': config.apiKey } : {}),
        },
        body: JSON.stringify({ messages: history, stream: true }),
        signal: abortRef.current.signal,
      })

      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail ?? `HTTP ${res.status}`)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let accumulated = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const text = decoder.decode(value, { stream: true })
        // Parse SSE lines
        for (const line of text.split('\n')) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (data === '[DONE]') break
          try {
            const parsed = JSON.parse(data)
            if (parsed.error) throw new Error(parsed.error)
            if (parsed.delta) {
              accumulated += parsed.delta
              // Update mesaj streaming in timp real
              setMessages(prev => prev.map(m =>
                m.id === assistantId
                  ? { ...m, content: accumulated }
                  : m
              ))
            }
          } catch (e) {
            if (e instanceof Error && e.message !== '[object Object]') throw e
          }
        }
      }

      // Parseaza actiunile din raspunsul final
      const { content: finalContent, actions } = parseActions(accumulated)
      setMessages(prev => prev.map(m =>
        m.id === assistantId
          ? { ...m, content: finalContent, actions: actions.length ? actions : undefined, streaming: false }
          : m
      ))
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return
      const errMsg = err instanceof Error ? err.message : 'Eroare necunoscuta'
      setMessages(prev => prev.map(m =>
        m.id === assistantId
          ? { ...m, content: `⚠️ Eroare: ${errMsg}`, streaming: false }
          : m
      ))
    } finally {
      setLoading(false)
    }
  }, [messages, loading])

  // ─ Executa o actiune propusa (dupa confirmare) ────────────────────────────
  const executeAction = useCallback(async (action: AIAction): Promise<{ success: boolean; error?: string }> => {
    setExecuting(action.type)
    try {
      const result = await apiFetch<{ success: boolean; error?: string }>('/ai/execute', {
        method: 'POST',
        body: JSON.stringify({ action_type: action.type, params: action.params }),
      })
      return result
    } catch (err: unknown) {
      return { success: false, error: err instanceof Error ? err.message : 'Eroare' }
    } finally {
      setExecuting(null)
    }
  }, [])

  const clearHistory = useCallback(() => setMessages([]), [])

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort()
    setLoading(false)
    // Marcam ultimul mesaj assistant ca non-streaming
    setMessages(prev => prev.map((m, i) =>
      i === prev.length - 1 && m.role === 'assistant' && m.streaming
        ? { ...m, streaming: false }
        : m
    ))
  }, [])

  return {
    messages,
    status,
    loading,
    executing,
    sendMessage,
    executeAction,
    clearHistory,
    stopStreaming,
  }
}
