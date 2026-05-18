/**
 * websocket.ts — Singleton WebSocket client with auto-reconnect.
 * Components subscribe via on() and unsubscribe via off().
 */

type WSHandler = (payload: unknown) => void

const DEFAULT_RECONNECT_MS = 1_000
const MAX_RECONNECT_MS     = 30_000

class NexusWSClient {
  private _ws: WebSocket | null = null
  private _reconnectMs = DEFAULT_RECONNECT_MS
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private _handlers: Map<string, Set<WSHandler>> = new Map()
  private _url: string
  public connected = false

  constructor(url: string) {
    this._url = url
  }

  connect(): void {
    if (this._ws?.readyState === WebSocket.OPEN) return
    try {
      this._ws = new WebSocket(this._url)
      this._ws.onopen    = () => { this.connected = true;  this._reconnectMs = DEFAULT_RECONNECT_MS; this._emit('connected', null) }
      this._ws.onclose   = () => { this.connected = false; this._emit('disconnected', null); this._scheduleReconnect() }
      this._ws.onerror   = () => { this._ws?.close() }
      this._ws.onmessage = (ev) => {
        try {
          const { event, payload } = JSON.parse(ev.data)
          this._emit(event, payload)
        } catch {}
      }
      // Keepalive
      const ping = setInterval(() => {
        if (this._ws?.readyState === WebSocket.OPEN) this._ws.send('{"type":"ping"}')
        else clearInterval(ping)
      }, 10_000)
    } catch { this._scheduleReconnect() }
  }

  on(event: string, handler: WSHandler): void {
    if (!this._handlers.has(event)) this._handlers.set(event, new Set())
    this._handlers.get(event)!.add(handler)
  }

  off(event: string, handler: WSHandler): void {
    this._handlers.get(event)?.delete(handler)
  }

  private _emit(event: string, payload: unknown): void {
    this._handlers.get(event)?.forEach(h => h(payload))
    this._handlers.get('*')?.forEach(h => h({ event, payload }))
  }

  private _scheduleReconnect(): void {
    if (this._reconnectTimer) clearTimeout(this._reconnectTimer)
    this._reconnectTimer = setTimeout(() => this.connect(), this._reconnectMs)
    this._reconnectMs = Math.min(this._reconnectMs * 2, MAX_RECONNECT_MS)
  }
}

// Singleton — safe to import anywhere
import { config } from './config'
export const wsClient = new NexusWSClient(config.wsUrl)
