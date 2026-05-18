"use client";
import { Section, Field, NumberInput, PercentSlider, InfoBox } from "../ui";
import type { SettingsData } from "@/types/settings";
interface Props { settings: SettingsData; overrides: Partial<SettingsData>; onChange: (k: keyof SettingsData, v: unknown) => void; isSensitive: (k: string) => boolean }

export function VolatilitySection({ settings, overrides, onChange }: Props) {
  const ov = (k: keyof SettingsData) => k in overrides;
  return (
    <div className="space-y-4">
      <Section title="ATR Configuration" description="Average True Range settings for dynamic SL/TP placement">
        <Field label="ATR Period" hint="Number of candles used to calculate ATR. 14 is standard." overridden={ov("atr_period")}>
          <NumberInput value={settings.atr_period} min={5} max={50} onChange={v => onChange("atr_period", v)} suffix="periods" />
        </Field>
        <Field label="ATR Multiplier — Stop Loss" hint="SL is placed at entry ± (ATR × multiplier)." overridden={ov("atr_multiplier_sl")}>
          <NumberInput value={settings.atr_multiplier_sl} min={0.5} max={5.0} step={0.1} onChange={v => onChange("atr_multiplier_sl", v)} suffix="× ATR" />
        </Field>
        <Field label="ATR Multiplier — Take Profit" hint="TP2 is placed at entry ± (ATR × multiplier)." overridden={ov("atr_multiplier_tp")}>
          <NumberInput value={settings.atr_multiplier_tp} min={1.0} max={10.0} step={0.1} onChange={v => onChange("atr_multiplier_tp", v)} suffix="× ATR" />
        </Field>
      </Section>

      <Section title="Volatility Gate">
        <Field label="Max ATR % of Price" hint="If ATR/price exceeds this, the signal is rejected." overridden={ov("max_atr_pct")}>
          <PercentSlider value={settings.max_atr_pct} onChange={v => onChange("max_atr_pct", v)} min={0.001} max={0.20} step={0.001} />
        </Field>
      </Section>

      <InfoBox>
        Implied R:R from current ATR multipliers: <strong>{(settings.atr_multiplier_tp / settings.atr_multiplier_sl).toFixed(2)}R</strong>.
        Must exceed min_rr ({settings.min_rr}R) for signals to pass the risk gate.
        {(settings.atr_multiplier_tp / settings.atr_multiplier_sl) < settings.min_rr
          ? " ⚠️ Current ATR multipliers produce R:R below min_rr!"
          : " ✓ OK"}
      </InfoBox>
    </div>
  );
}
