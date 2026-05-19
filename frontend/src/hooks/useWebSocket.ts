'use client'

import { useEffect, useRef, useCallback, useState } from 'react'
import type { WSEvent } from '@/types'

type Handler = (event: WSEvent) => void

const WS_URL = (process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws')

export function useWebSocket(onEvent: Handler) {
  const wsRef        = useRef<WebSocket | null>(null)
  const handlerRef   = useRef<Handler>(onEvent)
  const retryRef     = useRef<ReturnType<typeof setTimeout> | null>(null)
  const retryCount   = useRef(0)
  const [connected, setConnected] = useState(false)

  handlerRef.current = onEvent

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      retryCount.current = 0
    }

    ws.onmessage = (e) => {
      try {
        const evt: WSEvent = JSON.parse(e.data)
        handlerRef.current(evt)
      } catch { /* ignore malformed */ }
    }

    ws.onclose = () => {
      setConnected(false)
      wsRef.current = null
      // Exponential backoff: 1s, 2s, 4s … max 16s
      const delay = Math.min(1000 * 2 ** retryCount.current, 16_000)
      retryCount.current++
      retryRef.current = setTimeout(connect, delay)
    }

    ws.onerror = () => ws.close()
  }, [])

  useEffect(() => {
    connect()
    return () => {
      if (retryRef.current) clearTimeout(retryRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  return { connected }
}
