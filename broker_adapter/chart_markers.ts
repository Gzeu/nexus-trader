/**
 * chart_markers.ts – TradingView Chart Markers for Nexus Trader
 *
 * Renders entry, exit, SL hit, TP hit, breakeven, and risk-event markers
 * on the chart using TradingView Charting Library's createShape() /
 * createExecutionShape() API.
 *
 * Improvements over v1:
 * - loadHistoricalSignals() fetches + renders all past signals on chart ready
 * - onRiskEvent() renders ⚠ marker with CRITICAL/WARNING severity routing
 * - onBreakevenMove() renders BE marker explicitly (was missing)
 * - clearBySymbol() clears only shapes for one symbol
 * - getShapeCount() for testing / status display
 * - Symbol-indexed shape registry (_shapeIds keyed by symbol+id)
 * - All createShape() calls use safe try/catch with graceful fallback
 *
 * Usage:
 *   import { ChartMarkerManager, wireChartMarkersToWebSocket } from './chart_markers';
 *   const markers = new ChartMarkerManager(widget);
 *   markers.onOrderFilled(order);
 *   markers.onTPHit(position, 1, price, time);
 *   markers.onSLHit(position, price, time);
 *   markers.onSignal(signal);
 *   markers.onRiskEvent({ symbol: 'BTCUSDT', severity: 'CRITICAL', detail: '...', time });
 *   markers.onBreakevenMove('BTCUSDT', price, time);
 *   markers.loadHistoricalSignals('http://localhost:8000/api/v1', 'X-API-KEY');
 *
 * Docs:
 *   https://www.tradingview.com/charting-library-docs/latest/api/interfaces/Charting_Library.IChartingLibraryWidget
 *   https://www.tradingview.com/charting-library-docs/latest/api/interfaces/Charting_Library.IChartApi/#createshape
 */

export interface MarkerOrder {
  symbol:     string;
  side:       'BUY' | 'SELL';
  price:      number;
  quantity:   number;
  time:       number;   // Unix timestamp seconds
  orderId:    string;
  dryRun?:    boolean;
}

export interface MarkerPosition {
  symbol:      string;
  side:        'LONG' | 'SHORT';
  entryPrice:  number;
  stopLoss:    number;
  takeProfit1: number;
  takeProfit2: number;
}

export interface MarkerSignal {
  symbol:      string;
  action:      'BUY' | 'SELL' | 'HOLD';
  confidence:  number;
  reason:      string;
  time:        number;
  stopLoss:    number;
  takeProfit1: number;
}

export interface RiskEventMarker {
  symbol:   string;
  severity: 'CRITICAL' | 'WARNING';
  detail:   string;
  time:     number;  // Unix timestamp seconds
}

// ── Color palette aligned with Nexus design tokens ──────────────────────────
const COLORS = {
  buy:          '#01696f',  // --color-primary (Hydra Teal)
  sell:         '#a12c7b',  // --color-error
  tp:           '#437a22',  // --color-success
  sl:           '#a13544',  // --color-notification
  signal_buy:   '#006494',  // --color-blue
  signal_sell:  '#7a39bb',  // --color-purple
  dryRun:       '#d19900',  // --color-gold
  breakeven:    '#da7101',  // --color-orange
  risk_critical:'#ff1744',  // bright red — CRITICAL events
  risk_warning: '#ffa726',  // amber — WARNING events
} as const;


export class ChartMarkerManager {
  private _widget:   any;  // IChartingLibraryWidget
  /** key = `${symbol}__${id}` → array of TradingView entity IDs */
  private _shapeIds: Map<string, string[]> = new Map();

  constructor(widget: any) {
    this._widget = widget;
  }

  // ── Public API ────────────────────────────────────────────────────────────

  /**
   * Called when an order is filled (entry).
   * Renders an entry execution arrow on the chart.
   */
  onOrderFilled(order: MarkerOrder): void {
    const chart = this._activeChart();
    if (!chart) return;

    const isBuy  = order.side === 'BUY';
    const color  = order.dryRun ? COLORS.dryRun : (isBuy ? COLORS.buy : COLORS.sell);
    const text   = order.dryRun
      ? `[DRY] ${order.side} ${order.quantity} @ ${order.price.toFixed(2)}`
      : `${order.side} ${order.quantity} @ ${order.price.toFixed(2)}`;

    try {
      // createExecutionShape — preferred TV Charting Library API for trade fills
      const shapeId = chart.createExecutionShape()
        .setTime(order.time)
        .setDirection(isBuy ? 'buy' : 'sell')
        .setArrowHeight(15)
        .setArrowSpacing(5)
        .setArrowColor(color)
        .setTooltip(text)
        .setTextColor(color)
        .setText(text);

      this._addShapeId(order.symbol, order.orderId, shapeId);
    } catch {
      // Fallback: createShape arrow
      this._createArrowShape(
        chart, order.symbol, order.time, order.price,
        isBuy, color, text, order.orderId,
      );
    }
  }

  /**
   * TP1 or TP2 hit — green checkmark above/below the candle.
   */
  onTPHit(
    position: MarkerPosition,
    tpLevel:  1 | 2,
    price:    number,
    time:     number,
  ): void {
    const chart = this._activeChart();
    if (!chart) return;
    const isLong = position.side === 'LONG';
    const label  = `TP${tpLevel} \u2713 @ ${price.toFixed(2)}`;
    this._createTextShape(
      chart, position.symbol, time, price, label,
      COLORS.tp, isLong ? 'above' : 'below',
      `tp${tpLevel}_${position.symbol}_${time}`,
    );
  }

  /**
   * Stop-loss hit — red X marker.
   */
  onSLHit(
    position: MarkerPosition,
    price:    number,
    time:     number,
  ): void {
    const chart = this._activeChart();
    if (!chart) return;
    const isLong = position.side === 'LONG';
    const label  = `SL \u2717 @ ${price.toFixed(2)}`;
    this._createTextShape(
      chart, position.symbol, time, price, label,
      COLORS.sl, isLong ? 'below' : 'above',
      `sl_${position.symbol}_${time}`,
    );
  }

  /**
   * Strategy signal arrow (before entry — visible in dry-run/review mode).
   * Also draws SL and TP1 horizontal dashed lines.
   */
  onSignal(signal: MarkerSignal): void {
    const chart = this._activeChart();
    if (!chart || signal.action === 'HOLD') return;

    const isBuy  = signal.action === 'BUY';
    const color  = isBuy ? COLORS.signal_buy : COLORS.signal_sell;
    const label  = `${signal.action} ${(signal.confidence * 100).toFixed(0)}% \u2014 ${signal.reason.slice(0, 40)}`;
    const key    = `sig_${signal.symbol}_${signal.time}`;

    this._createArrowShape(
      chart, signal.symbol, signal.time,
      isBuy ? signal.stopLoss : signal.takeProfit1,
      isBuy, color, label, key,
    );
    this._createPriceLine(chart, signal.symbol, signal.stopLoss,    COLORS.sl, `SL ${signal.stopLoss.toFixed(2)}`, key + '_sl');
    this._createPriceLine(chart, signal.symbol, signal.takeProfit1, COLORS.tp, `TP1 ${signal.takeProfit1.toFixed(2)}`, key + '_tp');
  }

  /**
   * SL moved to breakeven after TP1 — orange BE marker.
   */
  onBreakevenMove(symbol: string, price: number, time: number): void {
    const chart = this._activeChart();
    if (!chart) return;
    this._createTextShape(
      chart, symbol, time, price,
      `BE \u2191 ${price.toFixed(2)}`,
      COLORS.breakeven, 'below',
      `be_${symbol}_${time}`,
    );
  }

  /**
   * Risk event marker — CRITICAL renders bright red \u26a0 marker,
   * WARNING renders amber \u26a0 marker.
   */
  onRiskEvent(event: RiskEventMarker): void {
    const chart = this._activeChart();
    if (!chart) return;
    const isCritical = event.severity === 'CRITICAL';
    const color  = isCritical ? COLORS.risk_critical : COLORS.risk_warning;
    const label  = `\u26a0 ${event.severity}: ${event.detail.slice(0, 50)}`;
    const key    = `risk_${event.symbol}_${event.time}`;
    this._createTextShape(
      chart, event.symbol, event.time, 0,
      label, color, 'above', key,
    );
    if (isCritical) {
      console.error('[ChartMarkers] CRITICAL risk event:', event.detail);
    } else {
      console.warn('[ChartMarkers] WARNING risk event:', event.detail);
    }
  }

  /**
   * Fetch historical signals from Nexus backend and render all markers on chart.
   * Call this inside widget.onChartReady().
   */
  async loadHistoricalSignals(
    apiBase:  string,
    apiKey?:  string,
    limit:    number = 500,
  ): Promise<void> {
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (apiKey) headers['X-API-Key'] = apiKey;

      const res = await fetch(`${apiBase}/signals?limit=${limit}`, { headers });
      if (!res.ok) {
        console.warn('[ChartMarkers] loadHistoricalSignals failed:', res.status);
        return;
      }
      const data = await res.json();
      const signals: any[] = data.signals ?? data.trades ?? [];

      for (const s of signals) {
        const time = s.timestamp ?? Math.floor(new Date(s.placed_at ?? s.created_at).getTime() / 1000);
        if (s.action === 'BUY' || s.action === 'SELL') {
          this.onSignal({
            symbol:      s.symbol,
            action:      s.action,
            confidence:  s.confidence ?? 0,
            reason:      s.reason ?? '',
            time,
            stopLoss:    parseFloat(s.stop_loss ?? 0),
            takeProfit1: parseFloat(s.take_profit_1 ?? 0),
          });
        }
        if (s.metadata?.tp1_hit) {
          this.onTPHit({ symbol: s.symbol, side: s.action === 'BUY' ? 'LONG' : 'SHORT', entryPrice: 0, stopLoss: 0, takeProfit1: 0, takeProfit2: 0 }, 1, parseFloat(s.take_profit_1), time);
        }
        if (s.metadata?.sl_hit) {
          this.onSLHit({ symbol: s.symbol, side: s.action === 'BUY' ? 'LONG' : 'SHORT', entryPrice: 0, stopLoss: parseFloat(s.stop_loss), takeProfit1: 0, takeProfit2: 0 }, parseFloat(s.stop_loss), time);
        }
      }
      console.log(`[ChartMarkers] Loaded ${signals.length} historical signals`);
    } catch (e) {
      console.warn('[ChartMarkers] loadHistoricalSignals error:', e);
    }
  }

  /**
   * Remove all chart shapes for a specific symbol.
   */
  clearBySymbol(symbol: string): void {
    const chart = this._activeChart();
    if (!chart) return;
    for (const [key, ids] of this._shapeIds.entries()) {
      if (key.startsWith(`${symbol}__`)) {
        ids.forEach(id => {
          try { chart.removeEntity(id); } catch {}
        });
        this._shapeIds.delete(key);
      }
    }
  }

  /**
   * Remove all shapes for a specific order/signal ID.
   */
  removeShapes(symbol: string, id: string): void {
    const chart = this._activeChart();
    if (!chart) return;
    const key = `${symbol}__${id}`;
    (this._shapeIds.get(key) ?? []).forEach(sid => {
      try { chart.removeEntity(sid); } catch {}
    });
    this._shapeIds.delete(key);
  }

  /** Total number of shapes currently on the chart. */
  getShapeCount(): number {
    let total = 0;
    this._shapeIds.forEach(ids => { total += ids.length; });
    return total;
  }

  // ── Private helpers ────────────────────────────────────────────────────────

  private _activeChart(): any | null {
    try { return this._widget.activeChart(); } catch { return null; }
  }

  private _createArrowShape(
    chart:   any,
    symbol:  string,
    time:    number,
    price:   number,
    isBuy:   boolean,
    color:   string,
    tooltip: string,
    id:      string,
  ): void {
    try {
      const shape = chart.createShape(
        { time, price },
        {
          shape:            isBuy ? 'arrow_up' : 'arrow_down',
          lock:             true,
          disableSelection: false,
          overrides: {
            color,
            fontsize:  12,
            bold:      false,
            text:      tooltip,
            textColor: color,
          },
        },
      );
      this._addShapeId(symbol, id, shape);
    } catch (e) {
      console.warn('[ChartMarkers] createShape (arrow) failed:', e);
    }
  }

  private _createTextShape(
    chart:    any,
    symbol:   string,
    time:     number,
    price:    number,
    text:     string,
    color:    string,
    position: 'above' | 'below',
    id:       string,
  ): void {
    try {
      const shape = chart.createShape(
        { time, price },
        {
          shape:   'note',
          lock:    true,
          overrides: {
            markerColor:   color,
            textColor:     color,
            fontSize:      11,
            text,
            labelFontSize: 11,
          },
        },
      );
      this._addShapeId(symbol, id, shape);
    } catch (e) {
      console.warn('[ChartMarkers] createShape (note) failed:', e);
    }
  }

  private _createPriceLine(
    chart:  any,
    symbol: string,
    price:  number,
    color:  string,
    text:   string,
    id:     string,
  ): void {
    try {
      const shape = chart.createShape(
        { price },
        {
          shape: 'horizontal_line',
          lock:  true,
          overrides: {
            linecolor:  color,
            linewidth:  1,
            linestyle:  2,      // dashed
            showLabel:  true,
            text,
            textcolor:  color,
            fontsize:   10,
          },
        },
      );
      this._addShapeId(symbol, id, shape);
    } catch (e) {
      console.warn('[ChartMarkers] createShape (h-line) failed:', e);
    }
  }

  private _addShapeId(symbol: string, id: string, shapeId: any): void {
    const key = `${symbol}__${id}`;
    if (!this._shapeIds.has(key)) this._shapeIds.set(key, []);
    this._shapeIds.get(key)!.push(shapeId);
  }
}


/**
 * wireChartMarkersToWebSocket
 *
 * Creates a ChartMarkerManager, connects to the Nexus WebSocket backend,
 * and wires all relevant events to chart markers.
 *
 * Events handled:
 *   order_filled       → onOrderFilled()
 *   signal_created     → onSignal()
 *   tp1_hit / tp2_hit  → onTPHit()
 *   sl_hit             → onSLHit()
 *   breakeven          → onBreakevenMove()
 *   risk_event         → onRiskEvent() [CRITICAL/WARNING routing]
 *
 * @param widget  IChartingLibraryWidget instance
 * @param wsUrl   WebSocket URL, e.g. "ws://localhost:8000/api/v1/ws"
 * @param apiBase REST API base, e.g. "http://localhost:8000/api/v1"
 * @param apiKey  Optional X-API-Key for authenticated historical fetch
 * @returns cleanup function — call to disconnect and stop reconnecting
 *
 * Usage:
 *   widget.onChartReady(async () => {
 *     const cleanup = wireChartMarkersToWebSocket(
 *       widget,
 *       'ws://localhost:8000/api/v1/ws',
 *       'http://localhost:8000/api/v1',
 *     );
 *     // To clean up: cleanup();
 *   });
 */
export function wireChartMarkersToWebSocket(
  widget:  any,
  wsUrl:   string,
  apiBase?: string,
  apiKey?:  string,
): () => void {
  const markers = new ChartMarkerManager(widget);
  let ws:               WebSocket | null = null;
  let reconnectTimer:   ReturnType<typeof setTimeout> | null = null;
  let reconnectMs     = 1_000;
  const MAX_RECONNECT = 30_000;
  let stopped         = false;

  // Load historical signals once on ready
  if (apiBase) {
    markers.loadHistoricalSignals(apiBase, apiKey).catch(console.warn);
  }

  function connect(): void {
    if (stopped) return;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('[ChartMarkers] WebSocket connected');
      reconnectMs = 1_000;
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    };

    ws.onmessage = (event: MessageEvent) => {
      try { handleEvent(JSON.parse(event.data as string)); } catch {}
    };

    ws.onclose = () => {
      if (stopped) return;
      console.log(`[ChartMarkers] WS closed — reconnecting in ${reconnectMs}ms`);
      reconnectTimer = setTimeout(connect, reconnectMs);
      reconnectMs = Math.min(reconnectMs * 2, MAX_RECONNECT);
    };

    ws.onerror = (err) => {
      console.warn('[ChartMarkers] WS error', err);
      ws?.close();
    };
  }

  function handleEvent(msg: any): void {
    const { event, payload } = msg;
    if (!event || !payload) return;

    switch (event) {
      case 'order_filled': {
        markers.onOrderFilled({
          symbol:   payload.symbol,
          side:     payload.side,
          price:    parseFloat(payload.avg_fill_price ?? payload.price) || 0,
          quantity: parseFloat(payload.quantity ?? payload.qty) || 0,
          time:     payload.time ?? Math.floor(Date.now() / 1000),
          orderId:  String(payload.exchange_order_id ?? Date.now()),
          dryRun:   payload.dry_run === true,
        });
        break;
      }

      case 'signal_created': {
        if (payload.action === 'HOLD') break;
        markers.onSignal({
          symbol:      payload.symbol,
          action:      payload.action,
          confidence:  payload.confidence ?? 0,
          reason:      payload.reason ?? '',
          time:        payload.timestamp ?? Math.floor(Date.now() / 1000),
          stopLoss:    parseFloat(payload.stop_loss ?? 0),
          takeProfit1: parseFloat(payload.take_profit_1 ?? 0),
        });
        break;
      }

      case 'tp1_hit': {
        const pos = payload.position ?? {};
        markers.onTPHit(
          {
            symbol:      payload.symbol,
            side:        pos.side ?? 'LONG',
            entryPrice:  parseFloat(pos.entry_price ?? 0),
            stopLoss:    parseFloat(pos.stop_loss ?? 0),
            takeProfit1: parseFloat(pos.take_profit_1 ?? 0),
            takeProfit2: parseFloat(pos.take_profit_2 ?? 0),
          },
          1,
          parseFloat(payload.price ?? 0),
          payload.time ?? Math.floor(Date.now() / 1000),
        );
        break;
      }

      case 'tp2_hit': {
        const pos2 = payload.position ?? {};
        markers.onTPHit(
          {
            symbol:      payload.symbol,
            side:        pos2.side ?? 'LONG',
            entryPrice:  parseFloat(pos2.entry_price ?? 0),
            stopLoss:    parseFloat(pos2.stop_loss ?? 0),
            takeProfit1: parseFloat(pos2.take_profit_1 ?? 0),
            takeProfit2: parseFloat(pos2.take_profit_2 ?? 0),
          },
          2,
          parseFloat(payload.price ?? 0),
          payload.time ?? Math.floor(Date.now() / 1000),
        );
        break;
      }

      case 'sl_hit': {
        const pos3 = payload.position ?? {};
        markers.onSLHit(
          {
            symbol:      payload.symbol,
            side:        pos3.side ?? 'LONG',
            entryPrice:  parseFloat(pos3.entry_price ?? 0),
            stopLoss:    parseFloat(pos3.stop_loss ?? 0),
            takeProfit1: parseFloat(pos3.take_profit_1 ?? 0),
            takeProfit2: parseFloat(pos3.take_profit_2 ?? 0),
          },
          parseFloat(payload.price ?? 0),
          payload.time ?? Math.floor(Date.now() / 1000),
        );
        break;
      }

      case 'breakeven': {
        markers.onBreakevenMove(
          payload.symbol,
          parseFloat(payload.price ?? 0),
          payload.time ?? Math.floor(Date.now() / 1000),
        );
        break;
      }

      case 'risk_event': {
        markers.onRiskEvent({
          symbol:   payload.symbol ?? '',
          severity: payload.severity === 'CRITICAL' ? 'CRITICAL' : 'WARNING',
          detail:   payload.detail ?? payload.event ?? '',
          time:     payload.time ?? Math.floor(Date.now() / 1000),
        });
        break;
      }
    }
  }

  connect();

  // Cleanup function
  return () => {
    stopped = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    ws?.close();
  };
}
