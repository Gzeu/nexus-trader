"use client";
import { Section, Field, Toggle, Select, NumberInput, TagInput, InfoBox } from "../ui";
import type { SettingsData } from "@/types/settings";
interface Props { settings: SettingsData; overrides: Partial<SettingsData>; onChange: (k: keyof SettingsData, v: unknown) => void; isSensitive: (k: string) => boolean }

const TF_OPTIONS = ["1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d","3d","1w"]
  .map(v => ({ value: v, label: v }));

export function MarketSection({ settings, overrides, onChange }: Props) {
  const ov = (k: keyof SettingsData) => k in overrides;
  return (
    <div className="space-y-4">
      <Section title="Market Mode" description="Enable/disable Futures trading">
        <Field label="Futures Enabled" hint="Enables futures trading. Requires separate API keys on mainnet." overridden={ov("futures_enabled")}>
          <Toggle checked={settings.futures_enabled} onChange={v => onChange("futures_enabled", v)} danger />
        </Field>
        <Field label="Default Leverage" hint="Applied to all futures symbols unless overridden per-symbol." overridden={ov("leverage_default")}>
          <NumberInput value={settings.leverage_default} min={1} max={125} step={1} suffix="×" onChange={v => onChange("leverage_default", v)} />
        </Field>
        <Field label="Primary Timeframe" hint="Timeframe used by the automation engine scan loop." overridden={ov("primary_timeframe")}>
          <Select value={settings.primary_timeframe} options={TF_OPTIONS} onChange={v => onChange("primary_timeframe", v)} />
        </Field>
      </Section>

      <Section title="Spot Whitelist" description="Symbols allowed for Spot trading">
        <TagInput value={settings.spot_whitelist} onChange={v => onChange("spot_whitelist", v)} placeholder="BTCUSDT" />
      </Section>

      <Section title="Futures Whitelist" description="Symbols allowed for Futures trading">
        <TagInput value={settings.futures_whitelist} onChange={v => onChange("futures_whitelist", v)} placeholder="BTCUSDT" />
      </Section>

      <Section title="Blacklist" description="These symbols will never be traded, regardless of whitelist">
        <TagInput value={settings.symbol_blacklist} onChange={v => onChange("symbol_blacklist", v)} placeholder="DOGEUSDT" />
      </Section>

      <InfoBox>
        The effective trading universe is: <strong>whitelist − blacklist</strong>.
        Futures symbols are used when futures_enabled=true, spot symbols otherwise.
      </InfoBox>
    </div>
  );
}
