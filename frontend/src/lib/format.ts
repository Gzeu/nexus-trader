/**
 * format.ts — number and date formatters for trading UI
 */

const USD  = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })
const PCT  = new Intl.NumberFormat('en-US', { style: 'percent',  minimumFractionDigits: 2, maximumFractionDigits: 2 })
const QTY  = new Intl.NumberFormat('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 8 })
const PRICE= new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 8 })

export const fmt = {
  usd:   (v: number)  => USD.format(v),
  pct:   (v: number)  => PCT.format(v),
  qty:   (v: number)  => QTY.format(v),
  price: (v: number)  => PRICE.format(v),
  pnl:   (v: number)  => (v >= 0 ? '+' : '') + USD.format(v),
  pnlPct:(v: number)  => (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%',
  r:     (v: number)  => (v >= 0 ? '+' : '') + v.toFixed(2) + 'R',
  compact:(v: number) => {
    if (Math.abs(v) >= 1_000_000) return (v / 1_000_000).toFixed(2) + 'M'
    if (Math.abs(v) >= 1_000)    return (v / 1_000).toFixed(2) + 'K'
    return v.toFixed(2)
  },
  date: (iso: string) => {
    const d = new Date(iso)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  },
  duration: (seconds: number) => {
    if (seconds < 60)   return `${Math.floor(seconds)}s`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
    if (seconds < 86400)return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
    return `${Math.floor(seconds / 86400)}d`
  },
  confidence: (v: number) => (v * 100).toFixed(0) + '%',
}
