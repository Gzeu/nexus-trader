'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch, config } from '@/lib/config'
import type { AIAction, AIMessage, AIStatus } from '@/types/ai'

/** Generează un ID unic simplu fără dependențe externe */
function uid(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

/**
 * Parsează blocurile <action>...</action> din textul unui mesaj AI.
 * Returnează { content: text_fără_acțiuni, actions: AIAction[] }
 */
function parseActions(raw: string): { content: string; actions: AIAction[] } {
  const actions: AIAction[] = []
  const content = raw
    .replace(/<action>\s*([\s\S]*?)\s*<\/action>/g, (_match, json) => {
      try {
        const parsed = JSON.parse(json) as AIAction
        if (parsed.type && parsed.label) actions.push(parsed)
      } catch {
        // JSON invalid — ignorăm silentios
      }
      return ''
    })
    .trim()
  return { content, actions }
}

export function useAI() {
  const [messages, setMessages] = useState<AIMessage[]>([])
  const [status, setStatus] = useState<AIStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [executing, setExecuting] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // ─ Fetch AI status la mount ──────────────────────────────────────────────
  useEffect(() => {
    apiFetch<AIStatus>('/ai/status')
      .then(s => setStatus(s))
      .catch(() =>
        setStatus({ enabled: false, provider: 'none', model: '', has_groq: false, has_openai: false }),
      )
  }, [])

  // ─ Trimite mesaj cu streaming SSE ───────────────────────────────────────
  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || loading) return

      // Adaugă mesajul user în history
      const userMsg: AIMessage = {
        id: uid(),
        role: 'user',
        content: text.trim(),
        timestamp: new Date().toISOString(),
      }
      setMessages(prev => [...prev, userMsg])
      setLoading(true)

      // Placeholder pentru răspunsul AI (streaming)
      const assistantId = uid()
      const assistantPlaceholder: AIMessage = {
        id: assistantId,
        role: 'assistant',
        content: '',
        timestamp: new Date().toISOString(),
        streaming: true,
      }
      setMessages(prev => [...prev, assistantPlaceholder])

      // History pentru API: toate mesajele anterioare + mesajul user curent
      const history = [...messages, userMsg].map(m => ({ role: m.role, content: m.content }))

      abortRef.current = new AbortController()

      try {
        // Endpoint corect: /ai/chat (nu /ai/chat/stream)
        const res = await fetch(`${config.apiBase}/ai/chat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(config.apiKey ? { 'X-API-Key': config.apiKey } : {}),
          },
          body: JSON.stringify({
            message: text.trim(),
            history: history.slice(0, -1), // exclude mesajul curent (trimis separat)
            include_context: true,
          }),
          signal: abortRef.current.signal,
        })

        if (!res.ok || !res.body) {
          const err = await res.json().catch(() => ({ detail: res.statusText }))
          throw new Error(err.detail ?? `HTTP ${res.status}`)
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let accumulated = ''   // tokeni de conținut acumulați
        let lineBuffer = ''    // buffer pentru linii SSE parțiale

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          // Decodificăm chunk-ul și îll adăugăm la buffer-ul de linii
          lineBuffer += decoder.decode(value, { stream: true })

          // Procesăm toate liniile complete (terminate cu \n)
          const lines = lineBuffer.split('\n')
          // Ultima "linie" poate fi incompletă — o păstrăm pentru următorul chunk
          lineBuffer = lines.pop() ?? ''

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            const data = line.slice(6).trim()

            if (data === '[DONE]') break

            try {
              const parsed = JSON.parse(data)

              // ── Eroare de la backend (non-retryable)
              if (parsed.error) {
                throw new Error(parsed.error)
              }

              // ── Token de conținut normal
              // Backend trimite: { "token": "..." } — nu { "delta": "..." }
              if (parsed.token) {
                accumulated += parsed.token
                setMessages(prev =>
                  prev.map(m =>
                    m.id === assistantId ? { ...m, content: accumulated } : m,
                  ),
                )
              }

              // ── Notice de sistem (retry Groq, fallback OpenAI, etc.)
              // Append ca notă italic în mesajul curent, vizibilă în timp real
              if (parsed.notice) {
                const noticeText = `\n\n*ℹ️ ${parsed.notice}*`
                accumulated += noticeText
                setMessages(prev =>
                  prev.map(m =>
                    m.id === assistantId ? { ...m, content: accumulated } : m,
                  ),
                )
              }
            } catch (e) {
              if (e instanceof Error && e.name !== 'SyntaxError') throw e
              // JSON parțial / linie goală — ignorăm
            }
          }
        }

        // Parsează acțiunile din răspunsul final acumulat
        const { content: finalContent, actions } = parseActions(accumulated)
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantId
              ? { ...m, content: finalContent, actions: actions.length ? actions : undefined, streaming: false }
              : m,
          ),
        )
      } catch (err: unknown) {
        if (err instanceof Error && err.name === 'AbortError') return
        const errMsg = err instanceof Error ? err.message : 'Eroare necunoscută'
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantId
              ? { ...m, content: `⚠️ Eroare: ${errMsg}`, streaming: false }
              : m,
          ),
        )
      } finally {
        setLoading(false)
      }
    },
    [messages, loading],
  )

  // ─ Execută o acțiune propusă (după confirmare) ───────────────────────
  const executeAction = useCallback(
    async (action: AIAction): Promise<{ success: boolean; error?: string }> => {
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
    },
    [],
  )

  const clearHistory = useCallback(() => setMessages([]), [])

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort()
    setLoading(false)
    // Marchează ultimul mesaj assistant ca non-streaming
    setMessages(prev =>
      prev.map((m, i) =>
        i === prev.length - 1 && m.role === 'assistant' && m.streaming
          ? { ...m, streaming: false }
          : m,
      ),
    )
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
