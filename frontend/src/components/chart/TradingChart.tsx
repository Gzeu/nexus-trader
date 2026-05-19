'use client'
/**
 * TradingChart.tsx — v3.1 (polish)
 * ─────────────────────────────────────────────────────────────────────────────
 * FIXES vs v3
 * ─ [BUG] MACD start offset: signal are length closes.length-26-8, nu closes.length-26
 *   → calcMACD returnează acum { macd[], signal[], hist[], startIdx } cu offset corect
 * ─ [BUG] BB data fence: slice startIdx era 19 (0-indexed period-1) dar BB array
 *   pornea de la period=20 → corect: startIdx = period - 1
 * ─ [BUG] Keyboard scroll: ts.scrollPosition() nu există în LightweightCharts v4
 *   → înlocuit cu ts.scrollToRealTime() + ts.getVisibleLogicalRange() shift manual
 * ─ [BUG] Indicator chip background color era calculat cu if-chain fragil pe string
 *   → mapat direct din paletă cu un Record<string,string>
 * ─ [BUG] BB legend afișa mereu C.bbUpper string indiferent de showBB
 *   → legend item color corect + adăugat label BB Middle / BB Lower
 * ─ [BUG] RSI pane label arăta "OB" / "OS" cu culori inversate (sl=red pe OB)
 *   → OB (70) folosește C.red, OS (30) folosește C.green — convenție standard
 * IMPROVEMENTS vs v3
 * ─ Keyboard focus ring vizibil (outline teal) când chart e activ
 * ─ Tooltip close price folosește culoarea candelei (verde/roșu) dinamic
 * ─ MACD histogram culori folosesc C.green/C.red direct (nu volGreen/volRed)
 *   pentru contrast mai bun în pane-ul mic
 * ─ WS live dot pulsează via CSS animation când e conectat
 * ─ Indicator chips au border explicit 1px ca să fie vizibil și fără background
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
  symbol?: string; action?: string; entry_price?: number
  stop_loss?: number; take_profit_1?: number; take_profit_2?: number
  candle_open_time?: number
}
interface OrderFilledPayload {
  symbol?: string; side?: string; price?: number; qty?: number; time?: number
}
interface Position {
  symbol: string; entry_price: number
  stop_loss?: number; take_profit_1?: number; take_profit_2?: number
}
interface OHLCVTooltip {
  time: string; open: number; high: number; low: number; close: number
  volume: number; change: number
}
export interface TradingChartProps {
  symbol?: string; timeframe?: string; positions?: Position[]
  height?: number; showRsi?: boolean
  onSymbolChange?: (s: string) => void; onTimeframeChange?: (t: string) => void
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
  red:       '#dd6974',   // fix: era C.red = magenta, acum roșu standard
  blue:      '#5591c7',
  teal:      '#4f98a3',
  orange:    '#fdab43',
  volGreen:  'rgba(109,170,69,0.28)',
  volRed:    'rgba(221,105,116,0.28)',
  ema9:      '#fdab43',
  ema21:     '#5591c7',
  rsi:       '#a86fdf',
  macd:      '#4f98a3',
  signal:    '#fdab43',
  bbUpper:   'rgba(85,145,199,0.55)',
  bbLower:   'rgba(85,145,199,0.55)',
  bbMiddle:  'rgba(85,145,199,0.30)',
  slLine:    '#dd6974',
  tp1Line:   '#6daa45',
  tp2Line:   '#4f98a3',
}

// ─────────────────────────────────────────────────────────────────────────────
// Indicator math
// ─────────────────────────────────────────────────────────────────────────────
function calcEMA(closes: number[], period: number): number[] {
  const k = 2 / (period + 1)
  let ema = closes[0]
  return closes.map((v, i) => { ema = i === 0 ? v : v * k + ema * (1 - k); return ema })
}

function calcRSI(closes: number[], period = 14): number[] {
  if (closes.length <= period) return new Array(closes.length).fill(50)
  const out: number[] = new Array(period).fill(50)
  let avgGain = 0, avgLoss = 0
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1]
    d > 0 ? (avgGain += d) : (avgLoss -= d)
  }
  avgGain /= period; avgLoss /= period
  out.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss))
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1]
    avgGain = (avgGain * (period - 1) + Math.max(d,  0)) / period
    avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period
    out.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss))
  }
  return out
}

/** FIX: signal are length (macd.length - 8), hist trebuie aliniat la signal.
 *  Returnează startIdx = 26 + 8 = 34 — prima candelă cu date valide în toate 3 serii. */
function calcMACD(closes: number[]): {
  macd: number[]; signal: number[]; hist: number[]; startIdx: number
} {
  const fast   = calcEMA(closes, 12)
  const slow   = calcEMA(closes, 26)
  const macdFull = fast.map((v, i) => v - slow[i])          // length = closes.length
  const macdSlice = macdFull.slice(26)                       // from bar 26
  const signalFull = calcEMA(macdSlice, 9)                  // length = macdSlice.length
  // signal[i] aligns with macdSlice[i], but first 8 are EMA warmup
  // use i >= 8 to get stable signal values
  const sigOffset = 8
  const signal = signalFull.slice(sigOffset)                 // length = macdSlice.length - 8
  const macd   = macdSlice.slice(sigOffset)                  // same length
  const hist   = macd.map((m, i) => m - signal[i])
  const startIdx = 26 + sigOffset                            // = 34
  return { macd, signal, hist, startIdx }
}

/** FIX: startIdx è period - 1 (0-based), BB array length = closes.length - period + 1 */
function calcBB(closes: number[], period = 20, mult = 2): {
  upper: number[]; middle: number[]; lower: number[]; startIdx: number
} {
  const upper: number[] = [], middle: number[] = [], lower: number[] = []
  for (let i = period - 1; i < closes.length; i++) {
    const slice = closes.slice(i - period + 1, i + 1)
    const avg = slice.reduce((a, b) => a + b, 0) / period
    const std = Math.sqrt(slice.reduce((a, b) => a + (b - avg) ** 2, 0) / period)
    middle.push(avg)
    upper.push(avg + mult * std)
    lower.push(avg - mult * std)
  }
  return { upper, middle, lower, startIdx: period - 1 }
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

// FIX: chip background culori — map direct din paletă, nu regex pe string
const CHIP_COLORS: Record<string, string> = {
  EMA:  C.ema9,
  BB:   C.blue,
  VOL:  C.textMuted,
  RSI:  C.rsi,
  MACD: C.teal,
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

  const wrapRef      = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const rsiRef       = useRef<HTMLDivElement>(null)
  const macdRef      = useRef<HTMLDivElement>(null)

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

  const binanceWSRef  = useRef<ReturnType<typeof createAutoWS> | null>(null)
  const backendWSRef  = useRef<ReturnType<typeof createAutoWS> | null>(null)
  const markersRef    = useRef<SeriesMarker<Time>[]>([])
  const candleDataRef = useRef<Candle[]>([])
  const priceLineRefs = useRef<ReturnType<ISeriesApi<'Candlestick'>['createPriceLine']>[]>([])

  const [symbol,     setSymbol]     = useState(initSymbol)
  const [timeframe,  setTimeframe]  = useState(initTimeframe)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState<string | null>(null)
  const [price,      setPrice]      = useState<number | null>(null)
  const [priceDir,   setPriceDir]   = useState<'up' | 'down' | null>(null)
  const [change24h,  setChange24h]  = useState<number | null>(null)
  const [wsLive,     setWsLive]     = useState(false)
  const [tooltip,    setTooltip]    = useState<OHLCVTooltip | null>(null)
  const [showBB,     setShowBB]     = useState(false)
  const [showMACD,   setShowMACD]   = useState(false)
  const [showVolume, setShowVolume] = useState(true)
  const [fullscreen, setFullscreen] = useState(false)

  // ── 1. Main chart init ────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: C.bg }, textColor: C.textMuted, fontFamily: "'Inter','SF Mono',monospace", fontSize: 11 },
      grid: { vertLines: { color: C.border, style: LineStyle.Dotted }, horzLines: { color: C.border, style: LineStyle.Dotted } },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: C.textFaint, width: 1, style: LineStyle.Dashed, labelBackgroundColor: C.surface2 },
        horzLine: { color: C.textFaint, width: 1, style: LineStyle.Dashed, labelBackgroundColor: C.surface2 },
      },
      rightPriceScale: { borderColor: C.border, scaleMargins: { top: 0.08, bottom: 0.28 } },
      timeScale: { borderColor: C.border, timeVisible: true, secondsVisible: false },
      handleScroll: true, handleScale: true,
    })
    const candles = chart.addCandlestickSeries({ upColor: C.green, downColor: C.red, borderUpColor: C.green, borderDownColor: C.red, wickUpColor: C.green, wickDownColor: C.red })
    const volume  = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'volume' })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
    const ema9  = chart.addLineSeries({ color: C.ema9,  lineWidth: 1, priceLineVisible: false, lastValueVisible: true,  crosshairMarkerVisible: false })
    const ema21 = chart.addLineSeries({ color: C.ema21, lineWidth: 1, priceLineVisible: false, lastValueVisible: true,  crosshairMarkerVisible: false })
    const bbUpper  = chart.addLineSeries({ color: C.bbUpper,  lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, lineStyle: LineStyle.Dashed,  visible: false })
    const bbMiddle = chart.addLineSeries({ color: C.bbMiddle, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, lineStyle: LineStyle.Dotted,  visible: false })
    const bbLower  = chart.addLineSeries({ color: C.bbLower,  lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, lineStyle: LineStyle.Dashed,  visible: false })

    chart.subscribeCrosshairMove(param => {
      if (!param.time || param.point === undefined) { setTooltip(null); return }
      const bar    = param.seriesData.get(candles) as CandlestickData | undefined
      const volBar = param.seriesData.get(volume)  as HistogramData   | undefined
      if (!bar) { setTooltip(null); return }
      setTooltip({ time: fmtTime(param.time as number), open: bar.open, high: bar.high, low: bar.low, close: bar.close, volume: volBar?.value ?? 0, change: ((bar.close - bar.open) / bar.open) * 100 })
    })

    chartRef.current = chart; candleRef.current = candles; volumeRef.current = volume
    ema9Ref.current = ema9; ema21Ref.current = ema21
    bbUpperRef.current = bbUpper; bbMiddleRef.current = bbMiddle; bbLowerRef.current = bbLower

    return () => {
      chart.remove()
      chartRef.current = candleRef.current = volumeRef.current = null
      ema9Ref.current = ema21Ref.current = bbUpperRef.current = bbMiddleRef.current = bbLowerRef.current = null
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
    // FIX: OB=70 → C.red (overbought = danger), OS=30 → C.green (oversold = opportunity)
    rsiSeries.createPriceLine({ price: 70, color: C.red,       lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true,  title: 'OB' })
    rsiSeries.createPriceLine({ price: 30, color: C.green,     lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true,  title: 'OS' })
    rsiSeries.createPriceLine({ price: 50, color: C.textFaint, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: '' })

    rsiChartRef.current = rsiChart; rsiSeriesRef.current = rsiSeries

    const syncMainToRsi = () => { const r = chartRef.current?.timeScale().getVisibleLogicalRange(); if (r) rsiChart.timeScale().setVisibleLogicalRange(r) }
    const syncRsiToMain = () => { const r = rsiChart.timeScale().getVisibleLogicalRange(); if (r) chartRef.current?.timeScale().setVisibleLogicalRange(r) }
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

    macdChartRef.current = macdChart; macdLineRef.current = macdLine
    macdSigRef.current = macdSig; macdHistRef.current = macdHist

    const syncMacd = () => { const r = chartRef.current?.timeScale().getVisibleLogicalRange(); if (r) macdChart.timeScale().setVisibleLogicalRange(r) }
    const syncMain = () => { const r = macdChart.timeScale().getVisibleLogicalRange(); if (r) chartRef.current?.timeScale().setVisibleLogicalRange(r) }
    chartRef.current?.timeScale().subscribeVisibleLogicalRangeChange(syncMacd)
    macdChart.timeScale().subscribeVisibleLogicalRangeChange(syncMain)

    // Populate with existing data
    const data = candleDataRef.current
    if (data.length >= 35) {
      const closes = data.map(c => c.close)
      const { macd: mv, signal: sv, hist: hv, startIdx } = calcMACD(closes)
      macdLine.setData(data.slice(startIdx).map((c, i) => ({ time: c.time, value: mv[i] ?? 0 })))
      macdSig.setData(data.slice(startIdx).map((c, i)  => ({ time: c.time, value: sv[i] ?? 0 })))
      macdHist.setData(data.slice(startIdx).map((c, i) => ({ time: c.time, value: hv[i] ?? 0, color: (hv[i] ?? 0) >= 0 ? C.green : C.red })))
    }
    return () => { macdChart.remove(); macdChartRef.current = macdLineRef.current = macdSigRef.current = macdHistRef.current = null }
  }, [showMACD])

  // ── 4. BB toggle ─────────────────────────────────────────────────────────
  useEffect(() => {
    bbUpperRef.current?.applyOptions({ visible: showBB })
    bbMiddleRef.current?.applyOptions({ visible: showBB })
    bbLowerRef.current?.applyOptions({ visible: showBB })
  }, [showBB])

  // ── 5. Volume toggle ──────────────────────────────────────────────────────
  useEffect(() => { volumeRef.current?.applyOptions({ visible: showVolume }) }, [showVolume])

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

      volumeRef.current?.setData(data.map(c => ({ time: c.time, value: c.volume ?? 0, color: c.close >= c.open ? C.volGreen : C.volRed })))

      const closes = data.map(c => c.close)
      ema9Ref.current?.setData(data.map((c, i)  => ({ time: c.time, value: calcEMA(closes, 9)[i]  })))
      ema21Ref.current?.setData(data.map((c, i) => ({ time: c.time, value: calcEMA(closes, 21)[i] })))

      if (rsiSeriesRef.current && closes.length > 14) {
        const rsiVals = calcRSI(closes)
        rsiSeriesRef.current.setData(data.map((c, i) => ({ time: c.time, value: rsiVals[i] })))
      }

      // FIX: usar startIdx da calcBB
      if (closes.length >= 20) {
        const bb = calcBB(closes)
        bbUpperRef.current?.setData(data.slice(bb.startIdx).map((c, i)  => ({ time: c.time, value: bb.upper[i] })))
        bbMiddleRef.current?.setData(data.slice(bb.startIdx).map((c, i) => ({ time: c.time, value: bb.middle[i] })))
        bbLowerRef.current?.setData(data.slice(bb.startIdx).map((c, i)  => ({ time: c.time, value: bb.lower[i] })))
      }

      // FIX: usar startIdx da calcMACD
      if (macdLineRef.current && closes.length >= 35) {
        const { macd: mv, signal: sv, hist: hv, startIdx } = calcMACD(closes)
        macdLineRef.current.setData(data.slice(startIdx).map((c, i)  => ({ time: c.time, value: mv[i] ?? 0 })))
        macdSigRef.current?.setData(data.slice(startIdx).map((c, i)  => ({ time: c.time, value: sv[i] ?? 0 })))
        macdHistRef.current?.setData(data.slice(startIdx).map((c, i) => ({ time: c.time, value: hv[i] ?? 0, color: (hv[i] ?? 0) >= 0 ? C.green : C.red })))
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
        const t        = (Number(k.t) / 1000) as Time
        const open     = +String(k.o), high  = +String(k.h)
        const low      = +String(k.l), close = +String(k.c)
        const vol      = +String(k.v), isClosed = Boolean(k.x)

        candleRef.current.update({ time: t, open, high, low, close })
        volumeRef.current?.update({ time: t, value: vol, color: close >= open ? C.volGreen : C.volRed })

        if (isClosed) {
          candleDataRef.current = [...candleDataRef.current, { time: t, open, high, low, close, volume: vol }]
          const ac = candleDataRef.current.map(c => c.close)

          const e9  = calcEMA(ac, 9);  ema9Ref.current?.update({ time: t, value: e9[e9.length - 1] })
          const e21 = calcEMA(ac, 21); ema21Ref.current?.update({ time: t, value: e21[e21.length - 1] })

          if (rsiSeriesRef.current && ac.length > 14) {
            const rv = calcRSI(ac); rsiSeriesRef.current.update({ time: t, value: rv[rv.length - 1] })
          }
          if (ac.length >= 20) {
            const bb = calcBB(ac)
            bbUpperRef.current?.update({ time: t, value: bb.upper[bb.upper.length - 1] })
            bbMiddleRef.current?.update({ time: t, value: bb.middle[bb.middle.length - 1] })
            bbLowerRef.current?.update({ time: t, value: bb.lower[bb.lower.length - 1] })
          }
          if (macdLineRef.current && ac.length >= 35) {
            const { macd: mv, signal: sv, hist: hv } = calcMACD(ac)
            macdLineRef.current.update({ time: t, value: mv[mv.length - 1] })
            macdSigRef.current?.update({ time: t, value: sv[sv.length - 1] })
            macdHistRef.current?.update({ time: t, value: hv[hv.length - 1], color: hv[hv.length - 1] >= 0 ? C.green : C.red })
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
    const bWS = createAutoWS(() => WS_URL, (raw) => {
      try {
        const msg = JSON.parse(raw) as { event?: string; payload?: unknown }
        if (msg.event === 'signal_created') {
          const p = msg.payload as SignalPayload
          if (!p?.entry_price || (p.symbol && p.symbol !== symbol)) return
          const time = ((p.candle_open_time ? p.candle_open_time / 1000 : Math.floor(Date.now() / 1000))) as Time
          const isBuy = p.action === 'BUY'
          const marker: SeriesMarker<Time> = { time, position: isBuy ? 'belowBar' : 'aboveBar', color: isBuy ? C.green : C.red, shape: isBuy ? 'arrowUp' : 'arrowDown', text: isBuy ? '▲ BUY' : '▼ SELL', size: 1.5 }
          markersRef.current = [...markersRef.current.slice(-99), marker]
          candleRef.current?.setMarkers(markersRef.current)
        }
        if (msg.event === 'order_filled') {
          const p = msg.payload as OrderFilledPayload
          if (!p?.price || (p.symbol && p.symbol !== symbol)) return
          const time = ((p.time ? p.time / 1000 : Math.floor(Date.now() / 1000))) as Time
          const isBuy = (p.side ?? '').toUpperCase() === 'BUY'
          const marker: SeriesMarker<Time> = { time, position: isBuy ? 'belowBar' : 'aboveBar', color: isBuy ? C.teal : C.orange, shape: 'circle', text: `FILL ${p.price?.toFixed(2)}`, size: 1 }
          markersRef.current = [...markersRef.current.slice(-99), marker]
          candleRef.current?.setMarkers(markersRef.current)
        }
        if (msg.event === 'position_opened') {
          const p = msg.payload as Position
          if (!p?.symbol || p.symbol !== symbol || !candleRef.current) return
          const series = candleRef.current
          const newLines: typeof priceLineRefs.current = []
          newLines.push(series.createPriceLine({ price: p.entry_price, color: C.blue,    lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'Entry' }))
          if (p.stop_loss)     newLines.push(series.createPriceLine({ price: p.stop_loss,     color: C.slLine,  lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'SL' }))
          if (p.take_profit_1) newLines.push(series.createPriceLine({ price: p.take_profit_1, color: C.tp1Line, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'TP1' }))
          if (p.take_profit_2) newLines.push(series.createPriceLine({ price: p.take_profit_2, color: C.tp2Line, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: 'TP2' }))
          priceLineRefs.current = [...priceLineRefs.current, ...newLines]
        }
      } catch {}
    })
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
      if (containerRef.current && chartRef.current)
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight })
      if (rsiRef.current && rsiChartRef.current)
        rsiChartRef.current.applyOptions({ width: rsiRef.current.clientWidth, height: rsiRef.current.clientHeight })
      if (macdRef.current && macdChartRef.current)
        macdChartRef.current.applyOptions({ width: macdRef.current.clientWidth, height: macdRef.current.clientHeight })
    })
    if (containerRef.current) ro.observe(containerRef.current)
    if (rsiRef.current)       ro.observe(rsiRef.current)
    if (macdRef.current)      ro.observe(macdRef.current)
    return () => ro.disconnect()
  }, [showRsi, showMACD, fullscreen])

  // ── 10. Keyboard shortcuts ────────────────────────────────────────────────
  // FIX: scrollPosition() non esiste in v4 → shift logicalRange manuale
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const onKey = (e: KeyboardEvent) => {
      const ts = chartRef.current?.timeScale()
      if (!ts) return
      switch (e.key) {
        case 'ArrowLeft': {
          const r = ts.getVisibleLogicalRange()
          if (r) ts.setVisibleLogicalRange({ from: r.from - 5, to: r.to - 5 })
          e.preventDefault(); break
        }
        case 'ArrowRight': {
          const r = ts.getVisibleLogicalRange()
          if (r) ts.setVisibleLogicalRange({ from: r.from + 5, to: r.to + 5 })
          e.preventDefault(); break
        }
        case '+': ts.applyOptions({ barSpacing: Math.min((ts.options() as { barSpacing: number }).barSpacing + 2, 50) }); break
        case '-': ts.applyOptions({ barSpacing: Math.max((ts.options() as { barSpacing: number }).barSpacing - 2,  2) }); break
        case 'r': case 'R': ts.fitContent(); break
        case 'f': case 'F': setFullscreen(f => !f); break
      }
    }
    el.setAttribute('tabindex', '0')
    el.addEventListener('keydown', onKey)
    return () => el.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (!fullscreen) return
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') setFullscreen(false) }
    document.addEventListener('keydown', onEsc)
    return () => document.removeEventListener('keydown', onEsc)
  }, [fullscreen])

  const handleSymbol    = useCallback((s: string) => { setSymbol(s);    onSymbolChange?.(s) },    [onSymbolChange])
  const handleTimeframe = useCallback((t: string) => { setTimeframe(t); onTimeframeChange?.(t) }, [onTimeframeChange])

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
        background: C.bg, border: `1px solid ${C.border}`,
        overflow: 'hidden', outline: 'none',
        borderRadius: fullscreen ? 0 : 8,
        ...(fullscreen ? { position: 'fixed', inset: 0, zIndex: 9999 } : {}),
      }}
      // FIX: focus ring vizibil când utilizatorul face click pe chart
      onFocus={e => { e.currentTarget.style.boxShadow = `0 0 0 2px ${C.teal}` }}
      onBlur={e =>  { e.currentTarget.style.boxShadow = 'none' }}
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

        {/* FIX: Indicator chips — culori din CHIP_COLORS map, border explicit */}
        <div style={{ display: 'flex', gap: 4, marginLeft: 4 }}>
          {([
            { label: 'EMA',  active: true,       disabled: true,  onClick: undefined },
            { label: 'BB',   active: showBB,     disabled: false, onClick: () => setShowBB(v => !v) },
            { label: 'VOL',  active: showVolume, disabled: false, onClick: () => setShowVolume(v => !v) },
            { label: 'RSI',  active: showRsi,    disabled: true,  onClick: undefined },
            { label: 'MACD', active: showMACD,   disabled: false, onClick: () => setShowMACD(v => !v) },
          ] as { label: string; active: boolean; disabled: boolean; onClick?: () => void }[]).map(btn => {
            const col = CHIP_COLORS[btn.label] ?? C.textMuted
            return (
              <button key={btn.label} onClick={btn.onClick} disabled={btn.disabled}
                title={btn.disabled ? 'Always on' : btn.active ? `Hide ${btn.label}` : `Show ${btn.label}`}
                style={{
                  padding: '2px 7px', fontSize: 10, fontWeight: 600,
                  border: `1px solid ${btn.active ? col : C.border}`,
                  borderRadius: 3, cursor: btn.disabled ? 'default' : 'pointer',
                  background: btn.active ? `${col}22` : 'transparent',
                  color: btn.active ? col : C.textFaint,
                  transition: 'background 120ms ease, color 120ms ease, border-color 120ms ease',
                  opacity: btn.disabled ? 0.55 : 1,
                }}>
                {btn.label}
              </button>
            )
          })}
        </div>

        {/* EMA legend */}
        <div style={{ display: 'flex', gap: 6, marginLeft: 2 }}>
          {[{c: C.ema9, l: 'EMA9'}, {c: C.ema21, l: 'EMA21'}].map(({c, l}) => (
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
            <span style={{ fontSize: 11, fontWeight: 600, color: change24h >= 0 ? C.green : C.red, background: change24h >= 0 ? 'rgba(109,170,69,0.15)' : 'rgba(221,105,116,0.15)', padding: '2px 6px', borderRadius: 4 }}>
              {change24h >= 0 ? '+' : ''}{change24h.toFixed(2)}%
            </span>
          )}
          {/* FIX: WS dot pulsează când live */}
          <span
            title={wsLive ? 'Live' : 'Connecting…'}
            style={{ width: 7, height: 7, borderRadius: '50%', background: wsLive ? C.green : C.textFaint, display: 'inline-block', transition: 'background 300ms ease', animation: wsLive ? 'ws-pulse 2s ease-in-out infinite' : 'none' }}
          />
          <button onClick={() => setFullscreen(f => !f)} title={fullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen (F)'}
            style={{ background: 'none', border: 'none', color: C.textMuted, cursor: 'pointer', padding: '2px 4px', fontSize: 14, lineHeight: 1 }}>
            {fullscreen ? '⊠' : '⛶'}
          </button>
        </div>
      </div>

      {/* WS pulse keyframe */}
      <style>{`@keyframes ws-pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>

      {/* ── Main chart ─────────────────────────────────────────────────────── */}
      <div style={{ position: 'relative', flex: fullscreen ? 1 : 'none' }}>
        <div ref={containerRef} style={{ width: '100%', height: fullscreen ? '100%' : mainHeight }} />

        {/* OHLCV tooltip */}
        {tooltip && (
          <div style={{ position: 'absolute', top: 8, left: 12, pointerEvents: 'none', background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 6, padding: '6px 10px', fontSize: 11, color: C.textMuted, lineHeight: 1.6, zIndex: 10 }}>
            <div style={{ color: C.textFaint, marginBottom: 2, fontSize: 10 }}>{tooltip.time}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'auto auto', gap: '0 12px' }}>
              <span style={{ color: C.textFaint }}>O</span><span style={{ color: C.text,                                         fontFamily: 'monospace' }}>{tooltip.open.toFixed(2)}</span>
              <span style={{ color: C.textFaint }}>H</span><span style={{ color: C.green,                                        fontFamily: 'monospace' }}>{tooltip.high.toFixed(2)}</span>
              <span style={{ color: C.textFaint }}>L</span><span style={{ color: C.red,                                          fontFamily: 'monospace' }}>{tooltip.low.toFixed(2)}</span>
              {/* FIX: close color dinamic pe culoarea candelei */}
              <span style={{ color: C.textFaint }}>C</span><span style={{ color: tooltip.change >= 0 ? C.green : C.red,          fontFamily: 'monospace', fontWeight: 700 }}>{tooltip.close.toFixed(2)}</span>
              <span style={{ color: C.textFaint }}>V</span><span style={{ color: C.textMuted,                                    fontFamily: 'monospace' }}>{fmtVol(tooltip.volume)}</span>
              <span style={{ color: C.textFaint }}>Δ</span><span style={{ color: tooltip.change >= 0 ? C.green : C.red,          fontFamily: 'monospace' }}>{tooltip.change >= 0 ? '+' : ''}{tooltip.change.toFixed(2)}%</span>
            </div>
          </div>
        )}
      </div>

      {/* ── RSI pane ───────────────────────────────────────────────────────── */}
      {showRsi && (
        <>
          <div style={{ borderTop: `1px solid ${C.border}`, padding: '2px 12px', background: C.surface2, fontSize: 10, color: C.textFaint, display: 'flex', gap: 12 }}>
            <span style={{ color: C.rsi, fontWeight: 600 }}>RSI(14)</span>
            {/* FIX: OB=rosso, OS=verde — convenzione standard */}
            <span style={{ color: C.red }}>OB 70</span>
            <span style={{ color: C.green }}>OS 30</span>
          </div>
          <div ref={rsiRef} style={{ width: '100%', height: rsiHeight }} />
        </>
      )}

      {/* ── MACD pane ──────────────────────────────────────────────────────── */}
      {showMACD && (
        <>
          <div style={{ borderTop: `1px solid ${C.border}`, padding: '2px 12px', background: C.surface2, fontSize: 10, color: C.textFaint, display: 'flex', gap: 12 }}>
            <span style={{ color: C.macd, fontWeight: 600 }}>MACD(12,26,9)</span>
            <span style={{ color: C.macd }}>● MACD</span>
            <span style={{ color: C.signal }}>● Signal</span>
            <span style={{ color: C.green }}>▲ Hist+</span>
            <span style={{ color: C.red }}>▼ Hist−</span>
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
          // FIX: BB legend mostra tutte e 3 le bande quando BB è attivo
          ...(showBB ? [
            { color: C.bbUpper,  label: 'BB Upper' },
            { color: C.bbMiddle, label: 'BB Mid' },
            { color: C.bbLower,  label: 'BB Lower' },
          ] : []),
          ...(showMACD ? [{ color: C.macd, label: 'MACD' }, { color: C.signal, label: 'Signal' }] : []),
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
        <span style={{ marginLeft: 'auto', color: C.textFaint, fontSize: 9 }}>← → scroll · +/− zoom · R reset · F fullscreen</span>
      </div>
    </div>
  )
}

export default TradingChart
