'use client';
import React, { useState } from 'react';
import type { AccountInfo } from '@/types/trading';
import { buildSnapshot, fmtUSD, pnlClass } from '@/lib/balance';

interface Props {
  account: AccountInfo | null;
  loading: boolean;
}

type SortKey = 'asset' | 'total' | 'free' | 'usd_value';

export function AssetsTable({ account, loading }: Props) {
  const [sort, setSort] = useState<SortKey>('usd_value');
  const [asc,  setAsc]  = useState(false);

  const snapshot = account ? buildSnapshot(account) : null;
  const assets   = snapshot?.assets ?? [];
  const sorted   = [...assets].sort((a, b) => {
    const v = sort === 'asset' ? a.asset.localeCompare(b.asset) : b[sort] - a[sort];
    return asc ? -v : v;
  });

  function toggleSort(k: SortKey) {
    if (sort === k) setAsc(x => !x);
    else { setSort(k); setAsc(false); }
  }

  function Th({ k, label }: { k: SortKey; label: string }) {
    const active = sort === k;
    return (
      <th onClick={() => toggleSort(k)} style={{ cursor: 'pointer', userSelect: 'none' }}>
        <span style={{ color: active ? 'var(--blue)' : undefined }}>
          {label} {active ? (asc ? '↑' : '↓') : ''}
        </span>
      </th>
    );
  }

  if (loading) {
    return (
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)' }}>
          <div className="skeleton" style={{ height: 14, width: 140 }} />
        </div>
        {[1,2,3,4].map(i => (
          <div key={i} style={{ display: 'flex', gap: 16, padding: '12px 20px',
            borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
            {[60,70,60,80].map((w, j) => (
              <div key={j} className="skeleton" style={{ height: 12, width: w }} />
            ))}
          </div>
        ))}
      </div>
    );
  }

  const totalUSD = assets.reduce((s, a) => s + a.usd_value, 0);

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8,
        padding: '14px 20px', borderBottom: '1px solid var(--border)' }}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--yellow)" strokeWidth="2">
          <line x1="12" y1="1" x2="12" y2="23"/>
          <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
        </svg>
        <span style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>Asset Balances</span>
        {assets.length > 0 && (
          <span className="badge badge-muted" style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)' }}>
            {fmtUSD(totalUSD)} total
          </span>
        )}
      </div>

      {assets.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '32px 20px', color: 'var(--text-faint)' }}>
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>No balances</div>
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <Th k="asset"     label="Asset" />
                <th>Free</th>
                <th>Locked</th>
                <Th k="total"     label="Total" />
                <Th k="usd_value" label="USD Value" />
                <th>Allocation %</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(a => {
                const pct = totalUSD > 0 ? (a.usd_value / totalUSD) * 100 : 0;
                return (
                  <tr key={a.asset}>
                    <td>
                      <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)' }}>
                        {a.asset}
                      </span>
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{a.free.toFixed(6)}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: a.locked > 0 ? 'var(--yellow)' : 'var(--text-faint)' }}>
                      {a.locked.toFixed(6)}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{a.total.toFixed(6)}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--green)' }}>
                      {fmtUSD(a.usd_value)}
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{ width: 80, height: 5, background: 'var(--surface-3)',
                          borderRadius: 99, overflow: 'hidden' }}>
                          <div style={{ height: '100%', width: `${pct}%`,
                            background: 'var(--blue)', borderRadius: 99,
                            transition: 'width 400ms ease' }} />
                        </div>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)',
                          color: 'var(--text-muted)', minWidth: 36 }}>
                          {pct.toFixed(1)}%
                        </span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
