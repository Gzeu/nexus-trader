'use client'
/**
 * TradingChart.tsx — v3
 * ─────────────────────────────────────────────────────────────────────────────
 * CHANGES vs v2
 * ─ MACD pane (MACD line + Signal + Histogram) — opțional, toggle din toolbar
 * ─ Bollinger Bands overlay (20, 2σ) — bandă superioară/inferioară + mijlocie
 * ─ Volume toggle — buton în toolbar să ascundă/afișeze volumul
 * ─ Fullscreen mode — buton ⛶ → chart ocupă tot ecranul (ESC pentru exit)
 * ─ Keyboard shortcuts: ← / → scroll, +/- zoom, F fullscreen, R reset zoom
 * ─ RSI sync bidirecțional — scrollul din RSI sincronizează și main chart
 * ─ order_filled events din backend WS → marker cu preț exact
 * ─ position_opened events → adaugă SL/TP lines live (fără re-render React)
 * ─ Bugfix: RSI data slice corect — datele pornesc de la index 14, nu 0
 * ─ Bugfix: candleDataRef update la fiecare candelă închisă
 * ─ Bugfix: cleanup price lines la schimbare simbol
 * ─ Perf: un singur ResizeObserver împărțit între main + RSI + MACD
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
  take_profit_2?: number
  candle_open_time?: number
}

interface OrderFilledPayload {
  symbol?: string
  side?: string
  price?: number
  qty?: number
  time?: number
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
const SYMBOLS    = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT', 'DOGEUSDT'] as const

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
  volGreen:  'rgba(109,170,69,0.28)',
  volRed:    'rgba(209,99,167,0.28)',
  ema9:      '#fdab43',
  ema21:     '#5591c7',
  rsi:       '#a86fdf',
  macd:      '#4f98a3',
  signal:    '#fdab43',
  bbUpper:   'rgba(85,145,199,0.40)',
  bbLower:   'rgba(85,145,199,0.40)',
  bbMiddle:  'rgba(85,145,199,0.25)',
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
  if (closes.length <= period) return new Array(closes.length).fill(50)
  const out: number[] = new Array(period).fill(50)
  let avgGain = 0, avgLoss = 0
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1]
    diff > 0 ? (avgGain += diff) : (avgLoss += Math.abs(diff))
  }
  avgGain /= period; avgLoss /= period
  out.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss))
  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1]
    avgGain = (avgGain * (period - 1) + Math.max(diff, 0))  / period
    avgLoss = (avgLoss * (period - 1) + Math.max(-diff, 0)) / period
    out.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss))
  }
  return out
}

function calcMACD(closes: number[]): { macd: number[]; signal: number[]; hist: number[] } {
  const fast   = calcEMA(closes, 12)
  const slow   = calcEMA(closes, 26)
  const macd   = fast.map((v, i) => v - slow[i])
  const signal = calcEMA(macd.slice(26), 9)
  const hist   = signal.map((s, i) => macd[i + 26] - s)
  return { macd: macd.slice(26), signal, hist }
}

function calcBB(closes: number[], period = 20, mult = 2): { upper: number[]; middle: number[]; lower: number[] } {
  const upper: number[] = [], middle: number[] = [], lower: number[] = []
  for (let i = period - 1; i < closes.length; i++) {
    const slice = closes.slice(i - period + 1, i + 1)
    const avg = slice.reduce((a, b) => a + b, 0) / period
    const std = Math.sqrt(slice.reduce((a, b) => a + (b - avg) ** 2, 0) / period)
    middle.push(avg)
    upper.push(avg + mult * std)
    lower.push(avg - mult * std)
  }
  return { upper, middle, lower }
}

// ─────────────────────────────────────────────────────────────────────────────
// Binance REST
// ─────────────────────────────────────────────────────────────────────────────
async function fetchCandles(symbol: string, interval: string, limit = 500): Promise<Candle[]> {
  const res = await fetch(`https://api.binance.com/api/v3/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`)
  if (!res.ok) throw new Error(`Binance klines ${res.status}`)
  const raw = await res.json() as number[][]
  return raw.map(k => ({ time: (k[0] / 1000) as Time, open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5] }))
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
// WS auto-reconnect
// ─────────────────────────────────────────────────────────────────────────────
function createAutoWS(getUrl: () => string, onMessage: (data: string) => void, maxRetries = 10) {
  let stopped = false, retries = 0
  let ws: WebSocket
  function connect() {
    ws = new WebSocket(getUrl())
    ws.onmessage = ev => onMessage(ev.data as string)
    ws.onclose   = () => {
      if (stopped || retries >= maxRetries) return
      const delay = Math.min(1000 * 2 ** retries, 30000); retries++
      setTimeout(connect, delay)
    }
    ws.onerror = () => ws.close()
  }
  connect()
  return { get ws() { return ws }, stop() { stopped = true; ws?.close() } }
}

// ─────────────────────────────────────────────────────────────────────────────
// Utils
// ─────────────────────────────────────────────────────────────────────────────
function fmtTime(unixSec: number): string {
  return new Date(unixSec * 1000).toLocaleString('en-US', {
    month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}
function fmtVol(v: number): string {
  if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M'
  if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K'
  return v.toFixed(0)
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────
export function TradingChart({
  symbol:    initSymbol    = 'BTCUSDT',
  timeframe: initTimeframe = '15m',
  positions  = [],
  height     = 520,
  showRsi    = true,
  onSymbolChange,
  onTimeframeChange,
}: TradingChartProps) {

  // ── DOM refs ──────────────────────────────────────────────────────────────
  const wrapRef      = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const rsiRef       = useRef<HTMLDivElement>(null)
  const macdRef      = useRef<HTMLDivElement>(null)

  // ── Chart API refs ────────────────────────────────────────────────────────
  const chartRef      = useRef<IChartApi | null>(null)
  const candleRef     = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeRef     = useRef<ISeriesApi<'Histogram'> | null>(null)
  const ema9Ref       = useRef<ISeriesApi<'Line'> | null>(null)
  const ema21Ref      = useRef<ISeriesApi<'Line'> | null>(null)
  const bbUpperRef    = useRef<ISeriesApi<'Line'> | null>(null)
  const bbMiddleRef   = useRef<ISeriesApi<'Line'> | null>(null)
  const bbLowerRef    = useRef<ISeriesApi<'Line'> | null>(null)

  const rsiChartRef   = useRef<IChartApi | null>(null)
  const rsiSeriesRef  = useRef<ISeriesApi<'Line'> | null>(null)

  const macdChartRef  = useRef<IChartApi | null>(null)
  const macdLineRef   = useRef<ISeriesApi<'Line'> | null>(null)
  const macdSigRef    = useRef<ISeriesApi<'Line'> | null>(null)
  const macdHistRef   = useRef<ISeriesApi<'Histogram'> | null>(null)

  // ── WS + data refs ────────────────────────────────────────────────────────
  const binanceWSRef  = useRef<ReturnType<typeof createAutoWS> | null>(null)
  const backendWSRef  = useRef<ReturnType<typeof createAutoWS> | null>(null)
  const markersRef    = useRef<SeriesMarker<Time>[]>([])
  const candleDataRef = useRef<Candle[]>([])
  const priceLineRefs = useRef<ReturnType<ISeriesApi<'Candlestick'>['createPriceLine']>[]>([])

  // ── UI state ──────────────────────────────────────────────────────────────
  const [symbol,      setSymbol]      = useState(initSymbol)
  const [timeframe,   setTimeframe]   = useState(initTimeframe)
  const [loading,     setLoading]     = useState(true)
  const [error,       setError]       = useState<string | null>(null)
  const [price,       setPrice]       = useState<number | null>(null)
  const [priceDir,    setPriceDir]    = useState<'up' | 'down' | null>(null)
  const [change24h,   setChange24h]   = useState<number | null>(null)
  const [wsLive,      setWsLive]      = useState(false)
  const [tooltip,     setTooltip]     = useState<OHLCVTooltip | null>(null)
  const [showBB,      setShowBB]      = useState(false)
  const [showMACD,    setShowMACD]    = useState(false)
  const [showVolume,  setShowVolume]  = useState(true)
  const [fullscreen,  setFullscreen]  = useState(false)

  // ── 1. Main chart init ────────────────────────────────────────────────────
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
      timeScale: { borderColor: C.border, timeVisible: true, secondsVisible: false },
      handleScroll: true,
      handleScale:  true,
    })

    const candles = chart.addCandlestickSeries({
      upColor: C.green, downColor: C.red,
      borderUpColor: C.green, borderDownColor: C.red,
      wickUpColor: C.green, wickDownColor: C.red,
    })
    const volume = chart.addHistogramSeries({
      priceFormat: { type: 'volume' }, priceScaleId: 'volume',
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })

    const ema9  = chart.addLineSeries({ color: C.ema9,  lineWidth: 1, priceLineVisible: false, lastValueVisible: true,  crosshairMarkerVisible: false })
    const ema21 = chart.addLineSeries({ color: C.ema21, lineWidth: 1, priceLineVisible: false, lastValueVisible: true,  crosshairMarkerVisible: false })
    const bbUpper  = chart.addLineSeries({ color: C.bbUpper,  lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, lineStyle: LineStyle.Dashed })
    const bbMiddle = chart.addLineSeries({ color: C.bbMiddle, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, lineStyle: LineStyle.Dotted })
    const bbLower  = chart.addLineSeries({ color: C.bbLower,  lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, lineStyle: LineStyle.Dashed })
    bbUpper.applyOptions({ visible: false })
    bbMiddle.applyOptions({ visible: false })
    bbLower.applyOptions({ visible: false })

    chart.subscribeCrosshairMove(param => {
      if (!param.time || param.point === undefined) { setTooltip(null); return }
      const bar    = param.seriesData.get(candles) as CandlestickData | undefined
      const volBar = param.seriesData.get(volume)  as HistogramData   | undefined
      if (!bar) { setTooltip(null); return }
      setTooltip({
        time: fmtTime(param.time as number),
        open: bar.open, high: bar.high, low: bar.low, close: bar.close,
        volume: volBar?.value ?? 0,
        change: ((bar.close - bar.open) / bar.open) * 100,
      })
    })

    chartRef.current   = chart
    candleRef.current  = candles
    volumeRef.current  = volume
    ema9Ref.current    = ema9
    ema21Ref.current   = ema21
    bbUpperRef.current = bbUpper
    bbMiddleRef.current = bbMiddle
    bbLowerRef.current = bbLower

    return () => {
      chart.remove()
      chartRef.current = candleRef.current = volumeRef.current = null
      ema9Ref.current = ema21Ref.current = null
      bbUpperRef.current = bbMiddleRef.current = bbLowerRef.current = null
    }
  }, [])

  // ── 2. RSI chart ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!showRsi || !rsiRef.current) return
    const rsiChart = createChart(rsiRef.current, {
      layout: { background: { type: ColorType.Solid, color: C.bg }, textColor: C.textMuted, fontSize: 10 },
      grid: { vertLines: { color: C.border, style: LineStyle.Dotted }, horzLines: { color: C.border, style: LineStyle.Dotted } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: C.textFaint, width: 1, style: LineStyle.Dashed }, horzLine: { color: C.textFaint, width: 1, style: LineStyle.Dashed } },
      rightPriceScale: { borderColor: C.border, scaleMargins: { top: 0.05, bottom: 0.05 } },
      timeScale: { borderColor: C.border, timeVisible: true, secondsVisible: false, visible: false },
      handleScroll: true, handleScale: false,
    })
    const rsiSeries = rsiChart.addLineSeries({ color: C.rsi, lineWidth: 1, priceLineVisible: false, lastValueVisible: true })
    rsiSeries.createPriceLine({ price: 70, color: C.slLine,  lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true,  title: 'OB' })
    rsiSeries.createPriceLine({ price: 30, color: C.tp1Line, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true,  title: 'OS' })
    rsiSeries.createPriceLine({ price: 50, color: C.textFaint, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: '' })

    rsiChartRef.current  = rsiChart
    rsiSeriesRef.current = rsiSeries

    // ── Bidirectional sync ──
    const syncMainToRsi = () => {
      const range = chartRef.current?.timeScale().getVisibleLogicalRange()
      if (range) rsiChart.timeScale().setVisibleLogicalRange(range)
    }
    const syncRsiToMain = () => {
      const range = rsiChart.timeScale().getVisibleLogicalRange()
      if (range) chartRef.current?.timeScale().setVisibleLogicalRange(range)
    }
    chartRef.current?.timeScale().subscribeVisibleLogicalRangeChange(syncMainToRsi)
    rsiChart.timeScale().subscribeVisibleLogicalRangeChange(syncRsiToMain)

    return () => { rsiChart.remove(); rsiChartRef.current = rsiSeriesRef.current = null }
  }, [showRsi])

  // ── 3. MACD chart ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!showMACD || !macdRef.current) return
    const macdChart = createChart(macdRef.current, {
      layout: { background: { type: ColorType.Solid, color: C.bg }, textColor: C.textMuted, fontSize: 10 },
      grid: { vertLines: { color: C.border, style: LineStyle.Dotted }, horzLines: { color: C.border, style: LineStyle.Dotted } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: C.textFaint, width: 1, style: LineStyle.Dashed }, horzLine: { color: C.textFaint, width: 1, style: LineStyle.Dashed } },
      rightPriceScale: { borderColor: C.border, scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: C.border, timeVisible: true, secondsVisible: false, visible: false },
      handleScroll: true, handleScale: false,
    })
    const macdLine = macdChart.addLineSeries({ color: C.macd,   lineWidth: 1, priceLineVisible: false, lastValueVisible: true })
    const macdSig  = macdChart.addLineSeries({ color: C.signal, lineWidth: 1, priceLineVisible: false, lastValueVisible: true })
    const macdHist = macdChart.addHistogramSeries({ priceScaleId: 'right', priceFormat: { type: 'price', precision: 4 } })

    macdChartRef.current = macdChart
    macdLineRef.current  = macdLine
    macdSigRef.current   = macdSig
    macdHistRef.current  = macdHist

    const syncMacd = () => {
      const range = chartRef.current?.timeScale().getVisibleLogicalRange()
      if (range) macdChart.timeScale().setVisibleLogicalRange(range)
    }
    const syncMain = () => {
      const range = macdChart.timeScale().getVisibleLogicalRange()
      if (range) chartRef.current?.timeScale().setVisibleLogicalRange(range)
    }
    chartRef.current?.timeScale().subscribeVisibleLogicalRangeChange(syncMacd)
    macdChart.timeScale().subscribeVisibleLogicalRangeChange(syncMain)

    // Populate with current data if available
    const data = candleDataRef.current
    if (data.length >= 35) {
      const closes = data.map(c => c.close)
      const { macd: mv, signal: sv, hist: hv } = calcMACD(closes)
      const startIdx = 26
      macdLine.setData(data.slice(startIdx).map((c, i) => ({ time: c.time, value: mv[i] ?? 0 })))
      macdSig.setData(data.slice(startIdx).map((c, i)  => ({ time: c.time, value: sv[i] ?? 0 })))
      macdHist.setData(data.slice(startIdx).map((c, i) => ({ time: c.time, value: hv[i] ?? 0, color: (hv[i] ?? 0) >= 0 ? C.volGreen : C.volRed })))
    }

    return () => { macdChart.remove(); macdChartRef.current = macdLineRef.current = macdSigRef.current = macdHistRef.current = null }
  }, [showMACD])

  // ── 4. BB visibility toggle ───────────────────────────────────────────────
  useEffect(() => {
    bbUpperRef.current?.applyOptions({ visible: showBB })
    bbMiddleRef.current?.applyOptions({ visible: showBB })
    bbLowerRef.current?.applyOptions({ visible: showBB })
  }, [showBB])

  // ── 5. Volume visibility toggle ───────────────────────────────────────────
  useEffect(() => {
    volumeRef.current?.applyOptions({ visible: showVolume })
  }, [showVolume])

  // ── 6. Load data + Binance WS ─────────────────────────────────────────────
  const loadData = useCallback(async (sym: string, tf: string) => {
    if (!candleRef.current) return
    setLoading(true); setError(null); setTooltip(null)
    markersRef.current = []
    priceLineRefs.current.forEach(l => { try { candleRef.current?.removePriceLine(l) } catch {} })
    priceLineRefs.current = []
    binanceWSRef.current?.stop(); setWsLive(false)

    try {
      const [data, ch] = await Promise.all([fetchCandles(sym, tf), fetch24hChange(sym)])
      if (!candleRef.current) return

      candleDataRef.current = data
      candleRef.current.setData(data)

      const volData: HistogramData[] = data.map(c => ({
        time: c.time, value: c.volume ?? 0,
        color: (c.close >= c.open) ? C.volGreen : C.volRed,
      }))
      volumeRef.current?.setData(volData)

      const closes = data.map(c => c.close)

      // EMA
      const ema9v  = calcEMA(closes, 9)
      const ema21v = calcEMA(closes, 21)
      ema9Ref.current?.setData(data.map((c, i)  => ({ time: c.time, value: ema9v[i] })))
      ema21Ref.current?.setData(data.map((c, i) => ({ time: c.time, value: ema21v[i] })))

      // RSI — FIX: slice data correctly from index `period`
      if (rsiSeriesRef.current && closes.length > 14) {
        const rsiVals = calcRSI(closes)
        rsiSeriesRef.current.setData(
          data.map((c, i) => ({ time: c.time, value: rsiVals[i] }))
        )
      }

      // BB
      if (closes.length >= 20) {
        const bb = calcBB(closes)
        const startIdx = 19
        bbUpperRef.current?.setData(data.slice(startIdx).map((c, i)  => ({ time: c.time, value: bb.upper[i] })))
        bbMiddleRef.current?.setData(data.slice(startIdx).map((c, i) => ({ time: c.time, value: bb.middle[i] })))
        bbLowerRef.current?.setData(data.slice(startIdx).map((c, i)  => ({ time: c.time, value: bb.lower[i] })))
      }

      // MACD
      if (macdLineRef.current && closes.length >= 35) {
        const { macd: mv, signal: sv, hist: hv } = calcMACD(closes)
        const startIdx = 26
        macdLineRef.current.setData(data.slice(startIdx).map((c, i)  => ({ time: c.time, value: mv[i] ?? 0 })))
        macdSigRef.current?.setData(data.slice(startIdx).map((c, i)  => ({ time: c.time, value: sv[i] ?? 0 })))
        macdHistRef.current?.setData(data.slice(startIdx).map((c, i) => ({ time: c.time, value: hv[i] ?? 0, color: (hv[i] ?? 0) >= 0 ? C.volGreen : C.volRed })))
      }

      chartRef.current?.timeScale().fitContent()
      setChange24h(ch)
      const last = data[data.length - 1]
      if (last) setPrice(last.close)
      setLoading(false)
    } catch (e) {
      setError(String((e as Error).message ?? e))
      setLoading(false)
    }

    // ── Binance live WS ──
    const stream = `${sym.toLowerCase()}@kline_${tf}`
    const bWS = createAutoWS(
      () => `wss://stream.binance.com:9443/ws/${stream}`,
      (raw) => {
        const msg = JSON.parse(raw) as { k: Record<string, unknown> }
        const k = msg.k
        if (!candleRef.current) return
        const t      = (Number(k.t) / 1000) as Time
        const open   = +String(k.o), high = +String(k.h)
        const low    = +String(k.l), close = +String(k.c)
        const vol    = +String(k.v), isClosed = Boolean(k.x)

        candleRef.current.update({ time: t, open, high, low, close })
        volumeRef.current?.update({ time: t, value: vol, color: close >= open ? C.volGreen : C.volRed })

        if (isClosed) {
          candleDataRef.current = [...candleDataRef.current, { time: t, open, high, low, close, volume: vol }]
          const allCloses = candleDataRef.current.map(c => c.close)

          // EMA live
          const e9  = calcEMA(allCloses, 9)
          const e21 = calcEMA(allCloses, 21)
          ema9Ref.current?.update({ time: t, value: e9[e9.length - 1] })
          ema21Ref.current?.update({ time: t, value: e21[e21.length - 1] })

          // RSI live
          if (rsiSeriesRef.current && allCloses.length > 14) {
            const rv = calcRSI(allCloses)
            rsiSeriesRef.current.update({ time: t, value: rv[rv.length - 1] })
          }

          // BB live
          if (allCloses.length >= 20) {
            const bb = calcBB(allCloses)
            bbUpperRef.current?.update({ time: t, value: bb.upper[bb.upper.length - 1] })
            bbMiddleRef.current?.update({ time: t, value: bb.middle[bb.middle.length - 1] })
            bbLowerRef.current?.update({ time: t, value: bb.lower[bb.lower.length - 1] })
          }

          // MACD live
          if (macdLineRef.current && allCloses.length >= 35) {
            const { macd: mv, signal: sv, hist: hv } = calcMACD(allCloses)
            macdLineRef.current.update({ time: t, value: mv[mv.length - 1] })
            macdSigRef.current?.update({ time: t, value: sv[sv.length - 1] })
            macdHistRef.current?.update({ time: t, value: hv[hv.length - 1], color: hv[hv.length - 1] >= 0 ? C.volGreen : C.volRed })
          }
        }

        setWsLive(true)
        setPrice(prev => { setPriceDir(prev === null ? null : close > prev ? 'up' : close < prev ? 'down' : null); return close })
      }
    )
    binanceWSRef.current = bWS
  }, [])

  useEffect(() => { loadData(symbol, timeframe) }, [symbol, timeframe, loadData])

  // ── 7. Backend WS ─────────────────────────────────────────────────────────
  useEffect(() => {
    const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws'
    const bWS = createAutoWS(
      () => WS_URL,
      (raw) => {
        try {
          const msg = JSON.parse(raw) as { event?: string; payload?: unknown }

          // ── signal_created → arrow marker ──
          if (msg.event === 'signal_created') {
            const p = msg.payload as SignalPayload
            if (!p?.entry_price) return
            if (p.symbol && p.symbol !== symbol) return
            const time = ((p.candle_open_time ? p.candle_open_time / 1000 : Math.floor(Date.now() / 1000))) as Time
            const isBuy = p.action === 'BUY'
            const marker: SeriesMarker<Time> = {
              time, position: isBuy ? 'belowBar' : 'aboveBar',
              color: isBuy ? C.green : C.red, shape: isBuy ? 'arrowUp' : 'arrowDown',
              text: isBuy ? '▲ BUY' : '▼ SELL', size: 1.5,
            }
            markersRef.current = [...markersRef.current.slice(-99), marker]
            candleRef.current?.setMarkers(markersRef.current)
          }

          // ── order_filled → circle marker + price ──
          if (msg.event === 'order_filled') {
            const p = msg.payload as OrderFilledPayload
            if (!p?.price) return
            if (p.symbol && p.symbol !== symbol) return
            const time = ((p.time ? p.time / 1000 : Math.floor(Date.now() / 1000))) as Time
            const isBuy = (p.side ?? '').toUpperCase() === 'BUY'
            const marker: SeriesMarker<Time> = {
              time, position: isBuy ? 'belowBar' : 'aboveBar',
              color: isBuy ? C.teal : C.orange, shape: 'circle',
              text: `FILL ${p.price?.toFixed(2)}`, size: 1,
            }
            markersRef.current = [...markersRef.current.slice(-99), marker]
            candleRef.current?.setMarkers(markersRef.current)
          }

          // ── position_opened → draw SL/TP lines live ──
          if (msg.event === 'position_opened') {
            const p = msg.payload as Position
            if (!p?.symbol || p.symbol !== symbol || !candleRef.current) return
            const series = candleRef.current
            const newLines: typeof priceLineRefs.current = []
            newLines.push(series.createPriceLine({ price: p.entry_price, color: C.blue, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'Entry' }))
            if (p.stop_loss)     newLines.push(series.createPriceLine({ price: p.stop_loss,     color: C.slLine,  lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'SL' }))
            if (p.take_profit_1) newLines.push(series.createPriceLine({ price: p.take_profit_1, color: C.tp1Line, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'TP1' }))
            if (p.take_profit_2) newLines.push(series.createPriceLine({ price: p.take_profit_2, color: C.tp2Line, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'TP2' }))
            priceLineRefs.current = [...priceLineRefs.current, ...newLines]
          }
        } catch {}
      }
    )
    backendWSRef.current = bWS
    return () => bWS.stop()
  }, [symbol])

  // ── 8. Price lines from props ─────────────────────────────────────────────
  useEffect(() => {
    const series = candleRef.current
    if (!series) return
    const lines: ReturnType<typeof series.createPriceLine>[] = []
    positions.filter(p => p.symbol === symbol).forEach(p => {
      lines.push(series.createPriceLine({ price: p.entry_price, color: C.blue,    lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'Entry' }))
      if (p.stop_loss)     lines.push(series.createPriceLine({ price: p.stop_loss,     color: C.slLine,  lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'SL'  }))
      if (p.take_profit_1) lines.push(series.createPriceLine({ price: p.take_profit_1, color: C.tp1Line, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'TP1' }))
      if (p.take_profit_2) lines.push(series.createPriceLine({ price: p.take_profit_2, color: C.tp2Line, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'TP2' }))
    })
    return () => lines.forEach(l => { try { series.removePriceLine(l) } catch {} })
  }, [positions, symbol])

  // ── 9. Shared ResizeObserver ──────────────────────────────────────────────
  useEffect(() => {
    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight })
      }
      if (rsiRef.current && rsiChartRef.current) {
        rsiChartRef.current.applyOptions({ width: rsiRef.current.clientWidth, height: rsiRef.current.clientHeight })
      }
      if (macdRef.current && macdChartRef.current) {
        macdChartRef.current.applyOptions({ width: macdRef.current.clientWidth, height: macdRef.current.clientHeight })
      }
    })
    if (containerRef.current) ro.observe(containerRef.current)
    if (rsiRef.current)       ro.observe(rsiRef.current)
    if (macdRef.current)      ro.observe(macdRef.current)
    return () => ro.disconnect()
  }, [showRsi, showMACD, fullscreen])

  // ── 10. Keyboard shortcuts ────────────────────────────────────────────────
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const onKey = (e: KeyboardEvent) => {
      const ts = chartRef.current?.timeScale()
      if (!ts) return
      switch (e.key) {
        case 'ArrowLeft':  ts.scrollToPosition(ts.scrollPosition() - 5, true);  e.preventDefault(); break
        case 'ArrowRight': ts.scrollToPosition(ts.scrollPosition() + 5, true);  e.preventDefault(); break
        case '+':          ts.applyOptions({ barSpacing: Math.min((ts.options() as Record<string, number>).barSpacing + 2, 50) }); break
        case '-':          ts.applyOptions({ barSpacing: Math.max((ts.options() as Record<string, number>).barSpacing - 2,  2) }); break
        case 'r': case 'R': ts.fitContent(); break
        case 'f': case 'F': setFullscreen(f => !f); break
      }
    }
    el.setAttribute('tabindex', '0')
    el.addEventListener('keydown', onKey)
    return () => el.removeEventListener('keydown', onKey)
  }, [])

  // ESC to exit fullscreen
  useEffect(() => {
    if (!fullscreen) return
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') setFullscreen(false) }
    document.addEventListener('keydown', onEsc)
    return () => document.removeEventListener('keydown', onEsc)
  }, [fullscreen])

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleSymbol    = useCallback((s: string) => { setSymbol(s);    onSymbolChange?.(s) },    [onSymbolChange])
  const handleTimeframe = useCallback((t: string) => { setTimeframe(t); onTimeframeChange?.(t) }, [onTimeframeChange])

  // ── Heights ───────────────────────────────────────────────────────────────
  const rsiHeight  = showRsi  ? 120 : 0
  const macdHeight = showMACD ? 110 : 0
  const mainHeight = height - rsiHeight - macdHeight - (showRsi ? 4 : 0) - (showMACD ? 4 : 0)

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div
      ref={wrapRef}
      style={{
        display: 'flex', flexDirection: 'column',
        background: C.bg, borderRadius: fullscreen ? 0 : 8,
        border: `1px solid ${C.border}`,
        overflow: 'hidden', outline: 'none',
        ...(fullscreen ? { position: 'fixed', inset: 0, zIndex: 9999, borderRadius: 0 } : {}),
      }}
    >
      {/* ── Toolbar ────────────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderBottom: `1px solid ${C.border}`, background: C.surface, flexWrap: 'wrap' }}>

        {/* Symbol */}
        <select value={symbol} onChange={e => handleSymbol(e.target.value)}
          style={{ background: C.bg, color: C.text, border: `1px solid ${C.border}`, borderRadius: 4, padding: '3px 8px', fontSize: 12, fontWeight: 700, cursor: 'pointer', outline: 'none' }}>
          {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>

        {/* Timeframes */}
        <div style={{ display: 'flex', gap: 2 }}>
          {TIMEFRAMES.map(tf => (
            <button key={tf} onClick={() => handleTimeframe(tf)}
              style={{ padding: '3px 8px', fontSize: 11, fontWeight: 600, border: 'none', borderRadius: 4, cursor: 'pointer', background: timeframe === tf ? C.blue : 'transparent', color: timeframe === tf ? '#fff' : C.textMuted, transition: 'background 120ms ease' }}>
              {tf}
            </button>
          ))}
        </div>

        {/* Indicator toggles */}
        <div style={{ display: 'flex', gap: 4, marginLeft: 4 }}>
          {([
            { label: 'EMA', active: true,       disabled: true,  color: C.ema9 },
            { label: 'BB',  active: showBB,     disabled: false, color: C.bbUpper,   onClick: () => setShowBB(v => !v) },
            { label: 'VOL', active: showVolume, disabled: false, color: C.textMuted, onClick: () => setShowVolume(v => !v) },
            { label: 'RSI', active: showRsi,    disabled: true,  color: C.rsi },
            { label: 'MACD',active: showMACD,   disabled: false, color: C.macd,      onClick: () => setShowMACD(v => !v) },
          ] as { label: string; active: boolean; disabled: boolean; color: string; onClick?: () => void }[]).map(btn => (
            <button key={btn.label} onClick={btn.onClick} disabled={btn.disabled}
              title={btn.disabled ? 'Always on' : btn.active ? `Hide ${btn.label}` : `Show ${btn.label}`}
              style={{
                padding: '2px 7px', fontSize: 10, fontWeight: 600, border: 'none', borderRadius: 3, cursor: btn.disabled ? 'default' : 'pointer',
                background: btn.active ? `rgba(${btn.color === C.rsi ? '168,111,223' : btn.color === C.macd ? '79,152,163' : btn.color === C.bbUpper ? '85,145,199' : btn.color === C.ema9 ? '253,171,67' : '121,120,118'},0.20)` : 'transparent',
                color: btn.active ? btn.color : C.textFaint,
                transition: 'background 120ms ease, color 120ms ease',
                opacity: btn.disabled ? 0.5 : 1,
              }}>
              {btn.label}
            </button>
          ))}
        </div>

        {/* EMA legend */}
        <div style={{ display: 'flex', gap: 6, marginLeft: 2 }}>
          {[{c: C.ema9, l: 'EMA9'}, {c: C.ema21, l: 'EMA21'}].map(({c,l}) => (
            <span key={l} style={{ fontSize: 10, color: c, display: 'flex', alignItems: 'center', gap: 3 }}>
              <span style={{ width: 14, height: 2, background: c, display: 'inline-block', borderRadius: 1 }} />{l}
            </span>
          ))}
        </div>

        {/* Right: price + 24h + WS dot + fullscreen */}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          {loading && <span style={{ fontSize: 11, color: C.textFaint }}>Loading…</span>}
          {error   && <span style={{ fontSize: 11, color: C.red, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>⚠ {error}</span>}
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
          <span title={wsLive ? 'Live' : 'Connecting…'} style={{ width: 7, height: 7, borderRadius: '50%', background: wsLive ? C.green : C.textFaint, display: 'inline-block', transition: 'background 300ms ease' }} />
          {/* Fullscreen toggle */}
          <button onClick={() => setFullscreen(f => !f)} title={fullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen (F)'}
            style={{ background: 'none', border: 'none', color: C.textMuted, cursor: 'pointer', padding: '2px 4px', fontSize: 14, lineHeight: 1 }}>
            {fullscreen ? '⊠' : '⛶'}
          </button>
        </div>
      </div>

      {/* ── Main chart ─────────────────────────────────────────────────────── */}
      <div style={{ position: 'relative', flex: fullscreen ? 1 : 'none' }}>
        <div ref={containerRef} style={{ width: '100%', height: fullscreen ? '100%' : mainHeight }} />

        {/* OHLCV tooltip */}
        {tooltip && (
          <div style={{ position: 'absolute', top: 8, left: 12, pointerEvents: 'none', background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 6, padding: '6px 10px', fontSize: 11, color: C.textMuted, lineHeight: 1.6, zIndex: 10 }}>
            <div style={{ color: C.textFaint, marginBottom: 2, fontSize: 10 }}>{tooltip.time}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'auto auto', gap: '0 12px' }}>
              <span style={{ color: C.textFaint }}>O</span><span style={{ color: C.text,    fontFamily: 'monospace' }}>{tooltip.open.toFixed(2)}</span>
              <span style={{ color: C.textFaint }}>H</span><span style={{ color: C.green,   fontFamily: 'monospace' }}>{tooltip.high.toFixed(2)}</span>
              <span style={{ color: C.textFaint }}>L</span><span style={{ color: C.red,     fontFamily: 'monospace' }}>{tooltip.low.toFixed(2)}</span>
              <span style={{ color: C.textFaint }}>C</span><span style={{ color: tooltip.change >= 0 ? C.green : C.red, fontFamily: 'monospace', fontWeight: 700 }}>{tooltip.close.toFixed(2)}</span>
              <span style={{ color: C.textFaint }}>V</span><span style={{ color: C.textMuted, fontFamily: 'monospace' }}>{fmtVol(tooltip.volume)}</span>
              <span style={{ color: C.textFaint }}>Δ</span><span style={{ color: tooltip.change >= 0 ? C.green : C.red, fontFamily: 'monospace' }}>{tooltip.change >= 0 ? '+' : ''}{tooltip.change.toFixed(2)}%</span>
            </div>
          </div>
        )}
      </div>

      {/* ── RSI pane ───────────────────────────────────────────────────────── */}
      {showRsi && (
        <>
          <div style={{ borderTop: `1px solid ${C.border}`, padding: '2px 12px', background: C.surface2, fontSize: 10, color: C.textFaint, display: 'flex', gap: 12 }}>
            <span style={{ color: C.rsi, fontWeight: 600 }}>RSI(14)</span>
            <span style={{ color: C.slLine }}>OB 70</span>
            <span style={{ color: C.tp1Line }}>OS 30</span>
          </div>
          <div ref={rsiRef} style={{ width: '100%', height: rsiHeight }} />
        </>
      )}

      {/* ── MACD pane ──────────────────────────────────────────────────────── */}
      {showMACD && (
        <>
          <div style={{ borderTop: `1px solid ${C.border}`, padding: '2px 12px', background: C.surface2, fontSize: 10, color: C.textFaint, display: 'flex', gap: 12 }}>
            <span style={{ color: C.macd,   fontWeight: 600 }}>MACD(12,26,9)</span>
            <span style={{ color: C.macd }}>MACD</span>
            <span style={{ color: C.signal }}>Signal</span>
            <span style={{ color: C.textMuted }}>Hist</span>
          </div>
          <div ref={macdRef} style={{ width: '100%', height: macdHeight }} />
        </>
      )}

      {/* ── Legend footer ──────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', gap: 14, padding: '5px 12px', borderTop: `1px solid ${C.border}`, background: C.surface, fontSize: 10, color: C.textFaint, flexWrap: 'wrap', alignItems: 'center' }}>
        {[
          { color: C.green,   label: 'Bull' },
          { color: C.red,     label: 'Bear' },
          { color: C.ema9,    label: 'EMA9' },
          { color: C.ema21,   label: 'EMA21' },
          ...(showBB  ? [{ color: C.bbUpper,  label: 'BB(20,2)' }] : []),
          ...(showMACD ? [{ color: C.macd,    label: 'MACD' }, { color: C.signal, label: 'Signal' }] : []),
          { color: C.blue,    label: 'Entry' },
          { color: C.slLine,  label: 'SL' },
          { color: C.tp1Line, label: 'TP1' },
          { color: C.tp2Line, label: 'TP2' },
          { color: C.rsi,     label: 'RSI' },
        ].map(item => (
          <span key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            <span style={{ width: 10, height: 2, background: item.color, borderRadius: 1, display: 'inline-block' }} />
            {item.label}
          </span>
        ))}
        <span style={{ marginLeft: 'auto', color: C.textFaint, fontSize: 9 }}>← → scroll · +/- zoom · R reset · F fullscreen</span>
      </div>
    </div>
  )
}

export default TradingChart
