export interface SettingsData {
  // Binance
  binance_api_key: string;
  binance_api_secret: string;
  binance_futures_api_key: string | null;
  binance_futures_api_secret: string | null;
  testnet: boolean;
  dry_run: boolean;
  debug: boolean;
  environment: string;

  // Market
  futures_enabled: boolean;
  futures_market_mode: string;
  spot_market_mode: string;
  spot_whitelist: string[];
  futures_whitelist: string[];
  symbol_blacklist: string[];
  leverage_default: number;
  primary_timeframe: string;
  symbol_config: Record<string, Record<string, unknown>>;

  // Risk
  risk_per_trade: number;
  max_positions: number;
  max_daily_loss: number;
  max_weekly_loss: number;
  max_drawdown: number;
  min_rr: number;
  cooldown_minutes: number;
  max_consecutive_losses: number;
  min_confidence: number;
  min_consensus: number;

  // ATR / Volatility
  atr_period: number;
  atr_multiplier_sl: number;
  atr_multiplier_tp: number;
  max_atr_pct: number;

  // Execution
  order_timeout_seconds: number;
  max_retries: number;
  retry_base_delay: number;
  retry_max_delay: number;
  exchange_info_ttl_seconds: number;
  partial_close_tp1_pct: number;
  partial_close_tp2_pct: number;

  // Automation
  scan_interval_seconds: number;
  reconcile_interval_seconds: number;
  max_holding_hours: number;
  inactivity_hours: number;

  // API Server
  api_host: string;
  api_port: number;
  cors_origins: string[];

  // Telegram
  telegram_bot_token: string | null;
  telegram_chat_id: string | null;
  telegram_enabled: boolean;

  // Database / Journal
  database_url: string;
  journal_csv_path: string;
  redis_url: string | null;
}

export interface SettingsResponse {
  settings: SettingsData;
  overrides: Partial<SettingsData>;
  sensitive_keys: string[];
}
