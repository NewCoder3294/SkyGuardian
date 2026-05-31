import * as React from "react";
import { cn } from "@/lib/cn";
import { Reticle } from "./Reticle";
interface StandbyStateProps { title: string; caveat?: string; grid?: boolean; className?: string; children?: React.ReactNode; }
/** Armed empty-state: reticle + scan beam + stencil copy. Reads "standing by". */
export function StandbyState({ title, caveat, grid = true, className, children }: StandbyStateProps) {
  return (
    <div className={cn("relative flex h-full w-full flex-col items-center justify-center overflow-hidden", grid && "hud-grid", className)}>
      <span aria-hidden className="scan-beam" />
      <Reticle size={56} className="mb-4 breathe" />
      <p className="font-mono text-[12px] uppercase tracking-[0.16em] text-text">{title}</p>
      {caveat && <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-text-dim">{caveat}</p>}
      {children && <div className="mt-4">{children}</div>}
    </div>
  );
}
