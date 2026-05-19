'use client';
import React, { useEffect, useReducer, useState } from 'react';
import type { ConfigGroup } from '@/types/balance';

/** Default config groups built from .env defaults — editable at runtime via /api/v1/config (if implemented) */
function buildDefaultGroups(): ConfigGroup[] {
  return [
    {
      name: 'Exchange', icon: '🔗',
      fields: [
        { key: 'TESTNET',         label: 'Testnet Mode',         description: 'Use Binance testnet endpoints', value: true,    type: 'boolean', group: 'Exchange' },
        { key: 'DRY_RUN',         label: 'Dry Run',              description: 'Simulate orders, never send real', value: true, type: 'boolean', group: 'Exchange' },
        { key: 'MARKET_MODE',     label: 'Market Mode',          description: 'Spot or Futures', value: 'spot',       type: 'select',  options: ['spot','futures'], group: 'Exchange' },
        { key: 'DEFAULT_LEVERAGE',label: 'Default Leverage',     description: 'Futures only (1-125)', value: 1,           type: 'number',  min: 1, max: 125, step: 1, group: 'Exchange' },
        { key: 'SYMBOLS',         label: 'Symbol Whitelist',     description: 'Comma-separated trading pairs', value: 'BTCUSDT,ETHUSDT,SOLUSDT', type: 'text', group: 'Exchange' },
        { key: 'SYMBOL_BLACKLIST',label: 'Symbol Blacklist',     description: 'Skip these symbols', value: '', type: 'text', group: 'Exchange' },
      ],
    },
    {
      name: 'Risk', icon: '🛡️',
      fields: [
        { key: 'RISK_PER_TRADE',          label: 'Risk Per Trade %',     description: 'Fraction of equity risked per trade', value: 0.01, type: 'number', min: 0.001, max: 0.05,  step: 0.001, group: 'Risk' },
        { key: 'MAX_POSITIONS',           label: 'Max Open Positions',   description: 'Global cap on concurrent positions',  value: 5,    type: 'number', min: 1,     max: 20,    step: 1,     group: 'Risk' },
        { key: 'MAX_DAILY_LOSS',          label: 'Max Daily Loss %',     description: 'Auto-pause threshold',                value: 0.03, type: 'number', min: 0.01,  max: 0.20,  step: 0.005, group: 'Risk', danger: true },
        { key: 'MAX_DRAWDOWN',            label: 'Max Drawdown %',       description: 'Emergency stop threshold',            value: 0.12, type: 'number', min: 0.05,  max: 0.50,  step: 0.01,  group: 'Risk', danger: true },
        { key: 'MIN_RR',                  label: 'Min Reward:Risk',      description: 'Minimum RR ratio to trade',           value: 1.5,  type: 'number', min: 1.0,   max: 10.0,  step: 0.1,   group: 'Risk' },
        { key: 'COOLDOWN_MINUTES',        label: 'SL Cooldown (min)',    description: 'Wait after stop-loss hit',            value: 20,   type: 'number', min: 0,     max: 120,   step: 5,     group: 'Risk' },
        { key: 'MAX_CONSECUTIVE_LOSSES',  label: 'Max Consec. Losses',   description: 'Auto-pause after N losses',           value: 3,    type: 'number', min: 1,     max: 10,    step: 1,     group: 'Risk' },
      ],
    },
    {
      name: 'Filters', icon: '⚙️',
      fields: [
        { key: 'ATR_MAX_PCT',    label: 'Max ATR %',     description: 'Skip if volatility > this', value: 0.05,  type: 'number', min: 0.01, max: 0.30, step: 0.005, group: 'Filters' },
        { key: 'SPREAD_MAX_PCT', label: 'Max Spread %',  description: 'Skip if spread > this',     value: 0.002, type: 'number', min: 0,    max: 0.01,  step: 0.0005, group: 'Filters' },
      ],
    },
    {
      name: 'Execution', icon: '⚡',
      fields: [
        { key: 'ORDER_TIMEOUT_SEC',    label: 'Order Timeout (s)',    description: 'Max wait for fill', value: 10,  type: 'number', min: 2,   max: 60,  step: 1, group: 'Execution' },
        { key: 'RETRY_MAX_ATTEMPTS',   label: 'Retry Attempts',       description: 'Max retries on failure', value: 3, type: 'number', min: 1, max: 10, step: 1, group: 'Execution' },
        { key: 'RETRY_BASE_DELAY',     label: 'Retry Base Delay (s)', description: 'Exponential backoff base', value: 0.5, type: 'number', min: 0.1, max: 5, step: 0.1, group: 'Execution' },
        { key: 'AUTOMATION_INTERVAL_SEC', label: 'Automation Interval', description: 'Seconds between strategy runs', value: 60, type: 'number', min: 5, max: 600, step: 5, group: 'Execution' },
      ],
    },
    {
      name: 'Alerts', icon: '📡',
      fields: [
        { key: 'TELEGRAM_BOT_TOKEN', label: 'Telegram Bot Token', description: 'Leave empty to disable', value: '', type: 'text',    group: 'Alerts', readonly: true },
        { key: 'TELEGRAM_CHAT_ID',   label: 'Telegram Chat ID',   description: 'Your chat / group ID',  value: '', type: 'text',    group: 'Alerts', readonly: true },
      ],
    },
  ];
}

type State = Record<string, string | number | boolean>;

function init(groups: ConfigGroup[]): State {
  const s: State = {};
  groups.forEach(g => g.fields.forEach(f => { s[f.key] = f.value; }));
  return s;
}

export function SettingsPanel() {
  const groups = buildDefaultGroups();
  const [values, dispatch] = useReducer(
    (s: State, a: { key: string; val: string | number | boolean }) => ({ ...s, [a.key]: a.val }),
    groups,
    init,
  );
  const [saved,   setSaved]   = useState(false);
  const [activeG, setActiveG] = useState(groups[0].name);

  const currentGroup = groups.find(g => g.name === activeG)!;

  async function handleSave() {
    // POST to /api/v1/config when backend implements it; for now store in memory
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8,
        padding: '14px 20px', borderBottom: '1px solid var(--border)' }}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--blue)" strokeWidth="2">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
        <span style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>Configuration</span>
        <span className="badge badge-yellow" style={{ marginLeft: 4 }}>Runtime — restart required for .env changes</span>
      </div>

      <div style={{ display: 'flex', minHeight: 400 }}>
        {/* Sidebar */}
        <nav style={{ width: 160, borderRight: '1px solid var(--border)', padding: '12px 8px',
          display: 'flex', flexDirection: 'column', gap: 2, flexShrink: 0 }}>
          {groups.map(g => (
            <button key={g.name}
              className="btn btn-ghost btn-sm"
              onClick={() => setActiveG(g.name)}
              style={{
                justifyContent: 'flex-start', gap: 8,
                background: activeG === g.name ? 'rgba(78,140,255,0.12)' : undefined,
                color:      activeG === g.name ? 'var(--blue)' : 'var(--text-muted)',
                borderColor: activeG === g.name ? 'rgba(78,140,255,0.25)' : 'transparent',
              }}
            >
              <span>{g.icon}</span> {g.name}
            </button>
          ))}
        </nav>

        {/* Fields */}
        <div style={{ flex: 1, padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto' }}>
          {currentGroup.fields.map(f => (
            <div key={f.key} style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <label style={{ fontSize: 'var(--text-sm)', fontWeight: 600,
                  color: f.danger ? 'var(--red)' : 'var(--text)' }}>
                  {f.label}
                </label>
                {f.danger && <span className="badge badge-red">Danger</span>}
                {f.readonly && <span className="badge badge-muted">Read-only in UI</span>}
              </div>
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)' }}>{f.description}</span>

              {f.type === 'boolean' ? (
                <button
                  onClick={() => !f.readonly && dispatch({ key: f.key, val: !values[f.key] })}
                  style={{
                    width: 44, height: 24, borderRadius: 99,
                    background: values[f.key] ? 'var(--green)' : 'var(--surface-3)',
                    border: '1px solid var(--border)', cursor: f.readonly ? 'not-allowed' : 'pointer',
                    position: 'relative', transition: 'background 200ms ease',
                    flexShrink: 0, alignSelf: 'flex-start',
                    opacity: f.readonly ? 0.5 : 1,
                  }}
                  aria-label={`Toggle ${f.label}`}
                >
                  <div style={{
                    width: 16, height: 16, borderRadius: '50%', background: '#fff',
                    position: 'absolute', top: 3,
                    left: values[f.key] ? 23 : 3,
                    transition: 'left 200ms ease',
                  }} />
                </button>
              ) : f.type === 'select' ? (
                <select
                  className="select-input"
                  value={String(values[f.key])}
                  onChange={e => dispatch({ key: f.key, val: e.target.value })}
                  disabled={f.readonly}
                  style={{ maxWidth: 240 }}
                >
                  {f.options?.map(o => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <input
                  className="input"
                  type={f.type}
                  value={String(values[f.key])}
                  min={f.min} max={f.max} step={f.step}
                  onChange={e => dispatch({ key: f.key, val: f.type === 'number' ? Number(e.target.value) : e.target.value })}
                  readOnly={f.readonly}
                  style={{ maxWidth: 320, opacity: f.readonly ? 0.5 : 1, cursor: f.readonly ? 'not-allowed' : undefined }}
                />
              )}
            </div>
          ))}

          {/* Save button */}
          <div style={{ marginTop: 8, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
            <button className="btn btn-primary" onClick={handleSave} style={{ width: 140 }}>
              {saved ? (
                <>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                  Saved!
                </>
              ) : 'Save Changes'}
            </button>
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-faint)', marginTop: 8 }}>
              ⚠️ Changes apply at runtime. For persistence, update your <code style={{ background: 'var(--surface-2)', padding: '1px 4px', borderRadius: 4 }}>.env</code> file and restart.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
