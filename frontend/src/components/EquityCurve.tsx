/** ─── EquityCurve — lightweight SVG sparkline ───────────────────────────── */
'use client';
import React from 'react';

interface Props {
  data:   number[];
  width?: number;
  height?: number;
}

export function EquityCurve({ data, width = 300, height = 80 }: Props) {
  if (!data || data.length < 2) {
    return (
      <div style={{ width, height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)' }}>Insufficient data</span>
      </div>
    );
  }

  const min   = Math.min(...data);
  const max   = Math.max(...data);
  const range = max - min || 1;
  const pad   = 4;
  const W     = width  - pad * 2;
  const H     = height - pad * 2;

  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * W;
    const y = pad + H - ((v - min) / range) * H;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(' ');

  const firstPoint = `${pad},${(pad + H - ((data[0] - min) / range) * H).toFixed(2)}`;
  const lastPoint  = `${(pad + W).toFixed(2)},${(pad + H - ((data[data.length-1] - min) / range) * H).toFixed(2)}`;
  const areaPath   = `M ${firstPoint} L ${points.split(' ').slice(1).join(' L ')} L ${pad + W},${pad + H} L ${pad},${pad + H} Z`;

  const isUp = data[data.length - 1] >= data[0];
  const lineColor = isUp ? 'var(--green)' : 'var(--red)';
  const gradId = `eq-grad-${Math.random().toString(36).slice(2, 7)}`;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"  stopColor={lineColor} stopOpacity="0.25" />
          <stop offset="100%" stopColor={lineColor} stopOpacity="0"   />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradId})`} />
      <polyline
        points={points}
        fill="none"
        stroke={lineColor}
        strokeWidth="1.8"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {/* Last point dot */}
      <circle cx={lastPoint.split(',')[0]} cy={lastPoint.split(',')[1]} r="3" fill={lineColor} />
    </svg>
  );
}
