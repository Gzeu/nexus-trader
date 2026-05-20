/**
 * websocket.ts — DEPRECATED no-op shim.
 *
 * FIX #7: useWebSocket (hooks/useWebSocket.ts) is the single canonical
 * WS implementation with exponential backoff + cleanup.
 * This file exists only to prevent import errors on any leftover references.
 * Do NOT use wsClient — use the useWebSocket hook instead.
 */
export const wsClient = null;
