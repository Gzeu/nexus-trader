"use client";
/**
 * JournalTable — paginated trade journal with PnL, R-multiple,
 * strategy tag, and close reason. Sortable by PnL and R-multiple.
 */
import { useState } from "react";
import { JournalEntry } from "@/lib/api";

interface Props {
  entries: JournalEntry[];
  total: number;
  page: number;
  onPageChange: (p: number) => void;
  loading?: boolean;
  pageSize?: number;
}

function fmt(n: number, d = 2) {
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

const REASON_COLORS: Record<string, string> = {
  tp1: "var(--green)",
  tp2: "var(--green)",
  trailing: "var(--blue)",
  signal_reverse: "var(--yellow)",
  time_exit: "var(--text-muted)",
  inactivity: "var(--text-muted)",
  stop_loss: "var(--red)",
  manual: "var(--text-muted)",
  emergency: "var(--red)",
};

export function JournalTable({ entries, total, page, onPageChange, loading, pageSize = 50 }: Props) {
  const [sortKey, setSortKey] = useState<"pnl" | "r" | "date">("date");
  const [sortDir, setSortDir] = useState<1 | -1>(-1);

  const sorted = [...entries].sort((a, b) => {
    const va = sortKey === "pnl" ? a.realized_pnl : sortKey === "r" ? a.r_multiple : new Date(a.closed_at).getTime();
    const vb = sortKey === "pnl" ? b.realized_pnl : sortKey === "r" ? b.r_multiple : new Date(b.closed_at).getTime();
    return sortDir * (va > vb ? 1 : va < vb ? -1 : 0);
  });

  const totalPages = Math.ceil(total / pageSize);

  function toggleSort(key: typeof sortKey) {
    if (sortKey === key) setSortDir((d) => (d === 1 ? -1 : 1));
    else { setSortKey(key); setSortDir(-1); }
  }

  const SortBtn = ({ label, k }: { label: string; k: typeof sortKey }) => (
    <button
      onClick={() => toggleSort(k)}
      style={{
        background: "none", border: "none", cursor: "pointer",
        color: sortKey === k ? "var(--text)" : "var(--text-muted)",
        fontWeight: sortKey === k ? 600 : 400,
        fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.06em",
        display: "flex", alignItems: "center", gap: 3,
      }}
    >
      {label} {sortKey === k ? (sortDir === -1 ? "↓" : "↑") : ""}
    </button>
  );

  if (loading) {
    return (
      <div className="card">
        <div className="skeleton" style={{ height: 14, width: "30%", marginBottom: 12 }} />
        {[...Array(5)].map((_, i) => (
          <div key={i} className="skeleton" style={{ height: 36, marginBottom: 6, borderRadius: 6 }} />
        ))}
      </div>
    );
  }

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <p style={{ fontWeight: 600, fontSize: "0.88rem" }}>Trade Journal</p>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <SortBtn label="PnL" k="pnl" />
          <SortBtn label="R" k="r" />
          <SortBtn label="Date" k="date" />
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>{total} trades</span>
        </div>
      </div>

      {entries.length === 0 ? (
        <div style={{ padding: "48px 16px", textAlign: "center", color: "var(--text-muted)" }}>
          <p style={{ fontSize: "1.4rem", marginBottom: 8 }}>📋</p>
          <p>No trades recorded yet.</p>
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", background: "var(--surface-2)" }}>
                {["Symbol", "Side", "Entry", "Exit", "Qty", "PnL", "R", "Strategy", "Reason", "Closed"].map((h) => (
                  <th key={h} style={{
                    padding: "8px 12px", textAlign: "left",
                    fontSize: "0.68rem", textTransform: "uppercase",
                    letterSpacing: "0.06em", color: "var(--text-muted)",
                    fontWeight: 500, whiteSpace: "nowrap",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((t, i) => {
                const pnlPos = t.realized_pnl >= 0;
                const rPos   = t.r_multiple >= 0;
                return (
                  <tr key={t.trade_id} style={{
                    borderBottom: "1px solid var(--border)",
                    background: i % 2 === 0 ? "transparent" : "var(--surface-2)",
                  }}>
                    <td style={{ padding: "8px 12px", fontFamily: "var(--font-mono)", fontWeight: 600, fontSize: "0.82rem" }}>
                      {t.symbol}
                    </td>
                    <td style={{ padding: "8px 12px" }}>
                      <span className={`badge ${t.side === "LONG" ? "badge-green" : "badge-red"}`}>{t.side}</span>
                    </td>
                    <td style={{ padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: "0.8rem", color: "var(--text-muted)" }}>
                      {fmt(t.entry_price)}
                    </td>
                    <td style={{ padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: "0.8rem", color: "var(--text-muted)" }}>
                      {fmt(t.exit_price)}
                    </td>
                    <td style={{ padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: "0.8rem", color: "var(--text-muted)" }}>
                      {t.quantity}
                    </td>
                    <td style={{ padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: "0.82rem", fontWeight: 600,
                      color: pnlPos ? "var(--green)" : "var(--red)" }}>
                      {pnlPos ? "+" : ""}{fmt(t.realized_pnl)}
                    </td>
                    <td style={{ padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: "0.82rem",
                      color: rPos ? "var(--green)" : "var(--red)" }}>
                      {rPos ? "+" : ""}{fmt(t.r_multiple, 2)}R
                    </td>
                    <td style={{ padding: "8px 12px" }}>
                      <span style={{ fontSize: "0.72rem", padding: "2px 7px", borderRadius: 9999,
                        background: "var(--surface-3)", border: "1px solid var(--border)",
                        color: "var(--text-muted)" }}>
                        {t.strategy}
                      </span>
                    </td>
                    <td style={{ padding: "8px 12px" }}>
                      <span style={{ fontSize: "0.72rem", color: REASON_COLORS[t.close_reason] ?? "var(--text-muted)" }}>
                        {t.close_reason.replace("_", " ")}
                      </span>
                    </td>
                    <td style={{ padding: "8px 12px", fontSize: "0.72rem", color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                      {new Date(t.closed_at).toLocaleString()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ padding: "10px 16px", borderTop: "1px solid var(--border)",
          display: "flex", justifyContent: "flex-end", gap: 6 }}>
          <button className="btn" onClick={() => onPageChange(page - 1)} disabled={page <= 1}
            style={{ opacity: page <= 1 ? 0.4 : 1 }}>← Prev</button>
          <span style={{ padding: "6px 10px", fontSize: "0.8rem", color: "var(--text-muted)" }}>
            {page} / {totalPages}
          </span>
          <button className="btn" onClick={() => onPageChange(page + 1)} disabled={page >= totalPages}
            style={{ opacity: page >= totalPages ? 0.4 : 1 }}>Next →</button>
        </div>
      )}
    </div>
  );
}
