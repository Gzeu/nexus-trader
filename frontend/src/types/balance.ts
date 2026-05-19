/** ─── Balance & Settings Domain Types ─────────────────────────────────────── */

export interface AssetBalance {
  asset:    string;
  free:     number;
  locked:   number;
  total:    number;
  usd_value: number;  // estimated, from backend
}

export interface BalanceSnapshot {
  total_equity:        number;
  available_balance:   number;
  used_margin:         number;
  unrealized_pnl:      number;
  realized_pnl_today:  number;
  realized_pnl_total:  number;
  assets:              AssetBalance[];
  fetched_at:          string;
  mode:                'spot' | 'futures';
}

export interface AllocationSlice {
  asset:   string;
  value:   number;
  pct:     number;
  color:   string;
}

export interface ConfigField {
  key:         string;
  label:       string;
  description: string;
  value:       string | number | boolean;
  type:        'text' | 'number' | 'boolean' | 'select';
  options?:    string[];
  min?:        number;
  max?:        number;
  step?:       number;
  group:       string;
  readonly?:   boolean;
  danger?:     boolean;
}

export interface ConfigGroup {
  name:   string;
  icon:   string;
  fields: ConfigField[];
}
