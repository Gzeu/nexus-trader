/**
 * chart_markers.ts – TradingView Chart Markers for Nexus Trader
 *
 * Renders entry, exit, SL hit, TP hit, and signal markers on the chart
 * using the TradingView Charting Library's createShape() / createExecutionShape() API.
 *
 * Docs: https://www.tradingview.com/charting-library-docs/latest/api/interfaces/Charting_Library.IChartingLibraryWidget
 *
 * Usage:
 *   import { ChartMarkerManager } from './chart_markers';
 *   const markers = new ChartMarkerManager(widget);
 *   markers.onOrderFilled(order);
 *   markers.onTPHit(position, tpLevel, price, time);
 *   markers.onSLHit(position, price, time);
 *   markers.onSignal(signal);
 */

export interface MarkerOrder {
  symbol:     string;
  side:       'BUY' | 'SELL';
  price:      number;
  quantity:   number;
  time:       number;  // Unix timestamp seconds
  orderId:    string;
  dryRun?:    boolean;
}

export interface MarkerPosition {
  symbol:     string;
  side:       'LONG' | 'SHORT';
  entryPrice: number;
  stopLoss:   number;
  takeProfit1: number;
  takeProfit2: number;
}

export interface MarkerSignal {
  symbol:     string;
  action:     'BUY' | 'SELL' | 'HOLD';
  confidence: number;
  reason:     string;
  time:       number;
  stopLoss:   number;
  takeProfit1: number;
}

// TradingView shape color palette aligned with Nexus design system
const COLORS = {
  buy:         '#01696f',  // --color-primary (Hydra Teal)
  sell:        '#a12c7b',  // --color-error
  tp:          '#437a22',  // --color-success
  sl:          '#a13544',  // --color-notification
  signal_buy:  '#006494',  // --color-blue
  signal_sell: '#7a39bb',  // --color-purple
  dryRun:      '#d19900',  // --color-gold
  breakeven:   '#da7101',  // --color-orange
} as const;


export class ChartMarkerManager {
  private _widget: any;  // IChartingLibraryWidget
  private _shapeIds: Map<string, string[]> = new Map();

  constructor(widget: any) {
    this._widget = widget;
  }

  /**
   * Called when an order is filled (entry).
   * Renders an entry arrow on the chart.
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
      // createExecutionShape is the correct TV Charting Library API for trade arrows
      const shapeId = chart.createExecutionShape()
        .setTime(order.time)
        .setDirection(isBuy ? 'buy' : 'sell')
        .setArrowHeight(15)
        .setArrowSpacing(5)
        .setArrowColor(color)
        .setTooltip(text)
        .setTextColor(color)
        .setText(text);

      this._addShapeId(order.orderId, shapeId);
    } catch (e) {
      console.warn('[ChartMarkers] createExecutionShape failed:', e);
      // Fallback: use createShape with arrow type
      this._createArrowShape(chart, order.time, order.price, isBuy, color, text, order.orderId);
    }
  }

  /**
   * Renders TP1 or TP2 hit marker (green checkmark above/below candle).
   */
  onTPHit(
    position:  MarkerPosition,
    tpLevel:   1 | 2,
    price:     number,
    time:      number,
  ): void {
    const chart = this._activeChart();
    if (!chart) return;

    const isLong = position.side === 'LONG';
    const label  = `TP${tpLevel} ${isLong ? '✓' : '✓'} @ ${price.toFixed(2)}`;

    this._createTextShape(chart, time, price, label, COLORS.tp, isLong ? 'above' : 'below');
  }

  /**
   * Renders SL hit marker (red X).
   */
  onSLHit(
    position: MarkerPosition,
    price:    number,
    time:     number,
  ): void {
    const chart = this._activeChart();
    if (!chart) return;

    const isLong = position.side === 'LONG';
    const label  = `SL HIT @ ${price.toFixed(2)}`;

    this._createTextShape(chart, time, price, label, COLORS.sl, isLong ? 'below' : 'above');
  }

  /**
   * Renders a signal arrow (before entry, shows the strategy signal).
   * Useful in dry-run / review mode.
   */
  onSignal(signal: MarkerSignal): void {
    const chart = this._activeChart();
    if (!chart) return;

    if (signal.action === 'HOLD') return;

    const isBuy  = signal.action === 'BUY';
    const color  = isBuy ? COLORS.signal_buy : COLORS.signal_sell;
    const label  = `${signal.action} ${(signal.confidence * 100).toFixed(0)}% | ${signal.reason.slice(0, 40)}`;

    this._createArrowShape(
      chart,
      signal.time,
      isBuy ? signal.stopLoss : signal.takeProfit1,
      isBuy,
      color,
      label,
      `sig_${signal.symbol}_${signal.time}`,
    );

    // Draw SL and TP horizontal lines
    this._createPriceLine(chart, signal.stopLoss,    COLORS.sl,  `SL ${signal.stopLoss.toFixed(2)}`);
    this._createPriceLine(chart, signal.takeProfit1, COLORS.tp,  `TP1 ${signal.takeProfit1.toFixed(2)}`);
  }

  /**
   * Renders breakeven move marker (SL moved to entry after TP1).
   */
  onBreakeven(symbol: string, price: number, time: number): void {
    const chart = this._activeChart();
    if (!chart) return;
    this._createTextShape(chart, time, price, `BE ↑ ${price.toFixed(2)}`, COLORS.breakeven, 'below');
  }

  /**
   * Remove all shapes created by this manager for a given order/signal ID.
   */
  removeShapes(id: string): void {
    const chart = this._activeChart();
    if (!chart) return;
    const ids = this._shapeIds.get(id) || [];
    ids.forEach(sid => {
      try { chart.removeEntity(sid); } catch {}
    });
    this._shapeIds.delete(id);
  }

  // ── Private helpers ──────────────────────────────────────────────────────

  private _activeChart(): any | null {
    try {
      return this._widget.activeChart();
    } catch {
      return null;
    }
  }

  private _createArrowShape(
    chart:    any,
    time:     number,
    price:    number,
    isBuy:    boolean,
    color:    string,
    tooltip:  string,
    id:       string,
  ): void {
    try {
      const shape = chart.createShape(
        { time, price },
        {
          shape:       isBuy ? 'arrow_up' : 'arrow_down',
          lock:        true,
          disableSelection: false,
          overrides: {
            color:       color,
            fontsize:    12,
            bold:        false,
            text:        tooltip,
            textColor:   color,
          },
        }
      );
      this._addShapeId(id, shape);
    } catch (e) {
      console.warn('[ChartMarkers] createShape failed:', e);
    }
  }

  private _createTextShape(
    chart:     any,
    time:      number,
    price:     number,
    text:      string,
    color:     string,
    position:  'above' | 'below',
  ): void {
    try {
      chart.createShape(
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
        }
      );
    } catch (e) {
      console.warn('[ChartMarkers] createShape (note) failed:', e);
    }
  }

  private _createPriceLine(
    chart: any,
    price: number,
    color: string,
    text:  string,
  ): void {
    try {
      chart.createShape(
        { price },
        {
          shape: 'horizontal_line',
          lock:  true,
          overrides: {
            linecolor:    color,
            linewidth:    1,
            linestyle:    2,  // dashed
            showLabel:    true,
            text,
            textcolor:    color,
            fontsize:     10,
          },
        }
      );
    } catch (e) {
      console.warn('[ChartMarkers] createShape (h-line) failed:', e);
    }
  }

  private _addShapeId(key: string, shapeId: any): void {
    if (!this._shapeIds.has(key)) {
      this._shapeIds.set(key, []);
    }
    this._shapeIds.get(key)!.push(shapeId);
  }
}


/**
 * Factory: creates a ChartMarkerManager and wires it to WebSocket events.
 *
 * @param widget  TradingView IChartingLibraryWidget instance
 * @param wsUrl   WebSocket URL for Nexus backend (e.g. ws://localhost:8000/api/v1/ws)
 *
 * Usage:
 *   const cleanup = wireChartMarkersToWebSocket(widget, 'ws://localhost:8000/api/v1/ws');
 *   // call cleanup() to disconnect
 */
export function wireChartMarkersToWebSocket(
  widget: any,
  wsUrl:  string,
): () => void {
  const markers = new ChartMarkerManager(widget);
  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  function connect(): void {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('[ChartMarkers] WebSocket connected');
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data);
        handleEvent(msg);
      } catch {}
    };

    ws.onclose = () => {
      console.log('[ChartMarkers] WebSocket closed — reconnecting in 3s');
      reconnectTimer = setTimeout(connect, 3000);
    };

    ws.onerror = (err) => {
      console.warn('[ChartMarkers] WebSocket error', err);
    };
  }

  function handleEvent(msg: any): void {
    const { event, payload } = msg;
    if (!event || !payload) return;

    switch (event) {
      case 'order_filled': {
        const order: MarkerOrder = {
          symbol:   payload.symbol,
          side:     payload.side,
          price:    parseFloat(payload.avg_price) || 0,
          quantity: parseFloat(payload.quantity)  || 0,
          time:     Math.floor(Date.now() / 1000),
          orderId:  payload.exchange_order_id || String(Date.now()),
          dryRun:   payload.dry_run === true,
        };
        markers.onOrderFilled(order);
        break;
      }

      case 'tp1_hit': {
        // payload: { symbol, price, position: MarkerPosition }
        if (payload.position) {
          markers.onTPHit(payload.position, 1, parseFloat(payload.price), Math.floor(Date.now() / 1000));
        }
        break;
      }

      case 'tp2_hit': {
        if (payload.position) {
          markers.onTPHit(payload.position, 2, parseFloat(payload.price), Math.floor(Date.now() / 1000));
        }
        break;
      }

      case 'sl_hit': {
        if (payload.position) {
          markers.onSLHit(payload.position, parseFloat(payload.price), Math.floor(Date.now() / 1000));
        }
        break;
      }

      case 'signal_created': {
        const signal: MarkerSignal = {
          symbol:      payload.symbol,
          action:      payload.action,
          confidence:  payload.confidence,
          reason:      payload.reason || '',
          time:        Math.floor(Date.now() / 1000),
          stopLoss:    payload.stop_loss,
          takeProfit1: payload.take_profit_1,
        };
        markers.onSignal(signal);
        break;
      }

      case 'tp1_hit_breakeven': {
        if (payload.symbol) {
          markers.onBreakeven(payload.symbol, parseFloat(payload.new_sl || 0), Math.floor(Date.now() / 1000));
        }
        break;
      }
    }
  }

  connect();

  // Return cleanup function
  return () => {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (ws) { ws.onclose = null; ws.close(); }
  };
}
