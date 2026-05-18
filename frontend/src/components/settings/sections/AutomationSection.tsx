"use client";
import { Section, Field, NumberInput, InfoBox } from "../ui";
import type { SettingsData } from "@/types/settings";
interface Props { settings: SettingsData; overrides: Partial<SettingsData>; onChange: (k: keyof SettingsData, v: unknown) => void; isSensitive: (k: string) => boolean }

export function AutomationSection({ settings, overrides, onChange }: Props) {
  const ov = (k: keyof SettingsData) => k in overrides;
  return (
    <div className="space-y-4">
      <Section title="Scan Loop" description="APScheduler intervals for the automation engine">
        <Field label="Scan Interval" hint="How often the strategy engine evaluates all whitelisted symbols." overridden={ov("scan_interval_seconds")}>
          <NumberInput value={settings.scan_interval_seconds} min={5} max={3600} step={5} onChange={v => onChange("scan_interval_seconds", v)} suffix="sec" />
        </Field>
        <Field label="Reconciliation Interval" hint="How often portfolio state is synced against the exchange." overridden={ov("reconcile_interval_seconds")}>
          <NumberInput value={settings.reconcile_interval_seconds} min={30} max={3600} step={30} onChange={v => onChange("reconcile_interval_seconds", v)} suffix="sec" />
        </Field>
      </Section>

      <Section title="Time-Based Exits">
        <Field label="Max Holding Time" hint="Force-close any position open longer than this." overridden={ov("max_holding_hours")}>
          <NumberInput value={settings.max_holding_hours} min={1} max={720} step={1} onChange={v => onChange("max_holding_hours", v)} suffix="hours" />
        </Field>
        <Field label="Inactivity Exit" hint="Close if no meaningful price progress for this duration." overridden={ov("inactivity_hours")}>
          <NumberInput value={settings.inactivity_hours} min={1} max={168} step={1} onChange={v => onChange("inactivity_hours", v)} suffix="hours" />
        </Field>
      </Section>

      <InfoBox>
        Scan interval should be ≤ candle duration of primary_timeframe ({settings.primary_timeframe}).
        Scanning faster than one candle period wastes CPU without producing new signals.
      </InfoBox>
    </div>
  );
}
