import * as React from "react";
import { cn } from "@/lib/cn";

interface SectionHeaderProps {
  index?: string; label: string; aside?: React.ReactNode;
  as?: "h1" | "h2" | "h3" | "h4"; className?: string;
}
/** Indexed mil-panel header: `01 // LABEL ───────── aside`. */
export function SectionHeader({ index, label, aside, as: Heading = "h2", className }: SectionHeaderProps) {
  return (
    <div className={cn("flex items-center gap-2 px-3 py-2", className)}>
      {index && <span className="font-mono text-[10px] tabular-nums text-text-dim">{index}</span>}
      {index && <span className="font-mono text-[10px] text-text-dim">//</span>}
      <Heading className="font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-text">{label}</Heading>
      <span aria-hidden className="h-px flex-1 bg-border" />
      {aside && <span className="shrink-0">{aside}</span>}
    </div>
  );
}
