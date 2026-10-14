"use client";

import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export interface SelectOption {
  value: string;
  label: string;
}

const NONE = "__none__"; // Base UI items need a string value; "no choice" maps to null for callers

interface LabeledSelectProps {
  id: string;
  label: string;
  value: string | null;
  options: SelectOption[];
  onChange: (value: string | null) => void;
  /** When set, offers an extra "none" choice with this label (value null). */
  noneLabel?: string;
}

export function LabeledSelect({ id, label, value, options, onChange, noneLabel }: LabeledSelectProps) {
  const items = noneLabel ? [{ value: NONE, label: noneLabel }, ...options] : options;
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Select
        items={items}
        value={value ?? (noneLabel ? NONE : null)}
        onValueChange={(next) => onChange(next === NONE || next === null ? null : String(next))}
      >
        <SelectTrigger id={id} className="w-full min-w-44">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
