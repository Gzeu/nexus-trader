/**
 * Typed API client for Nexus Trader backend.
 * All endpoints map 1-to-1 with FastAPI routes.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API  = `${BASE}/api/v1`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  return res.json() as Promise<T>;
}

const get  = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });

// ─── Types (mirror backend models) ──────────────────────────────────────────

export interface HealthStatus {
  status: "ok" | "degraded" | "error";
  reconciled: boolean;
  dry_run: boolean;
  testnet: boolean;
  paused: boolean;
  open_positions: number;
  open_orders: number;
  uptime_seconds: number;
  version: string;
}

export interface AccountInfo {
  total_equity: number;
  total_wallet_balance: number;
  total_unrealized_profit: number;
  total_margin_balance: number;
  available_balance: number;
  total_position_initial_margin: number;
  total_open_order_initial_margin: number;
  max_withdraw_amount: number;
  can_trade: boolean;
  can_withdraw: boolean;
  can_deposit: boolean;
  account_type: string;
  maker_commission: number;
  taker_commission: number;
  assets: AssetBalance[];
  futures_assets: FuturesAsset[];
}

export interface AssetBalance {
  asset: string;
  free: number;
  locked: number;
  total: number;
  usdt_valuation: number;
}

export interface FuturesAsset {
  asset: string;
  wallet_balance: number;
  unrealized_profit: number;
  margin_balance: number;
  maint_margin: number;
  initial_margin: number;
  available_balance: number;
  max_withdraw_amount: number;
  margin_available: boolean;
  update_time: number;
}

export interface BalanceSummary {
  total_usdt_value: number;
  spot_usdt_value: number;
  futures_usdt_value: number;
  unrealized_pnl: number;
  available_margin: number;
  used_margin_pct: number;
  top_assets: AssetBalance[];
  last_updated: string;
}

export interface Position {
  symbol: string;
  side: "LONG" | "SHORT";
  entry_price: number;
  current_price: number;
  quantity: number;
  unrealized_pnl: number;
  realized_pnl: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
  tp1_hit: boolean;
  tp2_hit: boolean;
  opened_at: string;
  market_mode: "SPOT" | "FUTURES";
  leverage: number;
}

export interface Order {
  order_id: string;
  client_order_id: string;
  symbol: string;
  side: "BUY" | "SELL";
  type: string;
  quantity: number;
  price?: number;
  status: string;
  filled_quantity: number;
  created_at: string;
  market_mode: "SPOT" | "FUTURES";
}

export interface StrategySignal {
  signal_id: string;
  symbol: string;
  action: "BUY" | "SELL" | "HOLD" | "CLOSE" | "REVERSE";
  confidence: number;
  entry_type: "market" | "limit";
  entry_price?: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
  trailing_stop?: number;
  timeframe: string;
  reason: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface RiskMetrics {
  equity: number;
  peak_equity: number;
  drawdown_pct: number;
  daily_pnl_pct: number;
  open_positions: number;
  consecutive_losses: number;
  is_paused: boolean;
  win_rate: number;
  profit_factor: number;
  sharpe_ratio: number;
  expectancy: number;
  total_trades: number;
}

export interface JournalEntry {
  trade_id: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number;
  quantity: number;
  realized_pnl: number;
  r_multiple: number;
  opened_at: string;
  closed_at: string;
  close_reason: string;
  strategy: string;
  timeframe: string;
}

export interface JournalPage {
  entries: JournalEntry[];
  total: number;
  page: number;
  page_size: number;
}

export interface PlaceOrderRequest {
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
  order_type: "MARKET" | "LIMIT";
  price?: number;
  stop_loss?: number;
  take_profit_1?: number;
  take_profit_2?: number;
  market_mode: "SPOT" | "FUTURES";
  leverage?: number;
}

// ─── Endpoints ───────────────────────────────────────────────────────────────

export const api = {
  health:        () => get<HealthStatus>("/health"),
  account:       () => get<AccountInfo>("/account"),
  balance:       () => get<BalanceSummary>("/balance"),
  positions:     () => get<Position[]>("/positions"),
  orders:        () => get<Order[]>("/orders"),
  signals:       () => get<StrategySignal[]>("/signals"),
  metrics:       () => get<RiskMetrics>("/metrics"),
  journal:       (page = 1, pageSize = 50) =>
                   get<JournalPage>(`/journal?page=${page}&page_size=${pageSize}`),

  placeOrder:    (body: PlaceOrderRequest) => post<Order>("/place_order", body),
  emergencyStop: () => post<{ ok: boolean }>("/emergency_stop"),
  resumeTrading: () => post<{ ok: boolean }>("/resume_trading"),
  cancelAll:     (symbol?: string) =>
                   post<{ cancelled: number }>("/cancel_all", symbol ? { symbol } : undefined),
  closeAll:      () => post<{ closed: number }>("/close_all"),
  reconcile:     () => post<{ ok: boolean }>("/reconcile"),
};
