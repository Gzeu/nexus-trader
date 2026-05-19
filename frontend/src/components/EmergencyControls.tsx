/** ─── EmergencyControls — kill switch panel ─────────────────────────────── */
'use client';
import React, { useState } from 'react';

interface Props {
  isPaused:     boolean;
  onEmergency:  () => Promise<void>;
  onResume:     () => Promise<void>;
  onCancelAll:  () => Promise<void>;
  onCloseAll:   () => Promise<void>;
}

export function EmergencyControls({ isPaused, onEmergency, onResume, onCancelAll, onCloseAll }: Props) {
  const [loading, setLoading] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  async function run(key: string, fn: () => Promise<void>) {
    if (confirm !== key) { setConfirm(key); return; }
    setLoading(key);
    setConfirm(null);
    try { await fn(); }
    finally { setLoading(null); }
  }

  const btn = (key: string, label: string, fn: () => Promise<void>, variant: string, icon: React.ReactNode) => (
    <button
      className={`btn ${variant}`}
      onClick={() => run(key, fn)}
      disabled={loading !== null}
      style={{
        position: 'relative', flex: '1 1 0', minWidth: 0,
        ...(confirm === key ? { outline: '2px solid var(--red)', outlineOffset: 2 } : {}),
      }}
    >
      {loading === key ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          style={{ animation: 'spin 1s linear infinite' }}>
          <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
        </svg>
      ) : icon}
      {confirm === key ? 'Confirm?' : label}
    </button>
  );

  return (
    <div className="card" style={{ padding: '16px 20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--red)" strokeWidth="2">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/>
          <line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
        <span style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>Controls</span>
        {confirm && (
          <span className="badge badge-red" style={{ marginLeft: 'auto' }}>Click again to confirm</span>
        )}
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {isPaused
          ? btn('resume', 'Resume Trading', onResume, 'btn-primary',
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="5 3 19 12 5 21 5 3"/>
              </svg>)
          : btn('emergency', '⚠ Emergency Stop', onEmergency, 'btn-danger',
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="18" height="18" rx="2"/>
              </svg>)}

        {btn('cancelAll', 'Cancel Orders', onCancelAll, 'btn-ghost',
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>)}

        {btn('closeAll', 'Close All Positions', onCloseAll, 'btn-danger',
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>
          </svg>)}
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
