"use client";
import { Section, Field, TextInput, InfoBox } from "../ui";
import type { SettingsData } from "@/types/settings";
interface Props { settings: SettingsData; overrides: Partial<SettingsData>; onChange: (k: keyof SettingsData, v: unknown) => void; isSensitive: (k: string) => boolean }

export function DatabaseSection({ settings, overrides, onChange }: Props) {
  const ov = (k: keyof SettingsData) => k in overrides;
  return (
    <div className="space-y-4">
      <Section title="Trade Journal">
        <Field label="Database URL" hint="SQLAlchemy async URL. Default: SQLite. Switch to postgresql+asyncpg:// for production." overridden={ov("database_url")}>
          <TextInput value={settings.database_url} onChange={e => onChange("database_url", e.target.value)} className="font-mono text-xs" />
        </Field>
        <Field label="Journal CSV Path" hint="Append-only CSV trade log." overridden={ov("journal_csv_path")}>
          <TextInput value={settings.journal_csv_path} onChange={e => onChange("journal_csv_path", e.target.value)} className="font-mono text-xs" />
        </Field>
      </Section>

      <InfoBox>
        For production: <code className="font-mono text-[#4f98a3]/80">postgresql+asyncpg://user:pass@host/nexus_trader</code>.
        Changing DATABASE_URL requires a migration or a fresh database.
      </InfoBox>
    </div>
  );
}
