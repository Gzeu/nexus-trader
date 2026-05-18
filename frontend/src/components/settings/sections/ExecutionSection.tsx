"use client";
import { Section, Field, NumberInput, PercentSlider, InfoBox } from "../ui";
import type { SettingsData } from "@/types/settings";
interface Props { settings: SettingsData; overrides: Partial<SettingsData>; onChange: (k: keyof SettingsData, v: unknown) => void; isSensitive: (k: string) => boolean }

export function ExecutionSection({ settings, overrides, onChange }: Props) {
  const ov = (k: keyof SettingsData) => k in overrides;
  return (
    <div className="space-y-4">
      <Section title="Order Timeouts & Retry">
        <Field label="Order Timeout" hint="Limit orders not filled within this time are cancelled." overridden={ov("order_timeout_seconds")}>
          <NumberInput value={settings.order_timeout_seconds} min={5} max={300} onChange={v => onChange("order_timeout_seconds", v)} suffix="sec" />
        </Field>
        <Field label="Max Retries" overridden={ov("max_retries")}>
          <NumberInput value={settings.max_retries} min={1} max={10} onChange={v => onChange("max_retries", v)} suffix="retries" />
        </Field>
        <Field label="Retry Base Delay" overridden={ov("retry_base_delay")}>
          <NumberInput value={settings.retry_base_delay} min={0.1} max={30.0} step={0.1} onChange={v => onChange("retry_base_delay", v)} suffix="sec" />
        </Field>
        <Field label="Retry Max Delay" overridden={ov("retry_max_delay")}>
          <NumberInput value={settings.retry_max_delay} min={1.0} max={300.0} step={1} onChange={v => onChange("retry_max_delay", v)} suffix="sec" />
        </Field>
        <Field label="Exchange Info Cache TTL" overridden={ov("exchange_info_ttl_seconds")}>
          <NumberInput value={settings.exchange_info_ttl_seconds} min={60} max={86400} step={60} onChange={v => onChange("exchange_info_ttl_seconds", v)} suffix="sec" />
        </Field>
      </Section>

      <Section title="Partial Close Targets">
        <Field label="TP1 Close %" hint="After TP1 hit, SL moves to breakeven." overridden={ov("partial_close_tp1_pct")}>
          <PercentSlider value={settings.partial_close_tp1_pct} onChange={v => onChange("partial_close_tp1_pct", v)} min={0.10} max={0.90} step={0.05} />
        </Field>
        <Field label="TP2 Close %" hint="Remainder trails with stop after TP2." overridden={ov("partial_close_tp2_pct")}>
          <PercentSlider value={settings.partial_close_tp2_pct} onChange={v => onChange("partial_close_tp2_pct", v)} min={0.10} max={0.90} step={0.05} />
        </Field>
      </Section>
      <InfoBox>
        After TP1 ({(settings.partial_close_tp1_pct*100).toFixed(0)}%) and TP2 ({(settings.partial_close_tp2_pct*100).toFixed(0)}%),
        remaining {((1 - settings.partial_close_tp1_pct) * (1 - settings.partial_close_tp2_pct) * 100).toFixed(0)}% of position trails with stop.
      </InfoBox>
    </div>
  );
}
