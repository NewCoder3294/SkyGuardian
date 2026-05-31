import * as React from "react";
import { cn } from "@/lib/cn";
interface ClassificationBannerProps { level?: string; caveat?: string; className?: string; }
export function ClassificationBanner({ level = "UNCLASSIFIED", caveat = "FOR DEMO USE", className }: ClassificationBannerProps) {
  return (
    <span title="Demo classification marking — cosmetic." className={cn(
      "inline-flex items-center gap-1.5 border border-border-strong px-1.5 py-0.5 font-mono text-[9px] font-medium uppercase tracking-[0.12em] text-text-muted", className)}>
      <span className="text-text">{level}</span><span className="text-text-dim">//</span><span>{caveat}</span>
    </span>
  );
}
