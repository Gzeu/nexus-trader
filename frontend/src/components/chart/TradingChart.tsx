'use client'

/**
 * TradingChart.tsx — TradingView Charting Library integration.
 *
 * IMPORTANT: The TradingView Charting Library (charting_library/) must be
 * placed in /public/charting_library/ and is NOT included in this repo
 * (requires a TradingView license). Download from:
 * https://www.tradingview.com/HTML5-stock-forex-bitcoin-charting-library/
 *
 * Flow:
 * 1. widget.js loaded from /charting_library/charting_library.js
 * 2. Datafeed wired to Binance REST (OHLCV) + WebSocket (live ticks)
 * 3. Broker terminal wired to TradingSystemBroker (tradingview_broker.ts)
 * 4. On signal events via WS → chart marks updated via createShape()
 */

import { useEffect, useRef, useState } from 'react'
import { wsClient } from '@/lib/websocket'
import { config } from '@/lib/config'
import { ChartSkeleton } from './ChartSkeleton'

declare global {
  interface Window {
    TradingView: {
      widget: new (config: Record<string, unknown>) => IChartingLibraryWidget
    }
  }
}

interface IChartingLibraryWidget {
  onChartReady(cb: () => void): void
  remove(): void
  chart(): IChartApi
  activeChart(): IChartApi
}

interface IChartApi {
  setSymbol(symbol: string, interval: string, cb?: () => void): void
  createShape(point: { time: number; price: number }, options: Record<string, unknown>): string | null
  setChartType(type: number): void
}

// ── Binance Datafeed ─────────────────────────────────────────────────────────
// Implements the minimal UDF-compatible datafeed for TradingView.

const RESOLUTION_MAP: Record<string, string> = {
  '1': '1m', '3': '3m', '5': '5m', '15': '15m', '30': '30m',
  '60': '1h', '240': '4h', 'D': '1d', '1D': '1d',
}

function makeBinanceDatafeed() {
  const BASE = 'https://api.binance.com/api/v3'

  return {
    onReady(cb: (cfg: object) => void) {
      setTimeout(() => cb({
        supported_resolutions: ['1','3','5','15','30','60','240','D'],
        supports_marks: true,
        supports_timescale_marks: true,
      }), 0)
    },
    searchSymbols(
      _userInput: string,
      _exchange: string,
      _symbolType: string,
      onResult: (s: object[]) => void
    ) { onResult([]) },
    resolveSymbol(
      symbolName: string,
      onResolve: (s: object) => void,
      _onError: (e: string) => void
    ) {
      onResolve({
        name: symbolName,
        description: symbolName,
        type: 'crypto',
        session: '24x7',
        timezone: 'Etc/UTC',
        exchange: 'BINANCE',
        minmov: 1,
        pricescale: 100,
        has_intraday: true,
        has_daily: true,
        supported_resolutions: ['1','3','5','15','30','60','240','D'],
        volume_precision: 4,
        data_status: 'streaming',
      })
    },
    async getBars(
      symbolInfo: { name: string },
      resolution: string,
      periodParams: { from: number; to: number; countBack: number },
      onResult: (bars: object[], meta: object) => void,
      onError: (e: string) => void
    ) {
      const interval = RESOLUTION_MAP[resolution] ?? '15m'
      const limit = Math.min(periodParams.countBack, 1000)
      const url = `${BASE}/klines?symbol=${symbolInfo.name}&interval=${interval}&limit=${limit}&endTime=${periodParams.to * 1000}`
      try {
        const res  = await fetch(url)
        const data = await res.json()
        const bars = (data as number[][]).map(k => ({
          time:   k[0],
          open:   parseFloat(String(k[1])),
          high:   parseFloat(String(k[2])),
          low:    parseFloat(String(k[3])),
          close:  parseFloat(String(k[4])),
          volume: parseFloat(String(k[5])),
        }))
        onResult(bars, { noData: bars.length === 0 })
      } catch (e) {
        onError(String(e))
      }
    },
    subscribeBars(
      symbolInfo: { name: string },
      resolution: string,
      onRealtimeCallback: (bar: object) => void,
      _subscriberUID: string
    ) {
      const interval = RESOLUTION_MAP[resolution] ?? '15m'
      const stream   = `${symbolInfo.name.toLowerCase()}@kline_${interval}`
      const ws = new WebSocket(`wss://stream.binance.com:9443/ws/${stream}`)
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data)
        const k   = msg.k
        onRealtimeCallback({
          time:   k.t,
          open:   parseFloat(k.o),
          high:   parseFloat(k.h),
          low:    parseFloat(k.l),
          close:  parseFloat(k.c),
          volume: parseFloat(k.v),
        })
      }
      ;(subscribeBars as Record<string, WebSocket>)[_subscriberUID] = ws
    },
    unsubscribeBars(_subscriberUID: string) {
      const ws = (subscribeBars as Record<string, WebSocket>)[_subscriberUID]
      ws?.close()
    },
  }
}

// eslint-disable-next-line prefer-const
let subscribeBars: Record<string, WebSocket> = {}

// ── Component ────────────────────────────────────────────────────────────────

export default function TradingChart({
  symbol    = 'BTCUSDT',
  timeframe = '15',
}: {
  symbol?:    string
  timeframe?: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const widgetRef    = useRef<IChartingLibraryWidget | null>(null)
  const [tvReady, setTvReady] = useState(false)
  const [libLoaded, setLibLoaded] = useState(false)

  // Load charting_library.js from /public once
  useEffect(() => {
    if (document.getElementById('tv-lib')) { setLibLoaded(true); return }
    const script = document.createElement('script')
    script.id  = 'tv-lib'
    script.src = '/charting_library/charting_library.js'
    script.onload = () => setLibLoaded(true)
    script.onerror = () => console.warn(
      '[NexusChart] charting_library.js not found. Place TradingView library in /public/charting_library/'
    )
    document.head.appendChild(script)
  }, [])

  // Init widget once library is loaded
  useEffect(() => {
    if (!libLoaded || !containerRef.current || !window.TradingView) return

    const datafeed = makeBinanceDatafeed()

    // Lazy import the broker adapter
    import('../../../broker_adapter/tradingview_broker').then(({ TradingSystemBroker }) => {
      // Dummy host for standalone usage; in real TV setup widget provides the host
      const brokerFactory = (host: Parameters<typeof TradingSystemBroker>[0]) =>
        new TradingSystemBroker(host, {
          apiBase:    config.apiBase,
          wsUrl:      config.wsUrl,
          apiKey:     config.apiKey,
          marketMode: config.marketMode,
          debug:      process.env.NODE_ENV === 'development',
        })

      const widget = new window.TradingView.widget({
        container:          containerRef.current!,
        library_path:       '/charting_library/',
        datafeed,
        symbol,
        interval:           timeframe,
        locale:             'en',
        theme:              'Dark',
        timezone:           'Etc/UTC',
        fullscreen:         false,
        autosize:           true,
        disabled_features:  ['header_saveload', 'use_localstorage_for_settings'],
        enabled_features:   ['study_templates', 'side_toolbar_in_fullscreen_mode'],
        overrides: {
          'mainSeriesProperties.candleStyle.upColor':      '#6daa45',
          'mainSeriesProperties.candleStyle.downColor':    '#d163a7',
          'mainSeriesProperties.candleStyle.borderUpColor':'#6daa45',
          'mainSeriesProperties.candleStyle.borderDownColor':'#d163a7',
          'mainSeriesProperties.candleStyle.wickUpColor':  '#6daa45',
          'mainSeriesProperties.candleStyle.wickDownColor':'#d163a7',
          'paneProperties.background':                     '#1c1b19',
          'paneProperties.backgroundType':                 'solid',
          'scalesProperties.textColor':                    '#797876',
          'scalesProperties.backgroundColor':             '#1c1b19',
        },
        broker_factory: brokerFactory,
        broker_config:  { configFlags: {
          supportOrderBrackets: true,
          supportClosePosition: true,
          supportMarketOrders:  true,
          supportLimitOrders:   true,
        }},
      })

      widget.onChartReady(() => setTvReady(true))
      widgetRef.current = widget
    }).catch(err => console.error('[NexusChart] broker import error', err))

    return () => {
      widgetRef.current?.remove()
      widgetRef.current = null
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [libLoaded])

  // Symbol / timeframe change
  useEffect(() => {
    if (!tvReady || !widgetRef.current) return
    widgetRef.current.activeChart().setSymbol(symbol, timeframe)
  }, [symbol, timeframe, tvReady])

  // Draw signal arrows on chart
  useEffect(() => {
    wsClient.connect()
    const handler = (payload: unknown) => {
      if (!tvReady || !widgetRef.current) return
      const p = payload as { symbol?: string; action?: string; entry_price?: number; candle_open_time?: number }
      if (!p?.entry_price) return
      const time  = p.candle_open_time ? p.candle_open_time / 1000 : Math.floor(Date.now() / 1000)
      const isBuy = p.action === 'BUY'
      try {
        widgetRef.current.activeChart().createShape(
          { time, price: p.entry_price },
          {
            shape:     isBuy ? 'arrow_up' : 'arrow_down',
            lock:      true,
            disableSelection: true,
            overrides: { color: isBuy ? '#6daa45' : '#d163a7' },
          }
        )
      } catch {}
    }
    wsClient.on('signal_created', handler)
    return () => wsClient.off('signal_created', handler)
  }, [tvReady])

  return (
    <div className="relative w-full h-full bg-surface">
      {!libLoaded && <ChartSkeleton />}
      <div
        ref={containerRef}
        id="tv-chart-container"
        className="w-full h-full"
        style={{ opacity: libLoaded ? 1 : 0 }}
      />
      {/* Overlay banner when TradingView library is missing */}
      {libLoaded && !window.TradingView && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-surface/90 text-center p-8">
          <p className="text-warning font-medium mb-2">TradingView Library Not Found</p>
          <p className="text-muted text-sm max-w-md">
            Place the charting_library folder in{' '}
            <code className="text-primary text-xs bg-surface2 px-1 rounded">frontend/public/charting_library/</code>.
          </p>
          <a
            href="https://www.tradingview.com/HTML5-stock-forex-bitcoin-charting-library/"
            target="_blank" rel="noopener noreferrer"
            className="mt-4 text-primary text-sm underline"
          >Get TradingView library →</a>
        </div>
      )}
    </div>
  )
}
