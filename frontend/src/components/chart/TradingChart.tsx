'use client'
/**
 * TradingChart.tsx
 * Full-featured TradingView Lightweight Charts v4 component.
 *
 * Features:
 * ─ Candlestick series (OHLCV) from Binance REST (500 candles history)
 * ─ Volume histogram series (semi-transparent, coloured by direction)
 * ─ Real-time Binance WebSocket kline stream (updates last candle live)
 * ─ Signal markers (BUY/SELL arrows) from backend WebSocket
 * ─ SL / TP price lines per open position
 * ─ ResizeObserver — auto-fits parent container
 * ─ Dark theme matched to Nexus Design System tokens
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import {
  createChart,
  IChartApi,
  ISeriesApi,
  ColorType,
  CrosshairMode,
  LineStyle,
  Time,
  CandlestickData,
  HistogramData,
  SeriesMarker,
} from 'lightweight-charts'

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────
interface Candle extends CandlestickData {
  volume?: number
}

interface SignalPayload {
  symbol?: string
  action?: string
  entry_price?: number
  stop_loss?: number
  take_profit_1?: number
  candle_open_time?: number
}

interface Position {
  symbol: string
  entry_price: number
  stop_loss?: number
  take_profit_1?: number
  take_profit_2?: number
}

export interface TradingChartProps {
  symbol?: string
  timeframe?: string
  positions?: Position[]
  height?: number
  /** Called when user selects a different symbol from the toolbar */
  onSymbolChange?: (s: string) => void
  /** Called when user selects a different timeframe */
  onTimeframeChange?: (t: string) => void
}

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────
const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '4h', '1d'] as const
const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT'] as const

const COLORS = {
  bg:           '#1c1b19',
  surface:      '#201f1d',
  border:       '#2d2c2a',
  textMuted:    '#797876',
  textFaint:    '#5a5957',
  green:        '#6daa45',
  red:          '#d163a7',
  blue:         '#5591c7',
  orange:       '#fdab43',
  volGreen:     'rgba(109,170,69,0.35)',
  volRed:       'rgba(209,99,167,0.35)',
  slLine:       '#dd6974',
  tp1Line:      '#6daa45',
  tp2Line:      '#4f98a3',
}

// ─────────────────────────────────────────────────────────────────────────────
// Binance REST datafeed
// ─────────────────────────────────────────────────────────────────────────────
async function fetchCandles(symbol: string, interval: string, limit = 500): Promise<Candle[]> {
  const url = `https://api.binance.com/api/v3/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`Binance klines ${res.status}`)
  const raw = await res.json() as number[][]
  return raw.map(k => ({
    time:   (k[0] / 1000) as Time,
    open:   +k[1],
    high:   +k[2],
    low:    +k[3],
    close:  +k[4],
    volume: +k[5],
  }))
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────
export function TradingChart({
  symbol:          initSymbol    = 'BTCUSDT',
  timeframe:       initTimeframe = '15m',
  positions        = [],
  height           = 520,
  onSymbolChange,
  onTimeframeChange,
}: TradingChartProps) {

  const containerRef  = useRef<HTMLDivElement>(null)
  const chartRef      = useRef<IChartApi | null>(null)
  const candleRef     = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeRef     = useRef<ISeriesApi<'Histogram'> | null>(null)
  const wsRef         = useRef<WebSocket | null>(null)
  const backendWsRef  = useRef<WebSocket | null>(null)
  const markersRef    = useRef<SeriesMarker<Time>[]>([])
  const resizeRef     = useRef<ResizeObserver | null>(null)

  const [symbol,    setSymbol]    = useState(initSymbol)
  const [timeframe, setTimeframe] = useState(initTimeframe)
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState<string | null>(null)
  const [price,     setPrice]     = useState<number | null>(null)
  const [priceDir,  setPriceDir]  = useState<'up' | 'down' | null>(null)
  const prevPriceRef = useRef<number | null>(null)

  // ── 1. Create chart once ──────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: COLORS.bg },
        textColor: COLORS.textMuted,
        fontFamily: "'Inter', 'SF Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: COLORS.border, style: LineStyle.Dotted },
        horzLines: { color: COLORS.border, style: LineStyle.Dotted },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: COLORS.textFaint, width: 1, style: LineStyle.Dashed },
        horzLine: { color: COLORS.textFaint, width: 1, style: LineStyle.Dashed },
      },
      rightPriceScale: {
        borderColor: COLORS.border,
        scaleMargins: { top: 0.08, bottom: 0.25 },
      },
      timeScale: {
        borderColor: COLORS.border,
        timeVisible: true,
        secondsVisible: false,
        fixLeftEdge: false,
        fixRightEdge: false,
      },
      handleScroll: true,
      handleScale: true,
    })

    // Candlestick series
    const candles = chart.addCandlestickSeries({
      upColor:          COLORS.green,
      downColor:        COLORS.red,
      borderUpColor:    COLORS.green,
      borderDownColor:  COLORS.red,
      wickUpColor:      COLORS.green,
      wickDownColor:    COLORS.red,
    })

    // Volume histogram — separate price scale
    const volume = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.80, bottom: 0 },
    })

    chartRef.current  = chart
    candleRef.current = candles
    volumeRef.current = volume

    // ResizeObserver
    const ro = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({
          width:  containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        })
      }
    })
    ro.observe(containerRef.current)
    resizeRef.current = ro

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current  = null
      candleRef.current = null
      volumeRef.current = null
    }
  }, [])

  // ── 2. Load data + WebSocket on symbol/timeframe change ───────────────────
  useEffect(() => {
    if (!candleRef.current || !volumeRef.current) return

    setLoading(true)
    setError(null)
    markersRef.current = []

    // Close previous Binance WS
    wsRef.current?.close()

    fetchCandles(symbol, timeframe)
      .then(data => {
        if (!candleRef.current || !volumeRef.current) return

        candleRef.current.setData(data)

        const volData: HistogramData[] = data.map(c => ({
          time:  c.time,
          value: c.volume ?? 0,
          color: c.close >= c.open ? COLORS.volGreen : COLORS.volRed,
        }))
        volumeRef.current.setData(volData)

        chartRef.current?.timeScale().fitContent()
        setLoading(false)

        // Latest price
        const last = data[data.length - 1]
        if (last) setPrice(last.close)
      })
      .catch(e => {
        setError(String(e.message ?? e))
        setLoading(false)
      })

    // Binance real-time kline WebSocket
    const stream = `${symbol.toLowerCase()}@kline_${timeframe}`
    const bws = new WebSocket(`wss://stream.binance.com:9443/ws/${stream}`)

    bws.onmessage = ev => {
      const msg  = JSON.parse(ev.data) as { k: Record<string, unknown> }
      const k    = msg.k
      if (!candleRef.current || !volumeRef.current) return

      const t     = Number(k.t) / 1000 as Time
      const open  = +String(k.o)
      const high  = +String(k.h)
      const low   = +String(k.l)
      const close = +String(k.c)
      const vol   = +String(k.v)

      candleRef.current.update({ time: t, open, high, low, close })
      volumeRef.current.update({
        time:  t,
        value: vol,
        color: close >= open ? COLORS.volGreen : COLORS.volRed,
      })

      // Animated price indicator
      setPrice(prev => {
        const dir = prev === null ? null : close > prev ? 'up' : close < prev ? 'down' : null
        setPriceDir(dir)
        return close
      })
    }

    bws.onerror = () => setError('Binance WebSocket error')
    wsRef.current = bws

    return () => bws.close()
  }, [symbol, timeframe])

  // ── 3. Backend WebSocket — signal markers ─────────────────────────────────
  useEffect(() => {
    const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws'
    const bws = new WebSocket(WS_URL)

    bws.onmessage = ev => {
      try {
        const msg = JSON.parse(ev.data) as { event?: string; payload?: unknown }
        if (msg.event !== 'signal_created') return

        const p = msg.payload as SignalPayload
        if (!p || !p.entry_price) return
        if (p.symbol && p.symbol !== symbol) return

        const time = (p.candle_open_time
          ? p.candle_open_time / 1000
          : Math.floor(Date.now() / 1000)) as Time

        const isBuy = p.action === 'BUY'

        const marker: SeriesMarker<Time> = {
          time,
          position: isBuy ? 'belowBar' : 'aboveBar',
          color:    isBuy ? COLORS.green : COLORS.red,
          shape:    isBuy ? 'arrowUp'    : 'arrowDown',
          text:     isBuy ? '▲ BUY'      : '▼ SELL',
          size:     1.5,
        }

        markersRef.current = [...markersRef.current.slice(-99), marker]
        candleRef.current?.setMarkers(markersRef.current)
      } catch {}
    }

    backendWsRef.current = bws
    return () => bws.close()
  }, [symbol])

  // ── 4. Position price lines (SL / TP) ─────────────────────────────────────
  useEffect(() => {
    const series = candleRef.current
    if (!series) return

    const lines: ReturnType<typeof series.createPriceLine>[] = []

    positions
      .filter(p => p.symbol === symbol)
      .forEach(p => {
        lines.push(series.createPriceLine({
          price: p.entry_price,
          color: COLORS.blue,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'Entry',
        }))
        if (p.stop_loss) {
          lines.push(series.createPriceLine({
            price: p.stop_loss,
            color: COLORS.slLine,
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: 'SL',
          }))
        }
        if (p.take_profit_1) {
          lines.push(series.createPriceLine({
            price: p.take_profit_1,
            color: COLORS.tp1Line,
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: 'TP1',
          }))
        }
        if (p.take_profit_2) {
          lines.push(series.createPriceLine({
            price: p.take_profit_2,
            color: COLORS.tp2Line,
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: true,
            title: 'TP2',
          }))
        }
      })

    return () => lines.forEach(l => series.removePriceLine(l))
  }, [positions, symbol])

  // ── Toolbar handlers ───────────────────────────────────────────────────────
  const handleSymbol = useCallback((s: string) => {
    setSymbol(s)
    onSymbolChange?.(s)
  }, [onSymbolChange])

  const handleTimeframe = useCallback((t: string) => {
    setTimeframe(t)
    onTimeframeChange?.(t)
  }, [onTimeframeChange])

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      background: COLORS.bg,
      borderRadius: 8,
      border: `1px solid ${COLORS.border}`,
      overflow: 'hidden',
    }}>

      {/* Toolbar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 12px',
        borderBottom: `1px solid ${COLORS.border}`,
        background: COLORS.surface,
        flexWrap: 'wrap',
      }}>

        {/* Symbol selector */}
        <select
          value={symbol}
          onChange={e => handleSymbol(e.target.value)}
          style={{
            background: COLORS.bg,
            color: '#cdccca',
            border: `1px solid ${COLORS.border}`,
            borderRadius: 4,
            padding: '3px 8px',
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            outline: 'none',
          }}
        >
          {SYMBOLS.map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        {/* Timeframe buttons */}
        <div style={{ display: 'flex', gap: 2 }}>
          {TIMEFRAMES.map(tf => (
            <button
              key={tf}
              onClick={() => handleTimeframe(tf)}
              style={{
                padding: '3px 8px',
                fontSize: 11,
                fontWeight: 600,
                border: 'none',
                borderRadius: 4,
                cursor: 'pointer',
                background: timeframe === tf ? COLORS.blue : 'transparent',
                color:      timeframe === tf ? '#fff'      : COLORS.textMuted,
                transition: 'background 120ms ease',
              }}
            >
              {tf}
            </button>
          ))}
        </div>

        {/* Live price display */}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          {loading && (
            <span style={{ fontSize: 11, color: COLORS.textFaint }}>Loading…</span>
          )}
          {error && (
            <span style={{ fontSize: 11, color: COLORS.red }}>⚠ {error}</span>
          )}
          {price !== null && !loading && (
            <span style={{
              fontFamily: 'monospace',
              fontSize: 14,
              fontWeight: 700,
              color: priceDir === 'up' ? COLORS.green : priceDir === 'down' ? COLORS.red : '#cdccca',
              transition: 'color 300ms ease',
            }}>
              {price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 })}
            </span>
          )}
          {/* Live dot */}
          <span style={{
            width: 7, height: 7,
            borderRadius: '50%',
            background: wsRef.current?.readyState === 1 ? COLORS.green : COLORS.textFaint,
            display: 'inline-block',
          }} />
        </div>
      </div>

      {/* Chart container */}
      <div
        ref={containerRef}
        style={{ width: '100%', height }}
      />

      {/* Legend */}
      <div style={{
        display: 'flex',
        gap: 16,
        padding: '6px 12px',
        borderTop: `1px solid ${COLORS.border}`,
        background: COLORS.surface,
        fontSize: 10,
        color: COLORS.textFaint,
      }}>
        {[
          { color: COLORS.green,   label: 'Bull candle' },
          { color: COLORS.red,     label: 'Bear candle' },
          { color: COLORS.blue,    label: 'Entry' },
          { color: COLORS.slLine,  label: 'Stop Loss' },
          { color: COLORS.tp1Line, label: 'TP1' },
          { color: COLORS.tp2Line, label: 'TP2' },
        ].map(item => (
          <span key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 2, background: item.color, borderRadius: 1, display: 'inline-block' }} />
            {item.label}
          </span>
        ))}
      </div>
    </div>
  )
}

export default TradingChart
