/** ─── Nexus Trader — Shared TypeScript Domain Types ─────────────────────── */

export type OrderSide   = 'BUY' | 'SELL';
export type OrderType   = 'MARKET' | 'LIMIT' | 'OCO';
export type OrderStatus = 'NEW' | 'PARTIALLY_FILLED' | 'FILLED' | 'CANCELED' | 'REJECTED' | 'EXPIRED';
export type MarketMode  = 'spot' | 'futures';
export type Action      = 'BUY' | 'SELL' | 'HOLD' | 'CLOSE' | 'REVERSE';
export type RiskVeto =
  | 'OK' | 'PAUSED' | 'MAX_DRAWDOWN' | 'MAX_DAILY_LOSS'
  | 'MAX_POSITIONS' | 'ONE_PER_SYMBOL' | 'COOLDOWN'
  | 'CONSECUTIVE_LOSSES' | 'LOW_RR' | 'HIGH_VOLATILITY'
  | 'HIGH_SPREAD' | 'LOW_CONFIDENCE' | 'NOT_RECONCILED';

export interface Position {
  id:             string;
  symbol:         string;
  side:           OrderSide;
  quantity:       number;
  entry_price:    number;
  current_price:  number;
  stop_loss:      number;
  take_profit_1:  number;
  take_profit_2:  number;
  trailing_stop?: number;
  tp1_hit:        boolean;
  tp2_hit:        boolean;
  breakeven_set:  boolean;
  /** Backend returns Optional[float] — may be null before first reconciliation. Use ?? 0 at render sites. */
  unrealized_pnl: number | null;
  realized_pnl:   number;
  total_pnl:      number;
  opened_at:      string;
  is_dry_run:     boolean;
  market_mode:    MarketMode;
  leverage:       number;
  signal_id?:     string;
}

export interface Order {
  id:                 string;
  client_order_id:    string;
  exchange_order_id?: string;
  symbol:             string;
  side:               OrderSide;
  order_type:         OrderType;
  quantity:           number;
  price?:             number;
  stop_price?:        number;
  status:             OrderStatus;
  filled_qty:         number;
  avg_fill_price?:    number;
  commission:         number;
  is_dry_run:         boolean;
  created_at:         string;
  signal_id?:         string;
}

export interface StrategySignal {
  id:               string;
  symbol:           string;
  action:           Action;
  confidence:       number;
  entry_type:       'market' | 'limit';
  entry_price?:     number;
  stop_loss:        number;
  take_profit_1:    number;
  take_profit_2:    number;
  trailing_stop?:   number;
  timeframe:        string;
  reason:           string;
  rr_ratio?:        number;
  candle_open_time?: string;
  created_at:       string;
  metadata:         Record<string, unknown>;
}

export interface AccountInfo {
  total_equity:       number;
  available_balance:  number;
  used_margin:        number;
  unrealized_pnl:     number;
  realized_pnl_today: number;
  balances:           Record<string, number>;
  fetched_at:         string;
}

export interface RiskMetrics {
  total_trades:       number;
  winning_trades:     number;
  losing_trades:      number;
  win_rate:           number;
  profit_factor:      number;
  expectancy:         number;
  sharpe_ratio:       number;
  max_drawdown:       number;
  current_drawdown:   number;
  daily_pnl:          number;
  consecutive_losses: number;
  r_multiples:        number[];
  equity_curve:       number[];
  is_paused:          boolean;
  pause_reason?:      string;
}

export interface HealthStatus {
  status:         string;
  is_reconciled:  boolean;
  dry_run:        boolean;
  testnet:        boolean;
  market_mode:    MarketMode;
  open_positions: number;
  is_paused:      boolean;
  timestamp:      string;
}

export interface WSEvent {
  event:     string;
  payload:   Record<string, unknown>;
  timestamp: string;
}

export interface KpiCard {
  label:  string;
  value:  string | number;
  sub?:   string;
  delta?: number; // positive = green, negative = red
  color?: 'green' | 'red' | 'yellow' | 'blue' | 'muted';
}
