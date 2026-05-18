"use client";
import { Section, Field, TextInput, Toggle, InfoBox } from "../ui";
import type { SettingsData } from "@/types/settings";
interface Props { settings: SettingsData; overrides: Partial<SettingsData>; onChange: (k: keyof SettingsData, v: unknown) => void; isSensitive: (k: string) => boolean }

export function TelegramSection({ settings, overrides, onChange }: Props) {
  const ov = (k: keyof SettingsData) => k in overrides;
  return (
    <div className="space-y-4">
      <Section title="Telegram Alerts" description="Real-time notifications for critical trading events">
        <Field label="Enabled" overridden={ov("telegram_enabled")}>
          <Toggle checked={settings.telegram_enabled} onChange={v => onChange("telegram_enabled", v)} />
        </Field>
        <Field label="Bot Token" hint="From @BotFather. Stored in .env only — masked here." overridden={ov("telegram_bot_token")}>
          <TextInput value={settings.telegram_bot_token ?? ""} masked readOnly className="cursor-not-allowed opacity-60" placeholder="Not set" />
        </Field>
        <Field label="Chat ID" hint="Your personal or group chat ID." overridden={ov("telegram_chat_id")}>
          <TextInput value={settings.telegram_chat_id ?? ""} readOnly className="cursor-not-allowed opacity-60" placeholder="Not set" />
        </Field>
      </Section>

      <InfoBox>
        Alerts sent: signal_created, order_filled, tp_hit, sl_hit, risk_pause, emergency_stop, daily_summary.
        Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your .env file to enable.
      </InfoBox>
    </div>
  );
}
