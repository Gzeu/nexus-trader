/**
 * markers.ts — TradingView Charting Library algo markers integration.
 *
 * Renders BUY/SELL/SL/TP/CLOSE/RISK markers on the main candlestick series
 * using the ISeriesApi.setMarkers() API.
 *
 * Docs: https://www.tradingview.com/charting-library-docs/latest/api/interfaces/Charting_Library.ISeriesApi
 * Quick-start: https://www.tradingview.com/charting-library-docs/latest/quick-start/
 */

import type {
  IChartingLibraryWidget,
  ISeriesApi,
  SeriesMarker,
  Time,
} from "../charting_library/charting_library";

// ─── Types ───────────────────────────────────────────────────────────────────────────────

export type MarkerKind =
  | "entry_long"
  | "entry_short"
  | "tp1"
  | "tp2"
  | "sl_hit"
  | "breakeven"
  | "close_signal"
  | "risk_event";

export interface AlgoMarker {
  kind: MarkerKind;
  time: number;        // UNIX seconds
  price?: number;
  symbol?: string;
  label?: string;
  tooltip?: string;
}

export interface BackendSignal {
  symbol: string;
  action: "BUY" | "SELL" | "CLOSE" | "REVERSE" | "HOLD";
  entry_type: "market" | "limit";
  entry_price: number | null;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
  timeframe: string;
  timestamp: number;           // UNIX seconds
  metadata?: {
    tp1_hit?: boolean;
    tp2_hit?: boolean;
    sl_hit?: boolean;
    breakeven_moved?: boolean;
    close_reason?: string;
    risk_event?: string;
    severity?: string;
    detail?: string;
  };
}

// ─── Marker config per kind ───────────────────────────────────────────────────────────

const MARKER_CONFIG: Record<
  MarkerKind,
  {
    position: "aboveBar" | "belowBar" | "inBar";
    shape: "arrowUp" | "arrowDown" | "circle" | "square";
    color: string;
    size: number;
    defaultLabel: string;
  }
> = {
  entry_long:   { position: "belowBar", shape: "arrowUp",   color: "#26a69a", size: 2, defaultLabel: "L"   },
  entry_short:  { position: "aboveBar", shape: "arrowDown",  color: "#ef5350", size: 2, defaultLabel: "S"   },
  tp1:          { position: "aboveBar", shape: "circle",     color: "#66bb6a", size: 1, defaultLabel: "TP1" },
  tp2:          { position: "aboveBar", shape: "circle",     color: "#81c784", size: 1, defaultLabel: "TP2" },
  sl_hit:       { position: "belowBar", shape: "square",     color: "#f44336", size: 1, defaultLabel: "SL"  },
  breakeven:    { position: "belowBar", shape: "circle",     color: "#ffa726", size: 1, defaultLabel: "BE"  },
  close_signal: { position: "aboveBar", shape: "circle",     color: "#ab47bc", size: 1, defaultLabel: "X"   },
  risk_event:   { position: "aboveBar", shape: "square",     color: "#ff1744", size: 2, defaultLabel: "\u26a0"  },
};

// ─── Signal → Markers conversion ─────────────────────────────────────────────────────────────

export function signalToMarkers(s: BackendSignal): AlgoMarker[] {
  const markers: AlgoMarker[] = [];
  const meta = s.metadata ?? {};

  if (s.action === "BUY") {
    markers.push({
      kind: "entry_long",
      time: s.timestamp,
      price: s.entry_price ?? undefined,
      symbol: s.symbol,
      label: "L",
      tooltip: `Long @ ${s.entry_price ?? "market"}  SL=${s.stop_loss}  TP1=${s.take_profit_1}`,
    });
  } else if (s.action === "SELL") {
    markers.push({
      kind: "entry_short",
      time: s.timestamp,
      price: s.entry_price ?? undefined,
      symbol: s.symbol,
      label: "S",
      tooltip: `Short @ ${s.entry_price ?? "market"}  SL=${s.stop_loss}  TP1=${s.take_profit_1}`,
    });
  } else if (s.action === "CLOSE") {
    markers.push({
      kind: "close_signal",
      time: s.timestamp,
      symbol: s.symbol,
      label: "X",
      tooltip: `Close: ${meta.close_reason ?? "signal"}`,
    });
  }

  if (meta.tp1_hit) markers.push({ kind: "tp1", time: s.timestamp, price: s.take_profit_1, symbol: s.symbol, label: "TP1", tooltip: `TP1 hit @ ${s.take_profit_1}` });
  if (meta.tp2_hit) markers.push({ kind: "tp2", time: s.timestamp, price: s.take_profit_2, symbol: s.symbol, label: "TP2", tooltip: `TP2 hit @ ${s.take_profit_2}` });
  if (meta.sl_hit)  markers.push({ kind: "sl_hit", time: s.timestamp, price: s.stop_loss, symbol: s.symbol, label: "SL", tooltip: `SL hit @ ${s.stop_loss}` });
  if (meta.breakeven_moved) markers.push({ kind: "breakeven", time: s.timestamp, symbol: s.symbol, label: "BE", tooltip: "SL moved to breakeven after TP1" });
  if (meta.risk_event) markers.push({ kind: "risk_event", time: s.timestamp, symbol: s.symbol, label: "\u26a0", tooltip: `Risk: ${meta.risk_event}` });

  return markers;
}

// ─── AlgoMarkerManager ───────────────────────────────────────────────────────────────────────

export class AlgoMarkerManager {
  private _series: ISeriesApi<"Candlestick"> | null = null;
  private _pending: AlgoMarker[] = [];
  private _applied: SeriesMarker<Time>[] = [];

  /**
   * Call after widget.onChartReady() and the main candlestick series is created.
   * Example:
   *   widget.onChartReady(() => {
   *     const series = widget.activeChart().series();  // or your reference
   *     markerManager.attachSeries(series);
   *   });
   */
  attachSeries(series: ISeriesApi<"Candlestick">): void {
    this._series = series;
    this._pending.forEach((m) => this._apply(m));
    this._pending = [];
  }

  addMarker(marker: AlgoMarker): void {
    if (!this._series) { this._pending.push(marker); return; }
    this._apply(marker);
  }

  addMarkers(markers: AlgoMarker[]): void {
    markers.forEach((m) => this.addMarker(m));
  }

  clearMarkers(): void {
    this._applied = [];
    this._series?.setMarkers([]);
  }

  loadFromSignals(signals: BackendSignal[]): void {
    this.clearMarkers();
    this.addMarkers(signals.flatMap(signalToMarkers));
  }

  private _apply(marker: AlgoMarker): void {
    if (!this._series) return;
    const cfg = MARKER_CONFIG[marker.kind];
    const m: SeriesMarker<Time> = {
      time: marker.time as Time,
      position: cfg.position,
      shape: cfg.shape,
      color: cfg.color,
      text: marker.label ?? cfg.defaultLabel,
      size: cfg.size,
      id: `${marker.kind}_${marker.time}_${marker.symbol ?? ""}`,
    };
    this._applied = [
      ...this._applied.filter((x) => (x as any).id !== m.id),
      m,
    ].sort((a, b) => (a.time as number) - (b.time as number));
    this._series.setMarkers(this._applied);
  }
}

// ─── AlgoMarkerWsFeed ────────────────────────────────────────────────────────────────────────

/**
 * Connects to the nexus-trader WebSocket and feeds live markers to AlgoMarkerManager.
 *
 * Usage:
 *   const manager = new AlgoMarkerManager();
 *   const feed = new AlgoMarkerWsFeed(manager, "ws://localhost:8000/ws");
 *   feed.connect();
 *
 *   // After chart ready:
 *   widget.onChartReady(() => manager.attachSeries(mainSeries));
 */
export class AlgoMarkerWsFeed {
  private _manager: AlgoMarkerManager;
  private _url: string;
  private _ws: WebSocket | null = null;
  private _reconnectMs = 3_000;
  private _destroyed = false;

  constructor(manager: AlgoMarkerManager, wsUrl: string) {
    this._manager = manager;
    this._url = wsUrl;
  }

  connect(): void {
    if (this._destroyed) return;
    this._ws = new WebSocket(this._url);

    this._ws.onopen = () => console.log("[AlgoMarkerWsFeed] connected");

    this._ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data as string) as {
          event_type: string;
          payload: BackendSignal & { severity?: string; detail?: string };
        };
        this._handle(event);
      } catch (e) {
        console.error("[AlgoMarkerWsFeed] parse error", e);
      }
    };

    this._ws.onclose = () => {
      if (!this._destroyed) {
        console.warn(`[AlgoMarkerWsFeed] disconnected — retry in ${this._reconnectMs}ms`);
        setTimeout(() => this.connect(), this._reconnectMs);
      }
    };

    this._ws.onerror = (e) => console.error("[AlgoMarkerWsFeed] error", e);
  }

  disconnect(): void {
    this._destroyed = true;
    this._ws?.close();
    this._ws = null;
  }

  private _handle(event: { event_type: string; payload: BackendSignal & { severity?: string; detail?: string } }): void {
    const { event_type, payload } = event;
    const now = Math.floor(Date.now() / 1000);

    switch (event_type) {
      case "signal_created":
      case "order_filled":
        this._manager.addMarkers(signalToMarkers(payload));
        break;

      case "tp_hit":
        this._manager.addMarker({
          kind: payload.metadata?.tp2_hit ? "tp2" : "tp1",
          time: payload.timestamp ?? now,
          symbol: payload.symbol,
          label: payload.metadata?.tp2_hit ? "TP2" : "TP1",
        });
        break;

      case "sl_hit":
        this._manager.addMarker({
          kind: "sl_hit",
          time: payload.timestamp ?? now,
          symbol: payload.symbol,
          label: "SL",
          tooltip: `SL hit @ ${payload.stop_loss}`,
        });
        break;

      case "risk_event":
        if (payload.severity === "CRITICAL" || payload.severity === "WARNING") {
          this._manager.addMarker({
            kind: "risk_event",
            time: payload.timestamp ?? now,
            symbol: payload.symbol ?? "",
            label: "\u26a0",
            tooltip: payload.detail ?? "Risk event",
          });
        }
        break;

      case "position_closed":
        this._manager.addMarker({
          kind: "close_signal",
          time: payload.timestamp ?? now,
          symbol: payload.symbol,
          label: "X",
        });
        break;
    }
  }
}

// ─── Integration guide (for broker_adapter/tradingview_broker.ts) ──────────────────
//
// import { AlgoMarkerManager, AlgoMarkerWsFeed } from "../frontend/charting/markers";
//
// export class TradingSystemBroker implements IBrokerTerminal {
//   private _markerManager: AlgoMarkerManager;
//   private _markerFeed: AlgoMarkerWsFeed;
//
//   constructor(host: IBrokerConnectionAdapterHost, widget: IChartingLibraryWidget) {
//     this._markerManager = new AlgoMarkerManager();
//     this._markerFeed = new AlgoMarkerWsFeed(
//       this._markerManager,
//       `ws://${window.location.hostname}:8000/ws`,
//     );
//     this._markerFeed.connect();
//
//     widget.onChartReady(() => {
//       // Get the main series reference from your chart setup
//       // (store it when you create the candlestick series)
//       if (this._mainSeries) {
//         this._markerManager.attachSeries(this._mainSeries);
//         // Load historical signals on chart ready
//         fetch("/api/v1/signals?limit=500")
//           .then((r) => r.json())
//           .then((signals) => this._markerManager.loadFromSignals(signals));
//       }
//     });
//   }
// }
