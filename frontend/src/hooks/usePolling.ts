'use client'

import { useEffect, useRef } from 'react'

/**
 * usePolling — calls `fn` immediately, then every `intervalMs`.
 * Stops when the component unmounts or `enabled` becomes false.
 */
export function usePolling(
  fn: () => void | Promise<void>,
  intervalMs: number,
  enabled = true
) {
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    if (!enabled) return
    let active = true
    const run = () => { if (active) void Promise.resolve(fnRef.current()) }
    run()
    const id = setInterval(run, intervalMs)
    return () => { active = false; clearInterval(id) }
  }, [intervalMs, enabled])
}
