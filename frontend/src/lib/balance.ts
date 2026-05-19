/** ─── Balance helpers ─────────────────────────────────────────────────────── */
import type { AccountInfo } from '@/types/trading';
import type { AllocationSlice, AssetBalance, BalanceSnapshot } from '@/types/balance';

const PALETTE = [
  '#00d97e', '#4e8cff', '#f5c542', '#ff4d6a', '#a78bfa',
  '#38bdf8', '#fb923c', '#34d399', '#f472b6', '#818cf8',
];

export function buildSnapshot(account: AccountInfo): BalanceSnapshot {
  const assets: AssetBalance[] = Object.entries(account.balances)
    .map(([asset, total]) => ({
      asset,
      free:      total,
      locked:    0,
      total,
      usd_value: total, // backend returns USDT-denominated values
    }))
    .filter(a => a.total > 0.0001)
    .sort((a, b) => b.usd_value - a.usd_value);

  return {
    total_equity:       account.total_equity,
    available_balance:  account.available_balance,
    used_margin:        account.used_margin,
    unrealized_pnl:     account.unrealized_pnl,
    realized_pnl_today: account.realized_pnl_today,
    realized_pnl_total: 0,
    assets,
    fetched_at: account.fetched_at,
    mode:       'spot',
  };
}

export function buildAllocation(assets: AssetBalance[]): AllocationSlice[] {
  const total = assets.reduce((s, a) => s + a.usd_value, 0);
  if (total === 0) return [];
  return assets.slice(0, 10).map((a, i) => ({
    asset:  a.asset,
    value:  a.usd_value,
    pct:    (a.usd_value / total) * 100,
    color:  PALETTE[i % PALETTE.length],
  }));
}

export function fmtUSD(n: number, decimals = 2): string {
  return new Intl.NumberFormat('en-US', {
    style:                 'currency',
    currency:              'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

export function fmtPct(n: number, decimals = 2): string {
  return `${n >= 0 ? '+' : ''}${n.toFixed(decimals)}%`;
}

export function pnlClass(n: number): string {
  return n > 0 ? 'var(--green)' : n < 0 ? 'var(--red)' : 'var(--text-muted)';
}
