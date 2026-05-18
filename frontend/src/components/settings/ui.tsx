"use client";
import React, { useState } from "react";
import { Eye, EyeOff, Info } from "lucide-react";

interface SectionProps { title: string; description?: string; children: React.ReactNode }
export function Section({ title, description, children }: SectionProps) {
  return (
    <div className="bg-[#1c1b19] border border-[#262523] rounded-xl overflow-hidden">
      <div className="px-5 py-4 border-b border-[#262523]">
        <h2 className="text-[#cdccca] font-semibold text-sm">{title}</h2>
        {description && <p className="text-[#797876] text-xs mt-0.5">{description}</p>}
      </div>
      <div className="p-5 space-y-4">{children}</div>
    </div>
  );
}

interface FieldProps { label: string; hint?: string; children: React.ReactNode; overridden?: boolean }
export function Field({ label, hint, children, overridden }: FieldProps) {
  return (
    <div className="grid grid-cols-[1fr_auto] gap-4 items-start">
      <div>
        <div className="flex items-center gap-1.5 mb-1">
          <label className="text-[#cdccca] text-sm font-medium">{label}</label>
          {overridden && (
            <span className="px-1.5 py-0.5 rounded text-[10px] bg-[#e8af34]/20 text-[#e8af34]">override</span>
          )}
        </div>
        {hint && <p className="text-[#797876] text-xs leading-relaxed">{hint}</p>}
      </div>
      <div className="min-w-[200px]">{children}</div>
    </div>
  );
}

interface TextInputProps extends React.InputHTMLAttributes<HTMLInputElement> { masked?: boolean }
export function TextInput({ masked, className = "", ...props }: TextInputProps) {
  const [show, setShow] = useState(false);
  const isMasked = masked && !show;
  return (
    <div className="relative">
      <input
        type={isMasked ? "password" : "text"}
        {...props}
        className={`w-full bg-[#201f1d] border border-[#393836] rounded-lg px-3 py-2 text-sm text-[#cdccca]
          placeholder-[#5a5957] focus:outline-none focus:border-[#4f98a3] focus:ring-1 focus:ring-[#4f98a3]/30
          transition-colors ${masked ? "pr-9" : ""} ${className}`}
      />
      {masked && (
        <button
          type="button"
          onClick={() => setShow(s => !s)}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#5a5957] hover:text-[#797876]"
        >
          {show ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
        </button>
      )}
    </div>
  );
}

interface NumberInputProps { value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; suffix?: string }
export function NumberInput({ value, onChange, min, max, step = 1, suffix }: NumberInputProps) {
  return (
    <div className="flex items-center gap-1.5">
      <input
        type="number" min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-full bg-[#201f1d] border border-[#393836] rounded-lg px-3 py-2 text-sm text-[#cdccca]
          focus:outline-none focus:border-[#4f98a3] focus:ring-1 focus:ring-[#4f98a3]/30 transition-colors"
      />
      {suffix && <span className="text-[#797876] text-xs shrink-0">{suffix}</span>}
    </div>
  );
}

interface PercentSliderProps { value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number }
export function PercentSlider({ value, onChange, min = 0, max = 1, step = 0.001 }: PercentSliderProps) {
  const pct = (value * 100).toFixed(2);
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs text-[#797876]">
        <span>{(min*100).toFixed(1)}%</span>
        <span className="font-mono text-[#cdccca]">{pct}%</span>
        <span>{(max*100).toFixed(1)}%</span>
      </div>
      <div className="relative h-5 flex items-center">
        <div className="absolute inset-x-0 h-1.5 rounded-full bg-[#393836]" />
        <div
          className="absolute left-0 h-1.5 rounded-full bg-[#4f98a3]"
          style={{ width: `${((value - min) / (max - min)) * 100}%` }}
        />
        <input
          type="range" min={min} max={max} step={step} value={value}
          onChange={e => onChange(Number(e.target.value))}
          className="relative w-full opacity-0 cursor-pointer h-5"
        />
        <div
          className="absolute w-3.5 h-3.5 rounded-full bg-[#4f98a3] border-2 border-[#0e0e0c] pointer-events-none"
          style={{ left: `calc(${((value - min) / (max - min)) * 100}% - 7px)` }}
        />
      </div>
    </div>
  );
}

interface ToggleProps { checked: boolean; onChange: (v: boolean) => void; label?: string; danger?: boolean }
export function Toggle({ checked, onChange, label, danger }: ToggleProps) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none
        ${checked ? (danger ? "bg-[#dd6974]" : "bg-[#4f98a3]") : "bg-[#393836]"}`}
    >
      <span
        className={`inline-block w-3.5 h-3.5 transform rounded-full bg-white shadow transition-transform
          ${checked ? "translate-x-4" : "translate-x-0.5"}`}
      />
      {label && <span className="sr-only">{label}</span>}
    </button>
  );
}

interface SelectProps { value: string; options: { value: string; label: string }[]; onChange: (v: string) => void }
export function Select({ value, options, onChange }: SelectProps) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full bg-[#201f1d] border border-[#393836] rounded-lg px-3 py-2 text-sm text-[#cdccca]
        focus:outline-none focus:border-[#4f98a3] focus:ring-1 focus:ring-[#4f98a3]/30 transition-colors appearance-none"
    >
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

interface TagInputProps { value: string[]; onChange: (v: string[]) => void; placeholder?: string }
export function TagInput({ value, onChange, placeholder }: TagInputProps) {
  const [input, setInput] = useState("");
  const add = () => {
    const t = input.trim().toUpperCase();
    if (t && !value.includes(t)) onChange([...value, t]);
    setInput("");
  };
  const remove = (t: string) => onChange(value.filter(x => x !== t));
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5 min-h-[32px]">
        {value.map(t => (
          <span key={t} className="flex items-center gap-1 px-2 py-0.5 rounded bg-[#4f98a3]/20 text-[#4f98a3] text-xs font-mono">
            {t}
            <button onClick={() => remove(t)} className="text-[#4f98a3]/60 hover:text-[#dd6974] text-xs ml-0.5">×</button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          value={input} placeholder={placeholder ?? "BTCUSDT"}
          onChange={e => setInput(e.target.value.toUpperCase())}
          onKeyDown={e => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } }}
          className="flex-1 bg-[#201f1d] border border-[#393836] rounded-lg px-3 py-1.5 text-xs font-mono text-[#cdccca]
            placeholder-[#5a5957] focus:outline-none focus:border-[#4f98a3] transition-colors"
        />
        <button onClick={add} className="px-3 py-1.5 text-xs bg-[#4f98a3]/20 text-[#4f98a3] rounded-lg hover:bg-[#4f98a3]/30 transition-colors">
          Add
        </button>
      </div>
    </div>
  );
}

export function InfoBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-2.5 p-3 rounded-lg bg-[#4f98a3]/10 border border-[#4f98a3]/20">
      <Info className="w-4 h-4 text-[#4f98a3] shrink-0 mt-0.5" />
      <p className="text-[#797876] text-xs leading-relaxed">{children}</p>
    </div>
  );
}

export function DangerBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-2.5 p-3 rounded-lg bg-[#dd6974]/10 border border-[#dd6974]/20">
      <Info className="w-4 h-4 text-[#dd6974] shrink-0 mt-0.5" />
      <p className="text-[#dd6974] text-xs leading-relaxed">{children}</p>
    </div>
  );
}
