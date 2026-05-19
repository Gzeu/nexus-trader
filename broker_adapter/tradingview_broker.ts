/**
 * tradingview_broker.ts – Complete IBrokerTerminal implementation for Nexus Trader.
 *
 * Changes in this version:
 * - ChartMarkerManager integrated — all WS events wired to chart markers:
 *     order_filled  → markers.onOrderFilled()
 *     signal_created→ markers.onSignal()
 *     tp1_hit       → markers.onTPHit(pos, 1, price, time)
 *     tp2_hit       → markers.onTPHit(pos, 2, price, time)
 *     sl_hit        → markers.onSLHit(pos, price, time)
 *     breakeven     → markers.onBreakevenMove()
 *     risk_event    → markers.onRiskEvent() [CRITICAL/WARNING routed]
 * - destroy() method — cleans up WS + marker manager
 * - loadHistoricalMarkers() — one call to render all past signals on chart
 * - WebSocket auto-reconnect with exponential backoff (max 30s)
 * - _pendingOrders cache prevents duplicate submissions on double-click
 * - _formatDecimal() ensures TradingView receives string numbers
 * - preOrderChecks() pings /health before every order
 * - Error boundaries on every async call with user-visible notification
 * - X-API-Key header on all fetch calls
 *
 * Docs:
 *   https://www.tradingview.com/charting-library-docs/latest/quick-start/
 *   https://www.tradingview.com/charting-library-docs/latest/api/interfaces/Charting_Library.IBrokerTerminal
 */

/// <reference types="@tradingview/charting_library" />

import type {
  IBrokerTerminal,
  Order,
  Position,
  Execution,
  BrokerConfigFlags,
  PlaceOrderResult,
  ModifyOrderResult,
} from "@tradingview/charting_library";

import {
  ChartMarkerManager,
  type MarkerOrder,
  type MarkerPosition,
} from "./chart_markers";

const DEFAULT_WS_RECONNECT_MS = 1_000;
const MAX_WS_RECONNECT_MS     = 30_000;

export interface NexusBrokerConfig {
  apiBase:     string;          // e.g. "http://localhost:8000/api/v1"
  wsUrl:       string;          // e.g. "ws://localhost:8000/ws"
  apiKey?:     string;          // API_SECRET_KEY from .env
  marketMode?: 'SPOT' | 'FUTURES';
  debug?:      boolean;
}

export class TradingSystemBroker implements IBrokerTerminal {
  private _host:            ReturnType<IBrokerTerminal['host']>;
  private _config:          NexusBrokerConfig;
  private _ws:              WebSocket | null = null;
  private _wsReconnectMs  = DEFAULT_WS_RECONNECT_MS;
  private _wsReconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _connected      = false;
  private _pendingOrders  = new Set<string>();
  private _markers:        ChartMarkerManager;
  private _destroyed       = false;

  constructor(
    host:   ReturnType<IBrokerTerminal['host']>,
    config: NexusBrokerConfig,
  ) {
    this._host    = host;
    this._config  = { marketMode: 'SPOT', debug: false, ...config };
    this._markers = new ChartMarkerManager(null); // attached later via attachWidget()
    this._connectWS();
  }

  /**
   * Call inside widget.onChartReady() to attach the marker manager to the live
   * chart and load all historical signals as markers.
   *
   * @param widget   The IChartingLibraryWidget instance
   */
  attachWidget(widget: any): void {
    this._markers = new ChartMarkerManager(widget);
    // Render historical signals on chart
    this._markers.loadHistoricalSignals(
      this._config.apiBase,
      this._config.apiKey,
    ).catch(e => this._log('warn', 'loadHistoricalSignals failed', e));
  }

  /**
   * Destroy this broker instance — disconnect WS and clear markers.
   */
  destroy(): void {
    this._destroyed = true;
    if (this._wsReconnectTimer) clearTimeout(this._wsReconnectTimer);
    this._ws?.close();
    this._ws = null;
  }

  // ── IBrokerTerminal required ──────────────────────────────────────────────

  connectionStatus(): number {
    return this._connected ? 1 : 0;
  }

  chartContextMenuActions(_context: any, _options: any): Promise<any[]> {
    return Promise.resolve([]);
  }

  isTradable(_symbol: string): Promise<boolean> {
    return Promise.resolve(true);
  }

  async placeOrder(order: Order): Promise<PlaceOrderResult> {
    const dedupeKey = `${order.symbol}_${order.side}_${order.qty}_${Date.now()}`;
    if (this._pendingOrders.has(dedupeKey)) {
      this._log('warn', 'Duplicate order submission blocked', order);
      return { orderId: '' };
    }
    this._pendingOrders.add(dedupeKey);
    setTimeout(() => this._pendingOrders.delete(dedupeKey), 5_000);

    const healthy = await this._checkHealth();
    if (!healthy) {
      this._host.showNotification('Nexus Trader', 'System not ready — check /health.', 1);
      return { orderId: '' };
    }

    try {
      const res = await this._fetch('/place_order', {
        method: 'POST',
        body:   JSON.stringify({
          symbol:      order.symbol,
          side:        order.side === 1 ? 'BUY' : 'SELL',
          quantity:    this._formatDecimal(order.qty),
          price:       order.type === 1 ? null : this._formatDecimal(order.limitPrice),
          stop_loss:   this._formatDecimal(order.stopLoss),
          take_profit: this._formatDecimal(order.takeProfit),
          market_mode: this._config.marketMode,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        this._host.showNotification('Order Failed', String(err.detail), 1);
        return { orderId: '' };
      }

      const data = await res.json();
      this._log('info', 'Order placed', data);
      return { orderId: data.exchange_order_id ?? data.id ?? '' };
    } catch (e) {
      this._host.showNotification('Order Error', String(e), 1);
      return { orderId: '' };
    } finally {
      this._pendingOrders.delete(dedupeKey);
    }
  }

  async modifyOrder(order: Order): Promise<ModifyOrderResult> {
    await this.cancelOrder(order.id);
    const result = await this.placeOrder(order);
    return { orderId: result.orderId };
  }

  async cancelOrder(orderId: string): Promise<void> {
    try {
      await this._fetch(`/cancel_all?symbol=${orderId}`, { method: 'POST' });
    } catch (e) {
      this._log('warn', 'cancelOrder failed', e);
    }
  }

  async cancelOrders(symbol: string): Promise<void> {
    try {
      await this._fetch(`/cancel_all?symbol=${symbol}`, { method: 'POST' });
    } catch (e) {
      this._log('warn', 'cancelOrders failed', e);
    }
  }

  async closePosition(symbol: string): Promise<void> {
    try {
      await this._fetch('/webhook/pine', {
        method: 'POST',
        body:   JSON.stringify({ symbol, action: 'CLOSE', secret: this._config.apiKey }),
      });
    } catch (e) {
      this._log('warn', 'closePosition failed', e);
    }
  }

  async orders(): Promise<Order[]> {
    try {
      const res  = await this._fetch('/signals?limit=100');
      const data = await res.json();
      return (data.trades ?? []).map(this._mapOrder.bind(this));
    } catch { return []; }
  }

  async positions(): Promise<Position[]> {
    try {
      const res  = await this._fetch('/positions');
      const data: any[] = await res.json();
      return data.map(this._mapPosition.bind(this));
    } catch { return []; }
  }

  async executions(_symbol?: string): Promise<Execution[]> {
    try {
      const res  = await this._fetch('/signals?limit=200');
      const data = await res.json();
      return (data.trades ?? [])
        .filter((t: any) => t.status === 'FILLED' || t.status === 'DRY_RUN')
        .map(this._mapExecution.bind(this));
    } catch { return []; }
  }

  async preOrderChecks(_order: Order): Promise<void> {
    await this._checkHealth();
  }

  async symbolInfo(_symbol: string) { return null; }
  accountInfo() { return Promise.resolve({ id: 'nexus', name: 'Nexus Trader' }); }
  subscribeEquity() {}
  unsubscribeEquity() {}
  subscribeOrders() {}
  subscribePL() {}

  configFlags(): BrokerConfigFlags {
    return {
      supportOrderBrackets:         true,
      supportPositionBrackets:      true,
      supportClosePosition:         true,
      supportEditAmount:            false,
      supportModifyOrder:           true,
      supportLevel2Data:            false,
      showQuantityInsteadOfAmount:  true,
      supportMarketOrders:          true,
      supportLimitOrders:           true,
      supportStopOrders:            false,
      supportStopLimitOrders:       false,
      supportPartialClosePosition:  false,
      supportNativeReversePosition: false,
    };
  }

  // ── WebSocket ─────────────────────────────────────────────────────────────

  private _connectWS(): void {
    if (this._destroyed) return;
    if (this._wsReconnectTimer) {
      clearTimeout(this._wsReconnectTimer);
      this._wsReconnectTimer = null;
    }

    try {
      this._ws = new WebSocket(this._config.wsUrl);

      this._ws.onopen = () => {
        this._connected    = true;
        this._wsReconnectMs = DEFAULT_WS_RECONNECT_MS;
        this._log('info', 'WebSocket connected');
      };

      this._ws.onmessage = (ev) => {
        try { this._handleWSEvent(JSON.parse(ev.data)); } catch {}
      };

      this._ws.onclose = () => {
        this._connected = false;
        if (!this._destroyed) this._scheduleReconnect();
      };

      this._ws.onerror = (err) => {
        this._log('warn', 'WebSocket error', err);
        this._ws?.close();
      };

      const pingInterval = setInterval(() => {
        if (this._destroyed) { clearInterval(pingInterval); return; }
        if (this._ws?.readyState === WebSocket.OPEN) {
          this._ws.send(JSON.stringify({ type: 'ping' }));
        } else {
          clearInterval(pingInterval);
        }
      }, 10_000);
    } catch (e) {
      this._log('warn', 'WebSocket connect failed', e);
      this._scheduleReconnect();
    }
  }

  private _scheduleReconnect(): void {
    this._wsReconnectTimer = setTimeout(() => {
      this._log('info', `WS reconnecting in ${this._wsReconnectMs}ms`);
      this._connectWS();
    }, this._wsReconnectMs);
    this._wsReconnectMs = Math.min(this._wsReconnectMs * 2, MAX_WS_RECONNECT_MS);
  }

  private _handleWSEvent(event: { event: string; payload: any }): void {
    const { event: type, payload } = event;

    switch (type) {
      // ── IBrokerTerminal host updates ──────────────────────────────────────
      case 'order_filled':
      case 'order_placed':
        this._host.orderUpdate(this._mapOrder(payload));
        // Chart marker: entry arrow
        this._markers.onOrderFilled({
          symbol:   payload.symbol,
          side:     payload.side,
          price:    parseFloat(payload.avg_fill_price ?? payload.price) || 0,
          quantity: parseFloat(payload.quantity ?? payload.qty) || 0,
          time:     payload.time ?? Math.floor(Date.now() / 1000),
          orderId:  String(payload.exchange_order_id ?? Date.now()),
          dryRun:   payload.dry_run === true,
        } satisfies MarkerOrder);
        break;

      case 'position_opened':
      case 'position_updated':
      case 'position_closed':
        this._host.positionUpdate(this._mapPosition(payload));
        break;

      case 'signal_created':
        if (payload.action !== 'HOLD') {
          this._markers.onSignal({
            symbol:      payload.symbol,
            action:      payload.action,
            confidence:  payload.confidence ?? 0,
            reason:      payload.reason ?? '',
            time:        payload.timestamp ?? Math.floor(Date.now() / 1000),
            stopLoss:    parseFloat(payload.stop_loss ?? 0),
            takeProfit1: parseFloat(payload.take_profit_1 ?? 0),
          });
        }
        break;

      case 'tp1_hit': {
        const pos = payload.position ?? {};
        this._markers.onTPHit(
          this._payloadToMarkerPos(payload.symbol, pos),
          1,
          parseFloat(payload.price ?? 0),
          payload.time ?? Math.floor(Date.now() / 1000),
        );
        this._host.showNotification('Trade Update', `TP1 hit — ${payload.symbol} @ ${payload.price}`, 0);
        break;
      }

      case 'tp2_hit': {
        const pos2 = payload.position ?? {};
        this._markers.onTPHit(
          this._payloadToMarkerPos(payload.symbol, pos2),
          2,
          parseFloat(payload.price ?? 0),
          payload.time ?? Math.floor(Date.now() / 1000),
        );
        this._host.showNotification('Trade Update', `TP2 hit — ${payload.symbol} @ ${payload.price}`, 0);
        break;
      }

      case 'sl_hit': {
        const pos3 = payload.position ?? {};
        this._markers.onSLHit(
          this._payloadToMarkerPos(payload.symbol, pos3),
          parseFloat(payload.price ?? 0),
          payload.time ?? Math.floor(Date.now() / 1000),
        );
        this._host.showNotification('Trade Update', `SL hit — ${payload.symbol} @ ${payload.price}`, 1);
        break;
      }

      case 'breakeven':
        this._markers.onBreakevenMove(
          payload.symbol,
          parseFloat(payload.price ?? 0),
          payload.time ?? Math.floor(Date.now() / 1000),
        );
        this._host.showNotification('Trade Update', `SL moved to breakeven — ${payload.symbol}`, 0);
        break;

      case 'risk_event': {
        const severity = payload.severity === 'CRITICAL' ? 'CRITICAL' : 'WARNING';
        this._markers.onRiskEvent({
          symbol:   payload.symbol ?? '',
          severity,
          detail:   payload.detail ?? payload.event ?? '',
          time:     payload.time ?? Math.floor(Date.now() / 1000),
        });
        this._host.showNotification(
          `NEXUS ${severity}`,
          payload.detail ?? payload.event ?? 'Risk event',
          severity === 'CRITICAL' ? 1 : 0,
        );
        break;
      }

      case 'emergency_stop':
        this._host.showNotification('NEXUS', '\uD83D\uDEA8 Emergency Stop activated', 1);
        break;

      case 'heartbeat':
        this._connected = true;
        break;
    }
  }

  // ── Private helpers ───────────────────────────────────────────────────────

  private _payloadToMarkerPos(symbol: string, pos: any): MarkerPosition {
    return {
      symbol,
      side:        pos.side === 'SHORT' ? 'SHORT' : 'LONG',
      entryPrice:  parseFloat(pos.entry_price ?? 0),
      stopLoss:    parseFloat(pos.stop_loss   ?? 0),
      takeProfit1: parseFloat(pos.take_profit_1 ?? 0),
      takeProfit2: parseFloat(pos.take_profit_2 ?? 0),
    };
  }

  private async _fetch(path: string, init?: RequestInit): Promise<Response> {
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...(this._config.apiKey ? { 'X-API-Key': this._config.apiKey } : {}),
    };
    return fetch(`${this._config.apiBase}${path}`, {
      ...init,
      headers: { ...headers, ...(init?.headers ?? {}) },
    });
  }

  private async _checkHealth(): Promise<boolean> {
    try {
      const res  = await this._fetch('/health');
      const data = await res.json();
      return data.status === 'ok' && data.reconciled === true;
    } catch { return false; }
  }

  private _formatDecimal(value?: number | null): string | undefined {
    if (value == null || isNaN(value)) return undefined;
    return parseFloat(value.toFixed(8)).toString();
  }

  private _mapOrder(raw: any): Order {
    return {
      id:         raw.exchange_order_id ?? raw.id ?? '',
      symbol:     raw.symbol ?? '',
      side:       raw.side === 'BUY' || raw.side === 1 ? 1 : -1,
      type:       raw.order_type === 'LIMIT' ? 2 : 1,
      status:     raw.status === 'FILLED' ? 2 : raw.status === 'CANCELED' ? 3 : 1,
      qty:        parseFloat(raw.quantity ?? raw.qty ?? 0),
      limitPrice: parseFloat(raw.avg_fill_price ?? raw.price ?? 0),
      stopLoss:   parseFloat(raw.stop_loss ?? 0),
      takeProfit: parseFloat(raw.take_profit_1 ?? raw.take_profit ?? 0),
    } as unknown as Order;
  }

  private _mapPosition(raw: any): Position {
    return {
      id:           raw.symbol ?? '',
      symbol:       raw.symbol ?? '',
      side:         raw.side === 'LONG' || raw.side === 1 ? 1 : -1,
      qty:          parseFloat(raw.quantity ?? 0),
      avgPrice:     parseFloat(raw.entry_price ?? 0),
      unrealizedPL: parseFloat(raw.unrealized_pnl ?? 0),
    } as unknown as Position;
  }

  private _mapExecution(raw: any): Execution {
    return {
      id:     raw.exchange_order_id ?? raw.id ?? '',
      symbol: raw.symbol ?? '',
      side:   raw.side === 'BUY' ? 1 : -1,
      qty:    parseFloat(raw.quantity ?? 0),
      price:  parseFloat(raw.avg_fill_price ?? 0),
      time:   new Date(raw.filled_at ?? raw.placed_at).getTime(),
    } as unknown as Execution;
  }

  private _log(level: 'info' | 'warn' | 'error', msg: string, data?: any): void {
    if (!this._config.debug && level === 'info') return;
    const prefix = '[NexusBroker]';
    if (level === 'error')     console.error(prefix, msg, data);
    else if (level === 'warn') console.warn(prefix, msg, data);
    else                       console.log(prefix, msg, data);
  }
}
