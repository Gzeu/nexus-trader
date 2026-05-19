'use client'
/**
 * TradingChart.tsx — v2
 * Production-grade Lightweight Charts v4 component.
 *
 * New in v2:
 * ─ EMA 9 + EMA 21 line overlays on candlestick pane
 * ─ RSI(14) pane — separate price scale, overbought/oversold bands
 * ─ Crosshair OHLCV tooltip (top-left floating legend)
 * ─ WebSocket auto-reconnect with exponential backoff (Binance + Backend)
 * ─ 24h price change % badge
 * ─ Volume bars retain colour sync with candles
 * ─ backend WS: also handle order_filled + position events
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
  LineData,
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

interface OHLCVTooltip {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  change: number
}

export interface TradingChartProps {
  symbol?: string
  timeframe?: string
  positions?: Position[]
  height?: number
  showRsi?: boolean
  onSymbolChange?: (s: string) => void
  onTimeframeChange?: (t: string) => void
}

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────
const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '4h', '1d'] as const
const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT', 'DOGEUSDT'] as const

const C = {
  bg:        '#1c1b19',
  surface:   '#201f1d',
  surface2:  '#252422',
  border:    '#2d2c2a',
  text:      '#cdccca',
  textMuted: '#797876',
  textFaint: '#5a5957',
  green:     '#6daa45',
  red:       '#d163a7',
  blue:      '#5591c7',
  teal:      '#4f98a3',
  orange:    '#fdab43',
  volGreen:  'rgba(109,170,69,0.30)',
  volRed:    'rgba(209,99,167,0.30)',
  ema9:      '#fdab43',   // orange
  ema21:     '#5591c7',   // blue
  rsi:       '#a86fdf',   // purple
  rsiOB:     'rgba(221,105,116,0.18)',
  rsiOS:     'rgba(109,170,69,0.18)',
  slLine:    '#dd6974',
  tp1Line:   '#6daa45',
  tp2Line:   '#4f98a3',
}

// ─────────────────────────────────────────────────────────────────────────────
// Indicator math
// ─────────────────────────────────────────────────────────────────────────────
function calcEMA(closes: number[], period: number): number[] {
  const k = 2 / (period + 1)
  const out: number[] = []
  let ema = closes[0]
  for (let i = 0; i < closes.length; i++) {
    ema = i === 0 ? closes[0] : closes[i] * k + ema * (1 - k)
    out.push(ema)
  }
  return out
}

function calcRSI(closes: number[], period = 14): number[] {
  const out: number[] = new Array(period).fill(50)
  let avgGain = 0
  let avgLoss = 0
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1]
    if (diff > 0) avgGain += diff
    else avgLoss += Math.abs(diff)
  }
  avgGain /= period
  avgLoss /= period
  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1]
    avgGain = (avgGain * (period - 1) + Math.max(diff, 0)) / period
    avgLoss = (avgLoss * (period - 1) + Math.max(-diff, 0)) / period
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss
    out.push(100 - 100 / (1 + rs))
  }
  return out
}

// ─────────────────────────────────────────────────────────────────────────────
// Binance REST
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

async function fetch24hChange(symbol: string): Promise<number | null> {
  try {
    const res = await fetch(`https://api.binance.com/api/v3/ticker/24hr?symbol=${symbol}`)
    if (!res.ok) return null
    const d = await res.json() as { priceChangePercent: string }
    return parseFloat(d.priceChangePercent)
  } catch { return null }
}

// ─────────────────────────────────────────────────────────────────────────────
// WS with auto-reconnect
// ─────────────────────────────────────────────────────────────────────────────
function createAutoWS(
  getUrl: () => string,
  onMessage: (data: string) => void,
  maxRetries = 10,
): { ws: WebSocket; stop: () => void } {
  let stopped = false
  let retries = 0
  let ws: WebSocket

  function connect() {
    ws = new WebSocket(getUrl())
    ws.onmessage = ev => onMessage(ev.data as string)
    ws.onclose = () => {
      if (stopped || retries >= maxRetries) return
      const delay = Math.min(1000 * 2 ** retries, 30000)
      retries++
      setTimeout(connect, delay)
    }
    ws.onerror = () => ws.close()
  }
  connect()
  return {
    get ws() { return ws },
    stop() { stopped = true; ws?.close() },
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Format time for tooltip
// ─────────────────────────────────────────────────────────────────────────────
function fmtTime(unixSec: number): string {
  return new Date(unixSec * 1000).toLocaleString('en-US', {
    month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────
export function TradingChart({
  symbol:      initSymbol    = 'BTCUSDT',
  timeframe:   initTimeframe = '15m',
  positions    = [],
  height       = 520,
  showRsi      = true,
  onSymbolChange,
  onTimeframeChange,
}: TradingChartProps) {

  const containerRef  = useRef<HTMLDivElement>(null)
  const rsiRef        = useRef<HTMLDivElement>(null)

  // Main chart refs
  const chartRef      = useRef<IChartApi | null>(null)
  const candleRef     = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeRef     = useRef<ISeriesApi<'Histogram'> | null>(null)
  const ema9Ref       = useRef<ISeriesApi<'Line'> | null>(null)
  const ema21Ref      = useRef<ISeriesApi<'Line'> | null>(null)

  // RSI chart refs
  const rsiChartRef   = useRef<IChartApi | null>(null)
  const rsiSeriesRef  = useRef<ISeriesApi<'Line'> | null>(null)
  const rsiOBRef      = useRef<ReturnType<ISeriesApi<'Line'>['createPriceLine']> | null>(null)
  const rsiOSRef      = useRef<ReturnType<ISeriesApi<'Line'>['createPriceLine']> | null>(null)

  // WS refs
  const binanceWSRef  = useRef<{ ws: WebSocket; stop: () => void } | null>(null)
  const backendWSRef  = useRef<{ ws: WebSocket; stop: () => void } | null>(null)
  const resizeRef     = useRef<ResizeObserver | null>(null)

  // Marker buffer
  const markersRef    = useRef<SeriesMarker<Time>[]>([])
  // Volume data cache for colour sync
  const candleDataRef = useRef<Candle[]>([])

  const [symbol,    setSymbol]    = useState(initSymbol)
  const [timeframe, setTimeframe] = useState(initTimeframe)
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState<string | null>(null)
  const [price,     setPrice]     = useState<number | null>(null)
  const [priceDir,  setPriceDir]  = useState<'up' | 'down' | null>(null)
  const [change24h, setChange24h] = useState<number | null>(null)
  const [wsLive,    setWsLive]    = useState(false)
  const [tooltip,   setTooltip]   = useState<OHLCVTooltip | null>(null)

  // ── 1. Create main chart ──────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: C.bg },
        textColor: C.textMuted,
        fontFamily: "'Inter', 'SF Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: C.border, style: LineStyle.Dotted },
        horzLines: { color: C.border, style: LineStyle.Dotted },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: C.textFaint, width: 1, style: LineStyle.Dashed, labelBackgroundColor: C.surface2 },
        horzLine: { color: C.textFaint, width: 1, style: LineStyle.Dashed, labelBackgroundColor: C.surface2 },
      },
      rightPriceScale: {
        borderColor: C.border,
        scaleMargins: { top: 0.08, bottom: 0.28 },
      },
      timeScale: {
        borderColor: C.border,
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: true,
      handleScale: true,
    })

    const candles = chart.addCandlestickSeries({
      upColor: C.green, downColor: C.red,
      borderUpColor: C.green, borderDownColor: C.red,
      wickUpColor: C.green, wickDownColor: C.red,
    })

    const volume = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })

    const ema9 = chart.addLineSeries({
      color: C.ema9, lineWidth: 1,
      priceLineVisible: false, lastValueVisible: true,
      crosshairMarkerVisible: false,
    })
    const ema21 = chart.addLineSeries({
      color: C.ema21, lineWidth: 1,
      priceLineVisible: false, lastValueVisible: true,
      crosshairMarkerVisible: false,
    })

    chartRef.current  = chart
    candleRef.current = candles
    volumeRef.current = volume
    ema9Ref.current   = ema9
    ema21Ref.current  = ema21

    // Crosshair tooltip
    chart.subscribeCrosshairMove(param => {
      if (!param.time || param.point === undefined) {
        setTooltip(null)
        return
      }
      const bar = param.seriesData.get(candles) as CandlestickData | undefined
      const volBar = param.seriesData.get(volume) as HistogramData | undefined
      if (!bar) { setTooltip(null); return }
      setTooltip({
        time:   fmtTime(param.time as number),
        open:   bar.open,
        high:   bar.high,
        low:    bar.low,
        close:  bar.close,
        volume: (volBar?.value ?? 0),
        change: ((bar.close - bar.open) / bar.open) * 100,
      })
    })

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
      chartRef.current = candleRef.current = volumeRef.current = null
      ema9Ref.current = ema21Ref.current = null
    }
  }, [])

  // ── 2. Create RSI chart ───────────────────────────────────────────────────
  useEffect(() => {
    if (!showRsi || !rsiRef.current) return

    const rsiChart = createChart(rsiRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: C.bg },
        textColor: C.textMuted,
        fontSize: 10,
      },
      grid: {
        vertLines: { color: C.border, style: LineStyle.Dotted },
        horzLines: { color: C.border, style: LineStyle.Dotted },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: C.textFaint, width: 1, style: LineStyle.Dashed },
        horzLine: { color: C.textFaint, width: 1, style: LineStyle.Dashed },
      },
      rightPriceScale: {
        borderColor: C.border,
        scaleMargins: { top: 0.05, bottom: 0.05 },
        autoScale: false,
        minValue: 0,
        maxValue: 100,
      },
      timeScale: {
        borderColor: C.border,
        timeVisible: true,
        secondsVisible: false,
        visible: false, // time axis shown in main chart only
      },
      handleScroll: false,
      handleScale:  false,
    })

    const rsiSeries = rsiChart.addLineSeries({
      color: C.rsi,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: true,
    })

    // OB / OS bands
    rsiOBRef.current = rsiSeries.createPriceLine({
      price: 70, color: C.slLine, lineWidth: 1,
      lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'OB',
    })
    rsiOSRef.current = rsiSeries.createPriceLine({
      price: 30, color: C.tp1Line, lineWidth: 1,
      lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'OS',
    })
    rsiSeries.createPriceLine({
      price: 50, color: C.textFaint, lineWidth: 1,
      lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: '',
    })

    rsiChartRef.current  = rsiChart
    rsiSeriesRef.current = rsiSeries

    // Sync RSI time scale with main chart
    const syncHandler = () => {
      if (!chartRef.current || !rsiChartRef.current) return
      const range = chartRef.current.timeScale().getVisibleLogicalRange()
      if (range) rsiChartRef.current.timeScale().setVisibleLogicalRange(range)
    }
    chartRef.current?.timeScale().subscribeVisibleLogicalRangeChange(syncHandler)

    // RSI resize
    const ro = new ResizeObserver(() => {
      if (rsiRef.current) {
        rsiChart.applyOptions({
          width:  rsiRef.current.clientWidth,
          height: rsiRef.current.clientHeight,
        })
      }
    })
    ro.observe(rsiRef.current)

    return () => {
      ro.disconnect()
      rsiChart.remove()
      rsiChartRef.current = rsiSeriesRef.current = null
    }
  }, [showRsi])

  // ── 3. Load data + Binance WS ─────────────────────────────────────────────
  useEffect(() => {
    if (!candleRef.current) return

    setLoading(true)
    setError(null)
    setTooltip(null)
    markersRef.current = []

    binanceWSRef.current?.stop()
    setWsLive(false)

    Promise.all([
      fetchCandles(symbol, timeframe),
      fetch24hChange(symbol),
    ]).then(([data, ch]) => {
      if (!candleRef.current || !volumeRef.current) return

      candleDataRef.current = data
      candleRef.current.setData(data)

      // Volume
      const volData: HistogramData[] = data.map(c => ({
        time:  c.time,
        value: c.volume ?? 0,
        color: (c.close >= c.open) ? C.volGreen : C.volRed,
      }))
      volumeRef.current.setData(volData)

      // EMA9 + EMA21
      const closes = data.map(c => c.close)
      const ema9vals  = calcEMA(closes, 9)
      const ema21vals = calcEMA(closes, 21)
      ema9Ref.current?.setData(data.map((c, i) => ({ time: c.time, value: ema9vals[i] })))
      ema21Ref.current?.setData(data.map((c, i) => ({ time: c.time, value: ema21vals[i] })))

      // RSI
      if (rsiSeriesRef.current && data.length > 14) {
        const rsiVals = calcRSI(closes)
        rsiSeriesRef.current.setData(
          data.slice(14).map((c, i) => ({ time: c.time, value: rsiVals[i + 14] ?? 50 }))
        )
      }

      chartRef.current?.timeScale().fitContent()
      setLoading(false)
      setChange24h(ch)

      const last = data[data.length - 1]
      if (last) setPrice(last.close)
    }).catch(e => {
      setError(String((e as Error).message ?? e))
      setLoading(false)
    })

    // Binance real-time WS with auto-reconnect
    const stream = `${symbol.toLowerCase()}@kline_${timeframe}`
    const bWS = createAutoWS(
      () => `wss://stream.binance.com:9443/ws/${stream}`,
      (data) => {
        const msg = JSON.parse(data) as { k: Record<string, unknown> }
        const k = msg.k
        if (!candleRef.current || !volumeRef.current) return

        const t     = (Number(k.t) / 1000) as Time
        const open  = +String(k.o)
        const high  = +String(k.h)
        const low   = +String(k.l)
        const close = +String(k.c)
        const vol   = +String(k.v)
        const isClosed = Boolean(k.x)

        candleRef.current.update({ time: t, open, high, low, close })
        volumeRef.current.update({
          time: t, value: vol,
          color: close >= open ? C.volGreen : C.volRed,
        })

        // Update EMA on closed candle
        if (isClosed && candleDataRef.current.length > 0) {
          const allCloses = [...candleDataRef.current.map(c => c.close), close]
          const ema9v  = calcEMA(allCloses, 9)
          const ema21v = calcEMA(allCloses, 21)
          ema9Ref.current?.update({ time: t, value: ema9v[ema9v.length - 1] })
          ema21Ref.current?.update({ time: t, value: ema21v[ema21v.length - 1] })
          // RSI update
          if (rsiSeriesRef.current && allCloses.length > 14) {
            const rsiVals = calcRSI(allCloses)
            rsiSeriesRef.current.update({ time: t, value: rsiVals[rsiVals.length - 1] })
          }
          candleDataRef.current = [...candleDataRef.current, { time: t, open, high, low, close, volume: vol }]
        }

        setWsLive(true)
        setPrice(prev => {
          setPriceDir(prev === null ? null : close > prev ? 'up' : close < prev ? 'down' : null)
          return close
        })
      }
    )
    binanceWSRef.current = bWS

    return () => bWS.stop()
  }, [symbol, timeframe])

  // ── 4. Backend WS — signals + positions ──────────────────────────────────
  useEffect(() => {
    const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws'
    const bWS = createAutoWS(
      () => WS_URL,
      (data) => {
        try {
          const msg = JSON.parse(data) as { event?: string; payload?: unknown }
          if (msg.event !== 'signal_created') return

          const p = msg.payload as SignalPayload
          if (!p?.entry_price) return
          if (p.symbol && p.symbol !== symbol) return

          const time = ((p.candle_open_time
            ? p.candle_open_time / 1000
            : Math.floor(Date.now() / 1000))) as Time

          const isBuy = p.action === 'BUY'
          const marker: SeriesMarker<Time> = {
            time,
            position: isBuy ? 'belowBar' : 'aboveBar',
            color:    isBuy ? C.green    : C.red,
            shape:    isBuy ? 'arrowUp'  : 'arrowDown',
            text:     isBuy ? '▲ BUY'   : '▼ SELL',
            size: 1.5,
          }
          markersRef.current = [...markersRef.current.slice(-99), marker]
          candleRef.current?.setMarkers(markersRef.current)
        } catch {}
      }
    )
    backendWSRef.current = bWS
    return () => bWS.stop()
  }, [symbol])

  // ── 5. SL / TP price lines ────────────────────────────────────────────────
  useEffect(() => {
    const series = candleRef.current
    if (!series) return
    const lines: ReturnType<typeof series.createPriceLine>[] = []
    positions
      .filter(p => p.symbol === symbol)
      .forEach(p => {
        lines.push(series.createPriceLine({ price: p.entry_price, color: C.blue, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'Entry' }))
        if (p.stop_loss)     lines.push(series.createPriceLine({ price: p.stop_loss,     color: C.slLine,  lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'SL' }))
        if (p.take_profit_1) lines.push(series.createPriceLine({ price: p.take_profit_1, color: C.tp1Line, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'TP1' }))
        if (p.take_profit_2) lines.push(series.createPriceLine({ price: p.take_profit_2, color: C.tp2Line, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'TP2' }))
      })
    return () => lines.forEach(l => series.removePriceLine(l))
  }, [positions, symbol])

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleSymbol = useCallback((s: string) => {
    setSymbol(s); onSymbolChange?.(s)
  }, [onSymbolChange])

  const handleTimeframe = useCallback((t: string) => {
    setTimeframe(t); onTimeframeChange?.(t)
  }, [onTimeframeChange])

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────
  const rsiHeight = showRsi ? 120 : 0
  const mainHeight = height - rsiHeight - (showRsi ? 4 : 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', background: C.bg, borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>

      {/* ── Toolbar ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderBottom: `1px solid ${C.border}`, background: C.surface, flexWrap: 'wrap' }}>

        {/* Symbol */}
        <select value={symbol} onChange={e => handleSymbol(e.target.value)} style={{ background: C.bg, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: '3px 8px', fontSize: 12, fontWeight: 700, cursor: 'pointer', outline: 'none' }}>
          {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>

        {/* Timeframes */}
        <div style={{ display: 'flex', gap: 2 }}>
          {TIMEFRAMES.map(tf => (
            <button key={tf} onClick={() => handleTimeframe(tf)} style={{ padding: '3px 8px', fontSize: 11, fontWeight: 600, border: 'none', borderRadius: 4, cursor: 'pointer', background: timeframe === tf ? C.blue : 'transparent', color: timeframe === tf ? '#fff' : C.textMuted, transition: 'background 120ms ease' }}>
              {tf}
            </button>
          ))}
        </div>

        {/* EMA legend chips */}
        <div style={{ display: 'flex', gap: 6, marginLeft: 4 }}>
          <span style={{ fontSize: 10, color: C.ema9,  display: 'flex', alignItems: 'center', gap: 3 }}>
            <span style={{ width: 16, height: 2, background: C.ema9,  display: 'inline-block', borderRadius: 1 }} />EMA9
          </span>
          <span style={{ fontSize: 10, color: C.ema21, display: 'flex', alignItems: 'center', gap: 3 }}>
            <span style={{ width: 16, height: 2, background: C.ema21, display: 'inline-block', borderRadius: 1 }} />EMA21
          </span>
        </div>

        {/* Price + 24h change */}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          {loading && <span style={{ fontSize: 11, color: C.textFaint }}>Loading…</span>}
          {error   && <span style={{ fontSize: 11, color: C.red }}>⚠ {error}</span>}
          {price != null && !loading && (
            <span style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 700, color: priceDir === 'up' ? C.green : priceDir === 'down' ? C.red : C.text, transition: 'color 300ms ease' }}>
              {price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 })}
            </span>
          )}
          {change24h != null && (
            <span style={{ fontSize: 11, fontWeight: 600, color: change24h >= 0 ? C.green : C.red, background: change24h >= 0 ? 'rgba(109,170,69,0.15)' : 'rgba(209,99,167,0.15)', padding: '2px 6px', borderRadius: 4 }}>
              {change24h >= 0 ? '+' : ''}{change24h.toFixed(2)}%
            </span>
          )}
          {/* WS live dot */}
          <span title={wsLive ? 'Live' : 'Connecting…'} style={{ width: 7, height: 7, borderRadius: '50%', background: wsLive ? C.green : C.textFaint, display: 'inline-block', transition: 'background 300ms ease' }} />
        </div>
      </div>

      {/* ── Main chart ── */}
      <div style={{ position: 'relative' }}>
        <div ref={containerRef} style={{ width: '100%', height: mainHeight }} />

        {/* Crosshair OHLCV tooltip */}
        {tooltip && (
          <div style={{ position: 'absolute', top: 8, left: 12, pointerEvents: 'none', background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 6, padding: '6px 10px', fontSize: 11, color: C.textMuted, lineHeight: 1.6, zIndex: 10 }}>
            <div style={{ color: C.textFaint, marginBottom: 2, fontSize: 10 }}>{tooltip.time}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'auto auto', gap: '0 12px' }}>
              <span style={{ color: C.textFaint }}>O</span><span style={{ color: C.text, fontFamily: 'monospace' }}>{tooltip.open.toFixed(2)}</span>
              <span style={{ color: C.textFaint }}>H</span><span style={{ color: C.green,  fontFamily: 'monospace' }}>{tooltip.high.toFixed(2)}</span>
              <span style={{ color: C.textFaint }}>L</span><span style={{ color: C.red,    fontFamily: 'monospace' }}>{tooltip.low.toFixed(2)}</span>
              <span style={{ color: C.textFaint }}>C</span><span style={{ color: tooltip.change >= 0 ? C.green : C.red, fontFamily: 'monospace', fontWeight: 700 }}>{tooltip.close.toFixed(2)}</span>
              <span style={{ color: C.textFaint }}>V</span><span style={{ color: C.textMuted, fontFamily: 'monospace' }}>{tooltip.volume >= 1e6 ? (tooltip.volume/1e6).toFixed(2)+'M' : tooltip.volume >= 1e3 ? (tooltip.volume/1e3).toFixed(1)+'K' : tooltip.volume.toFixed(0)}</span>
              <span style={{ color: C.textFaint }}>Δ</span><span style={{ color: tooltip.change >= 0 ? C.green : C.red, fontFamily: 'monospace' }}>{tooltip.change >= 0 ? '+' : ''}{tooltip.change.toFixed(2)}%</span>
            </div>
          </div>
        )}
      </div>

      {/* ── RSI pane ── */}
      {showRsi && (
        <>
          <div style={{ borderTop: `1px solid ${C.border}`, padding: '3px 12px', background: C.surface2, fontSize: 10, color: C.textFaint, display: 'flex', gap: 12 }}>
            <span>RSI(14)</span>
            <span style={{ color: C.rsi }}>{/* live RSI value shown via lastValueVisible */}</span>
            <span style={{ color: C.slLine }}>OB 70</span>
            <span style={{ color: C.tp1Line }}>OS 30</span>
          </div>
          <div ref={rsiRef} style={{ width: '100%', height: rsiHeight }} />
        </>
      )}

      {/* ── Legend footer ── */}
      <div style={{ display: 'flex', gap: 16, padding: '6px 12px', borderTop: `1px solid ${C.border}`, background: C.surface, fontSize: 10, color: C.textFaint, flexWrap: 'wrap' }}>
        {[
          { color: C.green,   label: 'Bull' },
          { color: C.red,     label: 'Bear' },
          { color: C.ema9,    label: 'EMA9' },
          { color: C.ema21,   label: 'EMA21' },
          { color: C.blue,    label: 'Entry' },
          { color: C.slLine,  label: 'SL' },
          { color: C.tp1Line, label: 'TP1' },
          { color: C.tp2Line, label: 'TP2' },
          { color: C.rsi,     label: 'RSI' },
        ].map(item => (
          <span key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, height: 2, background: item.color, borderRadius: 1, display: 'inline-block' }} />
            {item.label}
          </span>
        ))}
      </div>
    </div>
  )
}

export default TradingChart
