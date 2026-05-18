"use client";
import React, { useState } from "react";
import { Section, Field, NumberInput, InfoBox } from "../ui";
import { Plus, Trash2 } from "lucide-react";
import type { SettingsData } from "@/types/settings";
interface Props { settings: SettingsData; overrides: Partial<SettingsData>; onChange: (k: keyof SettingsData, v: unknown) => void; isSensitive: (k: string) => boolean }

interface SymbolOverride { leverage: number; max_position_pct: number }

export function SymbolConfigSection({ settings, onChange }: Props) {
  const config = settings.symbol_config as Record<string, SymbolOverride>;
  const [newSymbol, setNewSymbol] = useState("");

  const update = (sym: string, field: keyof SymbolOverride, val: number) => {
    onChange("symbol_config", { ...config, [sym]: { ...config[sym], [field]: val } });
  };
  const remove = (sym: string) => {
    const updated = { ...config };
    delete updated[sym];
    onChange("symbol_config", updated);
  };
  const add = () => {
    const s = newSymbol.trim().toUpperCase();
    if (!s || config[s]) return;
    onChange("symbol_config", { ...config, [s]: { leverage: settings.leverage_default, max_position_pct: 0.10 } });
    setNewSymbol("");
  };

  return (
    <div className="space-y-4">
      <InfoBox>
        Per-symbol overrides take precedence over global defaults.
        Only symbols in the whitelist are active at runtime.
      </InfoBox>

      {Object.keys(config).length === 0 && (
        <div className="text-center py-8 text-[#797876] text-sm">
          No per-symbol overrides. Add a symbol below.
        </div>
      )}

      {Object.entries(config).map(([sym, cfg]) => (
        <Section key={sym} title={sym}>
          <Field label="Leverage" hint={`Default: ${settings.leverage_default}×`}>
            <NumberInput value={(cfg as SymbolOverride).leverage ?? settings.leverage_default} min={1} max={125} onChange={v => update(sym, "leverage", v)} suffix="×" />
          </Field>
          <Field label="Max Position Size" hint="Max fraction of equity (0.10 = 10%).">
            <NumberInput value={(cfg as SymbolOverride).max_position_pct ?? 0.10} min={0.01} max={1.0} step={0.01} onChange={v => update(sym, "max_position_pct", v)} suffix="of equity" />
          </Field>
          <div className="flex justify-end">
            <button onClick={() => remove(sym)} className="flex items-center gap-1 text-xs text-[#dd6974] hover:text-[#dd6974]/80 transition-colors">
              <Trash2 className="w-3.5 h-3.5" /> Remove {sym}
            </button>
          </div>
        </Section>
      ))}

      <div className="flex gap-2">
        <input
          value={newSymbol} placeholder="SOLUSDT"
          onChange={e => setNewSymbol(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === "Enter" && add()}
          className="flex-1 bg-[#201f1d] border border-[#393836] rounded-lg px-3 py-2 text-sm font-mono text-[#cdccca]
            placeholder-[#5a5957] focus:outline-none focus:border-[#4f98a3] transition-colors"
        />
        <button onClick={add} className="flex items-center gap-1.5 px-4 py-2 text-sm bg-[#4f98a3]/20 text-[#4f98a3] rounded-lg hover:bg-[#4f98a3]/30 transition-colors">
          <Plus className="w-4 h-4" /> Add Symbol
        </button>
      </div>
    </div>
  );
}
