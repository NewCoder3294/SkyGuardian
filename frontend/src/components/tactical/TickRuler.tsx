import * as React from "react";
import { cn } from "@/lib/cn";
interface TickRulerProps { edge: "left" | "right" | "top" | "bottom"; className?: string; }
/** Thin measurement tick strip along one edge of a (relative) panel. */
export function TickRuler({ edge, className }: TickRulerProps) {
  const vertical = edge === "left" || edge === "right";
  return (
    <span aria-hidden className={cn(
      "pointer-events-none absolute opacity-60",
      vertical ? "tick-ruler-y top-0 h-full w-1.5" : "tick-ruler-x left-0 h-1.5 w-full",
      edge === "left" && "left-0", edge === "right" && "right-0",
      edge === "top" && "top-0", edge === "bottom" && "bottom-0", className,
    )} />
  );
}
