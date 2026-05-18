"use client";
import { Section, Field, TextInput, Toggle, Select, InfoBox, DangerBox } from "../ui";
import type { SettingsData } from "@/types/settings";

interface Props { settings: SettingsData; overrides: Partial<SettingsData>; onChange: (k: keyof SettingsData, v: unknown) => void; isSensitive: (k: string) => boolean }

export function CredentialsSection({ settings, overrides, onChange, isSensitive }: Props) {
  const ov = (k: keyof SettingsData) => k in overrides;
  return (
    <div className="space-y-4">
      <DangerBox>
        API keys are never sent or stored via this UI. Change them only in your <code className="font-mono text-[#dd6974]/80">.env</code> file.
      </DangerBox>

      <Section title="Spot Credentials" description="Used for all Spot market operations">
        <Field label="API Key" hint="Read-only display — cannot be changed via UI" overridden={ov("binance_api_key")}>
          <TextInput value={settings.binance_api_key} masked readOnly className="cursor-not-allowed opacity-60" />
        </Field>
        <Field label="API Secret" hint="Read-only display" overridden={ov("binance_api_secret")}>
          <TextInput value={settings.binance_api_secret} masked readOnly className="cursor-not-allowed opacity-60" />
        </Field>
      </Section>

      <Section title="Futures Credentials" description="Optional — only needed when futures_enabled=true">
        <Field label="Futures API Key" hint="Only required if Futures are enabled on mainnet" overridden={ov("binance_futures_api_key")}>
          <TextInput value={settings.binance_futures_api_key ?? ""} masked readOnly className="cursor-not-allowed opacity-60" />
        </Field>
        <Field label="Futures API Secret" overridden={ov("binance_futures_api_secret")}>
          <TextInput value={settings.binance_futures_api_secret ?? ""} masked readOnly className="cursor-not-allowed opacity-60" />
        </Field>
      </Section>

      <Section title="Environment" description="Controls trading mode and safety switches">
        <Field label="Testnet" hint="Use Binance Testnet instead of live exchange." overridden={ov("testnet")}>
          <Toggle checked={settings.testnet} onChange={v => onChange("testnet", v)} />
        </Field>
        <Field label="Dry Run" hint="Engine generates signals and logs orders but never sends them to the exchange." overridden={ov("dry_run")}>
          <Toggle checked={settings.dry_run} onChange={v => onChange("dry_run", v)} />
        </Field>
        <Field label="Debug Logging" overridden={ov("debug")}>
          <Toggle checked={settings.debug} onChange={v => onChange("debug", v)} />
        </Field>
        <Field label="Environment" overridden={ov("environment")}>
          <Select
            value={settings.environment}
            options={[
              { value: "development", label: "Development" },
              { value: "staging", label: "Staging" },
              { value: "production", label: "Production" },
            ]}
            onChange={v => onChange("environment", v)}
          />
        </Field>
      </Section>

      <InfoBox>
        Set <strong>Testnet=true</strong> and <strong>Dry Run=true</strong> until you have verified the full signal → execution pipeline.
      </InfoBox>
    </div>
  );
}
