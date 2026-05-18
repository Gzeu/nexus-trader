"use client";
import { Section, Field, NumberInput, PercentSlider, InfoBox, DangerBox } from "../ui";
import type { SettingsData } from "@/types/settings";
interface Props { settings: SettingsData; overrides: Partial<SettingsData>; onChange: (k: keyof SettingsData, v: unknown) => void; isSensitive: (k: string) => boolean }

export function RiskSection({ settings, overrides, onChange }: Props) {
  const ov = (k: keyof SettingsData) => k in overrides;
  return (
    <div className="space-y-4">
      <Section title="Position Sizing" description="Controls how much capital is risked per trade">
        <Field label="Risk per Trade" hint="Fraction of current equity risked on each trade (1% = 0.01)." overridden={ov("risk_per_trade")}>
          <PercentSlider value={settings.risk_per_trade} onChange={v => onChange("risk_per_trade", v)} min={0.001} max={0.05} step={0.001} />
        </Field>
        <Field label="Max Open Positions" hint="Hard cap on simultaneous open trades across all symbols." overridden={ov("max_positions")}>
          <NumberInput value={settings.max_positions} min={1} max={20} onChange={v => onChange("max_positions", v)} suffix="positions" />
        </Field>
        <Field label="Min Risk:Reward" hint="Signals with R:R below this threshold are rejected." overridden={ov("min_rr")}>
          <NumberInput value={settings.min_rr} min={1.0} max={10.0} step={0.1} onChange={v => onChange("min_rr", v)} suffix="R" />
        </Field>
      </Section>

      <Section title="Loss Protection" description="Auto-pause and emergency stop thresholds">
        <Field label="Max Daily Loss" hint="Engine pauses for the day when daily loss reaches this level." overridden={ov("max_daily_loss")}>
          <PercentSlider value={settings.max_daily_loss} onChange={v => onChange("max_daily_loss", v)} min={0.005} max={0.10} step={0.001} />
        </Field>
        <Field label="Max Weekly Loss" hint="Engine pauses until next week when weekly loss reaches this." overridden={ov("max_weekly_loss")}>
          <PercentSlider value={settings.max_weekly_loss} onChange={v => onChange("max_weekly_loss", v)} min={0.01} max={0.20} step={0.001} />
        </Field>
        <Field label="Max Drawdown (Emergency Stop)" hint="Full system halt when drawdown from peak reaches this." overridden={ov("max_drawdown")}>
          <PercentSlider value={settings.max_drawdown} onChange={v => onChange("max_drawdown", v)} min={0.03} max={0.40} step={0.005} />
        </Field>
      </Section>

      <Section title="Signal Filters">
        <Field label="Min Signal Confidence" hint="Signals below this confidence are rejected by the risk gate." overridden={ov("min_confidence")}>
          <PercentSlider value={settings.min_confidence} onChange={v => onChange("min_confidence", v)} min={0} max={1} step={0.01} />
        </Field>
        <Field label="Min CompositeStrategy Consensus" overridden={ov("min_consensus")}>
          <PercentSlider value={settings.min_consensus} onChange={v => onChange("min_consensus", v)} min={0} max={1} step={0.01} />
        </Field>
      </Section>

      <Section title="Cooldown & Streak Protection">
        <Field label="Cooldown after SL (minutes)" overridden={ov("cooldown_minutes")}>
          <NumberInput value={settings.cooldown_minutes} min={0} max={240} onChange={v => onChange("cooldown_minutes", v)} suffix="min" />
        </Field>
        <Field label="Max Consecutive Losses" overridden={ov("max_consecutive_losses")}>
          <NumberInput value={settings.max_consecutive_losses} min={1} max={20} onChange={v => onChange("max_consecutive_losses", v)} suffix="trades" />
        </Field>
      </Section>

      <DangerBox>
        max_daily_loss must be less than max_drawdown. max_weekly_loss must be less than max_drawdown.
        These constraints are validated at startup.
      </DangerBox>
    </div>
  );
}
