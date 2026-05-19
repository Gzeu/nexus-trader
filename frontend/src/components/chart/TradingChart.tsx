'use client'

/**
 * TradingChart.tsx — TradingView Lightweight Charts integration.
 *
 * Uses the free, open-source lightweight-charts library from TradingView.
 * Datafeed wired to Binance REST (OHLCV) + WebSocket (live ticks).
 * Signal arrows displayed as markers on the chart.
 */

import { useEffect, useRef, useState } from 'react'
import { createChart, IChartApi, ISeriesApi, ColorType, CrosshairMode, Time, CandlestickSeries } from 'lightweight-charts'
import { wsClient } from '@/lib/websocket'
import { config } from '@/lib/config'
import { ChartSkeleton } from './ChartSkeleton'

// ── Binance Datafeed ─────────────────────────────────────────────────────────

const RESOLUTION_MAP: Record<string, string> = {
  '1': '1m', '1m': '1m',
  '3': '3m', '3m': '3m',
  '5': '5m', '5m': '5m',
  '15': '15m', '15m': '15m',
  '30': '30m', '30m': '30m',
  '60': '1h', '1h': '1h',
  '240': '4h', '4h': '4h',
  'D': '1d', '1D': '1d', '1d': '1d',
}

async function fetchHistoricalData(symbol: string, interval: string, limit: number = 1000) {
  const BASE = 'https://api.binance.com/api/v3'
  const url = `${BASE}/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`
  const res = await fetch(url)
  const data = await res.json()
  return (data as number[][]).map(k => ({
    time: (k[0] / 1000) as Time,
    open: parseFloat(String(k[1])),
    high: parseFloat(String(k[2])),
    low: parseFloat(String(k[3])),
    close: parseFloat(String(k[4])),
  }))
}

// ── Component ────────────────────────────────────────────────────────────────

export default function TradingChart({
  symbol    = 'BTCUSDT',
  timeframe = '15',
}: {
  symbol?:    string
  timeframe?: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef    = useRef<any>(null)
  const seriesRef   = useRef<any>(null)
  const wsRef       = useRef<WebSocket | null>(null)
  const markersRef  = useRef<any[]>([])
  const [ready, setReady] = useState(false)

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return

    const chart: any = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#1c1b19' },
        textColor: '#797876',
      },
      grid: {
        vertLines: { color: '#2a2a2a' },
        horzLines: { color: '#2a2a2a' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: '#2a2a2a',
      },
      timeScale: {
        borderColor: '#2a2a2a',
        timeVisible: true,
      },
    })

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#6daa45',
      downColor: '#d163a7',
      borderUpColor: '#6daa45',
      borderDownColor: '#d163a7',
      wickUpColor: '#6daa45',
      wickDownColor: '#d163a7',
    })

    chartRef.current = chart
    seriesRef.current = candlestickSeries
    setReady(true)

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight })
      }
    }

    window.addEventListener('resize', handleResize)
    handleResize()

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
      wsRef.current?.close()
    }
  }, [])

  // Load historical data and setup WebSocket on symbol/timeframe change
  useEffect(() => {
    if (!ready || !seriesRef.current) return

    const interval = RESOLUTION_MAP[timeframe] ?? '15m'

    // Load historical data
    fetchHistoricalData(symbol, interval).then(data => {
      seriesRef.current?.setData(data)
    }).catch(err => console.error('[NexusChart] Failed to load historical data', err))

    // Setup WebSocket for real-time updates
    wsRef.current?.close()
    const stream = `${symbol.toLowerCase()}@kline_${interval}`
    const ws = new WebSocket(`wss://stream.binance.com:9443/ws/${stream}`)
    
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data)
      const k = msg.k
      if (seriesRef.current) {
        seriesRef.current.update({
          time: (k.t / 1000) as Time,
          open: parseFloat(k.o),
          high: parseFloat(k.h),
          low: parseFloat(k.l),
          close: parseFloat(k.c),
        })
      }
    }

    wsRef.current = ws

    return () => {
      ws.close()
    }
  }, [symbol, timeframe, ready])

  // Draw signal markers on chart
  useEffect(() => {
    if (!ready || !seriesRef.current) return

    wsClient.connect()
    const handler = (payload: unknown) => {
      const p = payload as { symbol?: string; action?: string; entry_price?: number; candle_open_time?: number }
      if (!p?.entry_price) return
      const time = (p.candle_open_time ? p.candle_open_time / 1000 : Math.floor(Date.now() / 1000)) as Time
      const isBuy = p.action === 'BUY'
      
      const marker = {
        time,
        position: isBuy ? 'belowBar' as const : 'aboveBar' as const,
        color: isBuy ? '#6daa45' : '#d163a7',
        shape: isBuy ? 'arrowUp' as const : 'arrowDown' as const,
        text: isBuy ? 'BUY' : 'SELL',
      }
      
      markersRef.current = [...markersRef.current, marker]
      seriesRef.current.setMarkers(markersRef.current)
    }
    wsClient.on('signal_created', handler)
    return () => wsClient.off('signal_created', handler)
  }, [ready])

  return (
    <div className="relative w-full h-full bg-surface">
      {!ready && <ChartSkeleton />}
      <div
        ref={containerRef}
        className="w-full h-full"
      />
    </div>
  )
}
