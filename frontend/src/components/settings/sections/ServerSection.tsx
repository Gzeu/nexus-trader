"use client";
import { Section, Field, TextInput, NumberInput, TagInput, InfoBox, DangerBox } from "../ui";
import type { SettingsData } from "@/types/settings";
interface Props { settings: SettingsData; overrides: Partial<SettingsData>; onChange: (k: keyof SettingsData, v: unknown) => void; isSensitive: (k: string) => boolean }

export function ServerSection({ settings, overrides, onChange }: Props) {
  const ov = (k: keyof SettingsData) => k in overrides;
  return (
    <div className="space-y-4">
      <Section title="FastAPI Server">
        <Field label="Host" hint="0.0.0.0 binds to all interfaces. Use 127.0.0.1 for local-only." overridden={ov("api_host")}>
          <TextInput value={settings.api_host} onChange={e => onChange("api_host", e.target.value)} />
        </Field>
        <Field label="Port" overridden={ov("api_port")}>
          <NumberInput value={settings.api_port} min={1024} max={65535} onChange={v => onChange("api_port", v)} />
        </Field>
        <Field label="API Secret Key" hint="Cannot be changed via UI. Edit in .env file." overridden={ov("api_secret_key")}>
          <TextInput value={settings.api_secret_key} masked readOnly className="cursor-not-allowed opacity-60" />
        </Field>
      </Section>

      <Section title="CORS Origins">
        <TagInput value={settings.cors_origins} onChange={v => onChange("cors_origins", v)} placeholder="http://localhost:3000" />
      </Section>

      <Section title="Redis (Optional)" description="Idempotency key storage to prevent duplicate orders">
        <Field label="Redis URL" hint="Leave empty to use in-memory store (single-process only)." overridden={ov("redis_url")}>
          <TextInput value={settings.redis_url ?? ""} placeholder="redis://localhost:6379/0" onChange={e => onChange("redis_url", e.target.value || null)} />
        </Field>
      </Section>

      <DangerBox>
        After changing host/port, update NEXT_PUBLIC_API_URL in frontend .env.local and restart both services.
      </DangerBox>
    </div>
  );
}
