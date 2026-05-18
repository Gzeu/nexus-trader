"use client";

import React, { useState, useCallback } from "react";
import { useSettings } from "@/hooks/useSettings";
import { apiFetch } from "@/lib/config";
import { SettingsData } from "@/types/settings";
import {
  ShieldCheck, Zap, BarChart2, Settings2, Server,
  Bell, Database, Save, RotateCcw, AlertTriangle,
  CheckCircle2, ChevronRight, Loader2,
} from "lucide-react";
import { CredentialsSection } from "./sections/CredentialsSection";
import { MarketSection } from "./sections/MarketSection";
import { RiskSection } from "./sections/RiskSection";
import { VolatilitySection } from "./sections/VolatilitySection";
import { ExecutionSection } from "./sections/ExecutionSection";
import { AutomationSection } from "./sections/AutomationSection";
import { ServerSection } from "./sections/ServerSection";
import { TelegramSection } from "./sections/TelegramSection";
import { DatabaseSection } from "./sections/DatabaseSection";
import { SymbolConfigSection } from "./sections/SymbolConfigSection";

const TABS = [
  { id: "credentials", label: "Binance API",     icon: ShieldCheck },
  { id: "market",      label: "Market",           icon: BarChart2   },
  { id: "risk",        label: "Risk Manager",     icon: ShieldCheck },
  { id: "volatility",  label: "Volatility / ATR", icon: Zap         },
  { id: "execution",   label: "Execution",        icon: Settings2   },
  { id: "automation",  label: "Automation",       icon: Zap         },
  { id: "symbols",     label: "Per-Symbol",       icon: BarChart2   },
  { id: "server",      label: "API Server",       icon: Server      },
  { id: "telegram",    label: "Telegram",         icon: Bell        },
  { id: "database",    label: "Database",         icon: Database    },
] as const;

type TabId = typeof TABS[number]["id"];

export function SettingsPage() {
  const { data, isLoading, error, mutate } = useSettings();
  const [activeTab, setActiveTab] = useState<TabId>("credentials");
  const [dirty, setDirty] = useState<Partial<SettingsData>>({});
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ type: "ok"|"err"; msg: string } | null>(null);

  const showToast = (type: "ok"|"err", msg: string) => {
    setToast({ type, msg });
    setTimeout(() => setToast(null), 4000);
  };

  const handleChange = useCallback((key: keyof SettingsData, value: unknown) => {
    setDirty(prev => ({ ...prev, [key]: value }));
  }, []);

  const merged = data ? { ...data.settings, ...dirty } : null;
  const isSensitive = (key: string) => data?.sensitive_keys.includes(key) ?? false;

  const handleSave = async () => {
    if (!Object.keys(dirty).length) return;
    setSaving(true);
    try {
      const payload: Partial<SettingsData> = {};
      for (const [k, v] of Object.entries(dirty)) {
        if (!isSensitive(k)) payload[k as keyof SettingsData] = v as never;
      }
      await apiFetch("/api/v1/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: payload }),
      });
      setDirty({});
      mutate();
      showToast("ok", "Settings saved. Restart backend to apply runtime changes.");
    } catch (e: unknown) {
      showToast("err", e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!confirm("Reset all overrides to .env defaults?")) return;
    setSaving(true);
    try {
      await apiFetch("/api/v1/settings/overrides", { method: "DELETE" });
      setDirty({});
      mutate();
      showToast("ok", "Overrides cleared. Restart backend to apply.");
    } catch {
      showToast("err", "Reset failed");
    } finally {
      setSaving(false);
    }
  };

  const dirtyCount = Object.keys(dirty).length;

  if (isLoading) return (
    <div className="flex items-center justify-center h-screen bg-[#0e0e0c]">
      <Loader2 className="w-8 h-8 text-[#4f98a3] animate-spin" />
    </div>
  );

  if (error || !merged) return (
    <div className="flex items-center justify-center h-screen bg-[#0e0e0c]">
      <div className="text-center space-y-2">
        <AlertTriangle className="w-10 h-10 text-[#dd6974] mx-auto" />
        <p className="text-[#cdccca]">Failed to load settings</p>
        <p className="text-[#797876] text-sm">Is the backend running?</p>
      </div>
    </div>
  );

  const sectionProps = { settings: merged, overrides: data.overrides, onChange: handleChange, isSensitive };

  return (
    <div className="min-h-screen bg-[#0e0e0c] flex flex-col">
      {/* Header */}
      <div className="border-b border-[#262523] bg-[#171614] px-6 py-4 flex items-center justify-between sticky top-0 z-20">
        <div className="flex items-center gap-3">
          <Settings2 className="w-5 h-5 text-[#4f98a3]" />
          <span className="text-[#cdccca] font-semibold text-base">Settings</span>
          {dirtyCount > 0 && (
            <span className="px-2 py-0.5 rounded-full bg-[#4f98a3]/20 text-[#4f98a3] text-xs font-medium">
              {dirtyCount} unsaved
            </span>
          )}
          {data.overrides && Object.keys(data.overrides).length > 0 && (
            <span className="px-2 py-0.5 rounded-full bg-[#e8af34]/20 text-[#e8af34] text-xs">
              {Object.keys(data.overrides).length} overrides active
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleReset}
            disabled={saving}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm text-[#797876] hover:text-[#cdccca] hover:bg-[#1c1b19] transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" /> Reset overrides
          </button>
          <button
            onClick={handleSave}
            disabled={saving || dirtyCount === 0}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-md text-sm font-medium bg-[#4f98a3] hover:bg-[#227f8b] disabled:opacity-40 disabled:cursor-not-allowed text-white transition-colors"
          >
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Save changes
          </button>
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div className={`fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-3 rounded-lg shadow-lg text-sm font-medium
          ${toast.type === "ok" ? "bg-[#3a4435] text-[#6daa45] border border-[#6daa45]/30" : "bg-[#574848] text-[#dd6974] border border-[#dd6974]/30"}`}>
          {toast.type === "ok" ? <CheckCircle2 className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
          {toast.msg}
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <nav className="w-52 shrink-0 border-r border-[#262523] bg-[#171614] py-4 overflow-y-auto">
          {TABS.map(tab => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`w-full flex items-center gap-2.5 px-4 py-2.5 text-sm transition-colors text-left
                  ${active
                    ? "bg-[#1c1b19] text-[#cdccca] border-r-2 border-[#4f98a3]"
                    : "text-[#797876] hover:text-[#cdccca] hover:bg-[#1a1918]"
                  }`}
              >
                <Icon className={`w-4 h-4 shrink-0 ${active ? "text-[#4f98a3]" : ""}`} />
                <span>{tab.label}</span>
                {active && <ChevronRight className="w-3 h-3 ml-auto text-[#4f98a3]" />}
              </button>
            );
          })}
        </nav>

        {/* Content */}
        <main className="flex-1 overflow-y-auto p-6">
          <div className="max-w-3xl mx-auto space-y-6">
            {activeTab === "credentials"  && <CredentialsSection  {...sectionProps} />}
            {activeTab === "market"       && <MarketSection       {...sectionProps} />}
            {activeTab === "risk"         && <RiskSection         {...sectionProps} />}
            {activeTab === "volatility"   && <VolatilitySection   {...sectionProps} />}
            {activeTab === "execution"    && <ExecutionSection    {...sectionProps} />}
            {activeTab === "automation"   && <AutomationSection   {...sectionProps} />}
            {activeTab === "symbols"      && <SymbolConfigSection {...sectionProps} />}
            {activeTab === "server"       && <ServerSection       {...sectionProps} />}
            {activeTab === "telegram"     && <TelegramSection     {...sectionProps} />}
            {activeTab === "database"     && <DatabaseSection     {...sectionProps} />}
          </div>
        </main>
      </div>
    </div>
  );
}
