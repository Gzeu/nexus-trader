/**
 * useWS.ts — DEPRECATED re-export shim.
 *
 * FIX #7: useWebSocket.ts is the canonical implementation.
 * Any component that imported useWS continues to work without changes.
 */
export { useWebSocket as useWS } from './useWebSocket';
