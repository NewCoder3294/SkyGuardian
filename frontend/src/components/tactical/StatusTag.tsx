import * as React from "react";
import { cn } from "@/lib/cn";

export type TacticalState = "idle" | "live" | "alert" | "threat" | "offline";

interface StatusTagProps { state: TacticalState; label: string; className?: string; }

/** Monochrome status pill — state by fill + pattern + motion. `threat` is the
 * ONLY hue (signal red), reserved for actual threats. */
export function StatusTag({ state, label, className }: StatusTagProps) {
  const base = "inline-flex items-center gap-2 border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.10em]";
  if (state === "threat") {
    return (
      <span className={cn(base, "border-fail text-fail", className)}>
        <span className="h-[7px] w-[7px] rounded-full bg-fail" aria-hidden />
        {label}
      </span>
    );
  }
  if (state === "alert") {
    return (
      <span className={cn(base, "danger-hatch border-text text-invert", className)}>
        <span className="bg-invert px-1 text-text">{label}</span>
      </span>
    );
  }
  if (state === "offline") {
    return (
      <span className={cn(base, "border-dashed border-border-strong text-text-dim opacity-80", className)}>
        <span className="h-[7px] w-[7px] border border-text-dim" aria-hidden />
        {label}
      </span>
    );
  }
  if (state === "idle") {
    return (
      <span className={cn(base, "breathe border-border text-text-muted", className)}>
        <span className="h-[7px] w-[7px] border border-text-muted" aria-hidden />
        {label}
      </span>
    );
  }
  return ( // live
    <span className={cn(base, "border-text text-text", className)}>
      <span className="h-[7px] w-[7px] rounded-full bg-text" aria-hidden />
      {label}
    </span>
  );
}
