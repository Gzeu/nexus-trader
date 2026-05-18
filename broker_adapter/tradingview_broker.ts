/**
 * tradingview_broker.ts
 *
 * Full IBrokerTerminal implementation for TradingView Charting Library.
 *
 * Connects to the Nexus Trader FastAPI backend via:
 *   - REST calls for order placement, positions, account info
 *   - WebSocket for real-time fills/position updates
 *
 * Usage:
 *   import { TradingSystemBroker } from './tradingview_broker';
 *   // Pass to TradingView widget as: brokerFactory: (host) => new TradingSystemBroker(host)
 */

// ---------- Types (subset of TradingView IBrokerTerminal interface) ----------

export interface IBrokerConnectionAdapterHost {
  orderUpdate(order: BrokerOrder): void;
  positionUpdate(position: BrokerPosition): void;
  executionUpdate(execution: BrokerExecution): void;
  fullUpdate(): void;
  setConnected(connected: boolean): void;
  showNotification(title: string, text: string, type: number): void;
}

export interface BrokerOrder {
  id: string;
  symbol: string;
  side: number; // 1 = buy, -1 = sell
  type: number; // 1 = market, 2 = limit
  qty: number;
  price?: number;
  status: number; // 0=pending, 1=inactive, 2=working, 3=filled, 4=cancelled
  filledQty?: number;
  avgPrice?: number;
}

export interface BrokerPosition {
  id: string;
  symbol: string;
  qty: number;
  side: number;
  avgPrice: number;
  unrealizedPL?: number;
  realizedPL?: number;
}

export interface BrokerExecution {
  id: string;
  symbol: string;
  side: number;
  qty: number;
  price: number;
  time: number;
  orderId: string;
}

export interface PlaceOrderParams {
  symbol: string;
  side: number;
  type: number;
  qty: number;
  price?: number;
  stopLoss?: number;
  takeProfit?: number;
}

// ---------- Constants ----------

const ORDER_STATUS = { PENDING: 0, INACTIVE: 1, WORKING: 2, FILLED: 3, CANCELLED: 4 };
const ORDER_TYPE = { MARKET: 1, LIMIT: 2, STOP: 3 };
const SIDE = { BUY: 1, SELL: -1 };

// ---------- Broker Implementation ----------

export class TradingSystemBroker {
  private _host: IBrokerConnectionAdapterHost;
  private _baseUrl: string;
  private _ws: WebSocket | null = null;
  private _wsReconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _orders: Map<string, BrokerOrder> = new Map();
  private _positions: Map<string, BrokerPosition> = new Map();
  private _executions: BrokerExecution[] = [];
  private _connected = false;

  constructor(
    host: IBrokerConnectionAdapterHost,
    baseUrl: string = 'http://localhost:8000'
  ) {
    this._host = host;
    this._baseUrl = baseUrl.replace(/\/$/, '');
    this._connectWS();
  }

  // ────────────────────────────────────────────────────────────────
  // WebSocket: real-time event stream from the backend
  // ────────────────────────────────────────────────────────────────

  private _connectWS(): void {
    const wsUrl = this._baseUrl.replace(/^http/, 'ws') + '/ws';
    try {
      this._ws = new WebSocket(wsUrl);

      this._ws.onopen = () => {
        this._connected = true;
        this._host.setConnected(true);
        console.log('[NexusTrader] WebSocket connected');
        // Keep-alive ping every 20s
        setInterval(() => this._ws?.send('ping'), 20_000);
      };

      this._ws.onmessage = (ev) => {
        try {
          const { event, payload } = JSON.parse(ev.data);
          this._handleWSEvent(event, payload);
        } catch (_) { /* ignore non-JSON */ }
      };

      this._ws.onclose = () => {
        this._connected = false;
        this._host.setConnected(false);
        console.warn('[NexusTrader] WS closed, reconnecting in 3s...');
        this._wsReconnectTimer = setTimeout(() => this._connectWS(), 3_000);
      };

      this._ws.onerror = (err) => {
        console.error('[NexusTrader] WS error', err);
      };
    } catch (e) {
      console.error('[NexusTrader] WS connect error', e);
      this._wsReconnectTimer = setTimeout(() => this._connectWS(), 5_000);
    }
  }

  private _handleWSEvent(event: string, payload: Record<string, unknown>): void {
    switch (event) {
      case 'order_filled': {
        const order = this._mapOrder(payload);
        this._orders.set(order.id, order);
        this._host.orderUpdate(order);
        // Also create execution record
        const exec: BrokerExecution = {
          id: `exec_${order.id}_${Date.now()}`,
          symbol: order.symbol,
          side: order.side,
          qty: order.filledQty ?? order.qty,
          price: order.avgPrice ?? order.price ?? 0,
          time: Date.now(),
          orderId: order.id,
        };
        this._executions.push(exec);
        this._host.executionUpdate(exec);
        break;
      }
      case 'position_opened':
      case 'position_update_required':
      case 'partial_close':
      case 'trade_closed': {
        const pos = this._mapPosition(payload);
        if (pos.qty === 0) {
          this._positions.delete(pos.symbol);
        } else {
          this._positions.set(pos.symbol, pos);
        }
        this._host.positionUpdate(pos);
        break;
      }
      case 'tp_hit':
      case 'sl_hit': {
        const sym = payload['symbol'] as string;
        this._host.showNotification(
          event === 'tp_hit' ? '🎯 Take Profit Hit' : '🛑 Stop Loss Hit',
          `${sym} — ${event.replace('_', ' ').toUpperCase()}`,
          event === 'tp_hit' ? 1 : 2
        );
        break;
      }
      case 'emergency_stop':
        this._host.showNotification('🚨 Emergency Stop', 'All trading halted', 2);
        break;
      default:
        break;
    }
  }

  // ────────────────────────────────────────────────────────────────
  // IBrokerTerminal — Connection
  // ────────────────────────────────────────────────────────────────

  connectionStatus(): number {
    return this._connected ? 1 : 0;
  }

  async subscribeEquity(): Promise<void> {
    // Equity updates arrive via WS events; nothing extra needed
  }

  async unsubscribeEquity(): Promise<void> { /* noop */ }

  // ────────────────────────────────────────────────────────────────
  // IBrokerTerminal — Orders
  // ────────────────────────────────────────────────────────────────

  async placeOrder(params: PlaceOrderParams): Promise<{ orderId: string }> {
    await this._preOrderChecks();

    const body = {
      symbol: params.symbol,
      side: params.side === SIDE.BUY ? 'BUY' : 'SELL',
      quantity: params.qty,
      price: params.type === ORDER_TYPE.LIMIT ? params.price : undefined,
      stop_loss: params.stopLoss,
      take_profit: params.takeProfit,
      market_mode: 'SPOT',
    };

    const resp = await this._post('/api/v1/place_order', body);
    const order: BrokerOrder = {
      id: String(resp.orderId ?? resp.clientOrderId ?? Date.now()),
      symbol: params.symbol,
      side: params.side,
      type: params.type,
      qty: params.qty,
      price: params.price,
      status: ORDER_STATUS.WORKING,
    };
    this._orders.set(order.id, order);
    this._host.orderUpdate(order);
    return { orderId: order.id };
  }

  async cancelOrder(orderId: string): Promise<void> {
    const order = this._orders.get(orderId);
    if (!order) return;
    await this._post('/api/v1/cancel_all', { symbol: order.symbol });
    order.status = ORDER_STATUS.CANCELLED;
    this._orders.set(orderId, order);
    this._host.orderUpdate(order);
  }

  async cancelOrders(ids: string[]): Promise<void> {
    await Promise.all(ids.map((id) => this.cancelOrder(id)));
  }

  async orders(): Promise<BrokerOrder[]> {
    return Array.from(this._orders.values()).filter(
      (o) => o.status === ORDER_STATUS.WORKING || o.status === ORDER_STATUS.PENDING
    );
  }

  async executions(): Promise<BrokerExecution[]> {
    return [...this._executions];
  }

  // ────────────────────────────────────────────────────────────────
  // IBrokerTerminal — Positions
  // ────────────────────────────────────────────────────────────────

  async positions(): Promise<BrokerPosition[]> {
    try {
      const data: unknown[] = await this._get('/api/v1/positions');
      const mapped = data.map((p) => this._mapPosition(p as Record<string, unknown>));
      this._positions.clear();
      mapped.forEach((pos) => this._positions.set(pos.symbol, pos));
      return mapped;
    } catch {
      return Array.from(this._positions.values());
    }
  }

  async closePosition(symbol: string): Promise<void> {
    const pos = this._positions.get(symbol);
    if (!pos) return;
    await this._post('/api/v1/close_all', {});
    pos.qty = 0;
    this._positions.delete(symbol);
    this._host.positionUpdate({ ...pos, qty: 0 });
  }

  // ────────────────────────────────────────────────────────────────
  // IBrokerTerminal — Account
  // ────────────────────────────────────────────────────────────────

  async accountInfo(): Promise<{ balance: number; equity: number }> {
    try {
      const data = await this._get('/api/v1/account') as Record<string, number>;
      return { balance: data['total_wallet_balance'] ?? 0, equity: data['equity'] ?? 0 };
    } catch {
      return { balance: 0, equity: 0 };
    }
  }

  // ────────────────────────────────────────────────────────────────
  // Pre-order safety check
  // ────────────────────────────────────────────────────────────────

  private async _preOrderChecks(): Promise<void> {
    const health = await this._get('/api/v1/health') as Record<string, unknown>;
    if (health['status'] !== 'ok') {
      throw new Error(`System not ready: ${health['status']} — ${health['pause_reason'] ?? ''}`);
    }
    if (health['trading_paused']) {
      throw new Error(`Trading paused: ${health['pause_reason']}`);
    }
  }

  // ────────────────────────────────────────────────────────────────
  // HTTP helpers
  // ────────────────────────────────────────────────────────────────

  private async _get(path: string): Promise<unknown> {
    const r = await fetch(`${this._baseUrl}${path}`);
    if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
    return r.json();
  }

  private async _post(path: string, body: unknown): Promise<Record<string, unknown>> {
    const r = await fetch(`${this._baseUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.text();
      throw new Error(`POST ${path} → ${r.status}: ${err}`);
    }
    return r.json();
  }

  // ────────────────────────────────────────────────────────────────
  // Mappers: backend JSON → TradingView types
  // ────────────────────────────────────────────────────────────────

  private _mapOrder(data: Record<string, unknown>): BrokerOrder {
    return {
      id: String(data['orderId'] ?? data['id'] ?? Date.now()),
      symbol: String(data['symbol'] ?? ''),
      side: String(data['side']).toUpperCase() === 'BUY' ? SIDE.BUY : SIDE.SELL,
      type: String(data['type']).toUpperCase() === 'LIMIT' ? ORDER_TYPE.LIMIT : ORDER_TYPE.MARKET,
      qty: Number(data['origQty'] ?? data['quantity'] ?? 0),
      price: data['price'] ? Number(data['price']) : undefined,
      status: this._mapStatus(String(data['status'] ?? '')),
      filledQty: Number(data['executedQty'] ?? 0),
      avgPrice: data['avgPrice'] ? Number(data['avgPrice']) : undefined,
    };
  }

  private _mapPosition(data: Record<string, unknown>): BrokerPosition {
    const qty = Math.abs(Number(data['quantity'] ?? data['qty'] ?? 0));
    const side = Number(data['quantity'] ?? data['qty'] ?? 1) >= 0 ? SIDE.BUY : SIDE.SELL;
    return {
      id: String(data['id'] ?? data['symbol']),
      symbol: String(data['symbol'] ?? ''),
      qty,
      side,
      avgPrice: Number(data['entry_price'] ?? data['avgPrice'] ?? 0),
      unrealizedPL: Number(data['unrealized_pnl'] ?? 0),
      realizedPL: Number(data['realized_pnl'] ?? 0),
    };
  }

  private _mapStatus(status: string): number {
    switch (status.toUpperCase()) {
      case 'NEW': return ORDER_STATUS.WORKING;
      case 'PARTIALLY_FILLED': return ORDER_STATUS.WORKING;
      case 'FILLED': return ORDER_STATUS.FILLED;
      case 'CANCELED':
      case 'CANCELLED': return ORDER_STATUS.CANCELLED;
      case 'EXPIRED': return ORDER_STATUS.INACTIVE;
      default: return ORDER_STATUS.PENDING;
    }
  }
}
