// ─── Domain Types (mirror backend/models.py) ──────────────────────────────

export type Action = 'BUY' | 'SELL' | 'HOLD' | 'CLOSE' | 'REVERSE'
export type OrderSide = 'BUY' | 'SELL'
export type OrderStatus = 'NEW' | 'PARTIALLY_FILLED' | 'FILLED' | 'CANCELED' | 'REJECTED' | 'EXPIRED'
export type MarketMode = 'spot' | 'futures'
export type ExitReason = 'TP1' | 'TP2' | 'TRAILING_STOP' | 'STOP_LOSS' | 'SIGNAL_REVERSE' | 'TIME_EXIT' | 'INACTIVITY' | 'MANUAL' | 'EMERGENCY'
export type RiskVeto = 'OK' | 'PAUSED' | 'MAX_DRAWDOWN' | 'MAX_DAILY_LOSS' | 'MAX_POSITIONS' | 'ONE_PER_SYMBOL' | 'COOLDOWN' | 'CONSECUTIVE_LOSSES' | 'LOW_RR' | 'HIGH_VOLATILITY' | 'HIGH_SPREAD' | 'LOW_CONFIDENCE' | 'NOT_RECONCILED'

export interface StrategySignal {
  id: string
  symbol: string
  action: Action
  confidence: number
  entry_type: 'market' | 'limit'
  entry_price?: number
  stop_loss: number
  take_profit_1: number
  take_profit_2: number
  trailing_stop?: number
  timeframe: string
  reason: string
  metadata: Record<string, unknown>
  created_at: string
  candle_open_time?: string
  rr_ratio?: number
}

export interface Order {
  id: string
  client_order_id: string
  exchange_order_id?: string
  symbol: string
  side: OrderSide
  order_type: string
  quantity: number
  price?: number
  stop_price?: number
  status: OrderStatus
  filled_qty: number
  avg_fill_price?: number
  commission: number
  is_dry_run: boolean
  created_at: string
  updated_at: string
  signal_id?: string
}

export interface Position {
  id: string
  symbol: string
  side: OrderSide
  quantity: number
  entry_price: number
  current_price: number
  stop_loss: number
  take_profit_1: number
  take_profit_2: number
  trailing_stop?: number
  tp1_hit: boolean
  tp2_hit: boolean
  breakeven_set: boolean
  realized_pnl: number
  unrealized_pnl: number
  total_pnl: number
  commission_paid: number
  opened_at: string
  updated_at: string
  signal_id?: string
  is_dry_run: boolean
  market_mode: MarketMode
  leverage: number
}

export interface Trade {
  id: string
  symbol: string
  side: OrderSide
  entry_price: number
  exit_price: number
  quantity: number
  realized_pnl: number
  commission_paid: number
  exit_reason: ExitReason
  r_multiple?: number
  opened_at: string
  closed_at: string
  duration_seconds?: number
}

export interface AccountInfo {
  total_equity: number
  available_balance: number
  used_margin: number
  unrealized_pnl: number
  realized_pnl_today: number
  balances: Record<string, number>
  fetched_at: string
}

export interface RiskMetrics {
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  profit_factor: number
  expectancy: number
  sharpe_ratio: number
  max_drawdown: number
  current_drawdown: number
  daily_pnl: number
  consecutive_losses: number
  r_multiples: number[]
  equity_curve: number[]
  is_paused: boolean
  pause_reason?: string
}

export interface HealthResponse {
  status: string
  is_reconciled: boolean
  dry_run: boolean
  testnet: boolean
  market_mode: MarketMode
  open_positions: number
  is_paused: boolean
  timestamp: string
}

export interface WSEvent {
  event: string
  payload: Record<string, unknown>
  timestamp: string
}
