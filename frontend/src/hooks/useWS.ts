'use client'
import { useEffect, useRef } from 'react'
import { wsClient } from '@/lib/websocket'

/**
 * useWS — Subscribe to a WebSocket event.
 * Automatically connects the singleton on mount.
 * Cleans up subscription on unmount.
 */
export function useWS(event: string, handler: (payload: unknown) => void) {
  const handlerRef = useRef(handler)
  handlerRef.current = handler

  useEffect(() => {
    wsClient.connect()
    const h = (payload: unknown) => handlerRef.current(payload)
    wsClient.on(event, h)
    return () => wsClient.off(event, h)
  }, [event])
}
