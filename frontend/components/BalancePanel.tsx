"use client";
/**
 * BalancePanel — compact USDT balance overview card.
 * Shows spot / futures split, unrealized PnL, available margin,
 * used-margin progress bar, and top 6 assets.
 */
import { BalanceSummary } from "@/lib/api";

interface Props {
  data: BalanceSummary | null;
  loading?: boolean;
}

function fmt(n: number, decimals = 2): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function PnlBadge({ value }: { value: number }) {
  const pos = value >= 0;
  return (
    <span style={{
      color: pos ? "var(--green)" : "var(--red)",
      fontFamily: "var(--font-mono)",
      fontWeight: 600,
      fontSize: "0.82rem",
    }}>
      {pos ? "+" : ""}{fmt(value)} USDT
    </span>
  );
}

export function BalancePanel({ data, loading }: Props) {
  if (loading || !data) {
    return (
      <div className="card" style={{ minHeight: 180 }}>
        <div className="skeleton" style={{ height: 18, width: "40%", marginBottom: 12 }} />
        <div className="skeleton" style={{ height: 32, width: "60%", marginBottom: 8 }} />
        <div className="skeleton" style={{ height: 12, width: "80%", marginBottom: 6 }} />
        <div className="skeleton" style={{ height: 12, width: "70%" }} />
      </div>
    );
  }

  const usedPct = Math.min(data.used_margin_pct, 100);
  const barColor = usedPct > 75 ? "var(--red)" : usedPct > 50 ? "var(--yellow)" : "var(--green)";

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <p style={{ fontSize: "0.72rem", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>
            Total Balance
          </p>
          <p style={{ fontFamily: "var(--font-mono)", fontSize: "1.6rem", fontWeight: 700, lineHeight: 1 }}>
            ${fmt(data.total_usdt_value)}
          </p>
        </div>
        <div style={{ textAlign: "right" }}>
          <p style={{ fontSize: "0.72rem", color: "var(--text-muted)", marginBottom: 4 }}>Unrealized PnL</p>
          <PnlBadge value={data.unrealized_pnl} />
        </div>
      </div>

      {/* Spot / Futures split */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <MiniStat label="Spot" value={`$${fmt(data.spot_usdt_value)}`} />
        <MiniStat label="Futures" value={`$${fmt(data.futures_usdt_value)}`} />
        <MiniStat label="Available" value={`$${fmt(data.available_margin)}`} accent="var(--green)" />
        <MiniStat label="Margin Used" value={`${fmt(data.used_margin_pct, 1)}%`} accent={barColor} />
      </div>

      {/* Margin bar */}
      <div>
        <div style={{
          height: 4,
          borderRadius: 9999,
          background: "var(--border)",
          overflow: "hidden",
        }}>
          <div style={{
            height: "100%",
            width: `${usedPct}%`,
            background: barColor,
            borderRadius: 9999,
            transition: "width 0.6s ease",
          }} />
        </div>
        <p style={{ fontSize: "0.68rem", color: "var(--text-muted)", marginTop: 4 }}>
          {fmt(data.used_margin_pct, 1)}% margin used
        </p>
      </div>

      {/* Top assets */}
      {data.top_assets.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {data.top_assets.map((a) => (
            <span key={a.asset} style={{
              fontSize: "0.72rem",
              padding: "2px 8px",
              borderRadius: 9999,
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              fontFamily: "var(--font-mono)",
              color: "var(--text-muted)",
            }}>
              {a.asset} {fmt(a.total, a.asset === "USDT" ? 2 : 4)}
            </span>
          ))}
        </div>
      )}

      <p style={{ fontSize: "0.65rem", color: "var(--text-faint)", marginTop: -4 }}>
        Updated {new Date(data.last_updated).toLocaleTimeString()}
      </p>
    </div>
  );
}

function MiniStat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div style={{
      background: "var(--surface-2)",
      borderRadius: "var(--radius)",
      padding: "8px 10px",
      border: "1px solid var(--border)",
    }}>
      <p style={{ fontSize: "0.68rem", color: "var(--text-muted)", marginBottom: 2 }}>{label}</p>
      <p style={{
        fontFamily: "var(--font-mono)",
        fontSize: "0.88rem",
        fontWeight: 600,
        color: accent ?? "var(--text)",
      }}>{value}</p>
    </div>
  );
}
