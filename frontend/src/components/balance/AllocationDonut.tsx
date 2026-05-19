'use client';
import React, { useMemo } from 'react';
import type { AllocationSlice } from '@/types/balance';
import { fmtUSD } from '@/lib/balance';

interface Props {
  slices:       AllocationSlice[];
  totalEquity:  number;
  size?:        number;
}

/** Pure SVG donut — no external deps */
export function AllocationDonut({ slices, totalEquity, size = 160 }: Props) {
  const R   = size / 2;
  const r   = R * 0.62;   // inner radius
  const cx  = R;
  const cy  = R;
  const gap = 0.012;      // radians gap between slices

  const paths = useMemo(() => {
    let angle = -Math.PI / 2;
    return slices.map((s) => {
      const sweep = (s.pct / 100) * 2 * Math.PI - gap;
      const x1 = cx + R * Math.cos(angle);
      const y1 = cy + R * Math.sin(angle);
      const x2 = cx + R * Math.cos(angle + sweep);
      const y2 = cy + R * Math.sin(angle + sweep);
      const x3 = cx + r * Math.cos(angle + sweep);
      const y3 = cy + r * Math.sin(angle + sweep);
      const x4 = cx + r * Math.cos(angle);
      const y4 = cy + r * Math.sin(angle);
      const large = sweep > Math.PI ? 1 : 0;
      const d = [
        `M ${x1.toFixed(3)} ${y1.toFixed(3)}`,
        `A ${R} ${R} 0 ${large} 1 ${x2.toFixed(3)} ${y2.toFixed(3)}`,
        `L ${x3.toFixed(3)} ${y3.toFixed(3)}`,
        `A ${r} ${r} 0 ${large} 0 ${x4.toFixed(3)} ${y4.toFixed(3)}`,
        'Z',
      ].join(' ');
      angle += sweep + gap;
      return { d, color: s.color, label: s.asset, pct: s.pct };
    });
  }, [slices, R, r, cx, cy, gap]);

  if (slices.length === 0) {
    return (
      <div style={{ width: size, height: size, display: 'flex', alignItems: 'center', justifyContent: 'center',
        borderRadius: '50%', background: 'var(--surface-2)', flexShrink: 0 }}>
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)' }}>No data</span>
      </div>
    );
  }

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flexShrink: 0, overflow: 'visible' }}>
      {paths.map((p, i) => (
        <path key={i} d={p.d} fill={p.color} opacity="0.9">
          <title>{p.label} — {p.pct.toFixed(1)}%</title>
        </path>
      ))}
      {/* Center label */}
      <text x={cx} y={cy - 8} textAnchor="middle" fill="var(--text)"
        fontSize="13" fontWeight="700" fontFamily="var(--font-mono)">
        {fmtUSD(totalEquity, 0)}
      </text>
      <text x={cx} y={cy + 10} textAnchor="middle" fill="var(--text-muted)" fontSize="10">
        Total Equity
      </text>
    </svg>
  );
}
