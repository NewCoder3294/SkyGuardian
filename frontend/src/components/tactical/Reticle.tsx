import * as React from "react";
import { cn } from "@/lib/cn";
interface ReticleProps { size?: number; className?: string; }
/** Centered crosshair / origin marker. */
export function Reticle({ size = 40, className }: ReticleProps) {
  return (
    <span aria-hidden style={{ width: size, height: size }} className={cn("pointer-events-none relative inline-block text-border-strong", className)}>
      <span className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-current" />
      <span className="absolute top-1/2 left-0 h-px w-full -translate-y-1/2 bg-current" />
      <span className="absolute left-1/2 top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-current" />
    </span>
  );
}
