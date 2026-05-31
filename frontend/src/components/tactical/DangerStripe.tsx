import * as React from "react";
import { cn } from "@/lib/cn";
interface DangerStripeProps extends React.HTMLAttributes<HTMLDivElement> { tone?: "mono" | "threat"; children?: React.ReactNode; }
/** Hatched alert bar. tone="threat" uses signal red (threats only); default mono. */
export function DangerStripe({ tone = "mono", className, children, ...rest }: DangerStripeProps) {
  const threat = tone === "threat";
  return (
    <div className={cn("flex items-center gap-2 border-y", threat ? "border-fail" : "border-text", className)} {...rest}>
      <span aria-hidden className={cn("danger-hatch h-full min-h-5 w-6 self-stretch", threat && "opacity-90")} />
      <span className={cn("font-mono text-[11px] uppercase tracking-[0.12em]", threat ? "text-fail" : "text-text")}>{children}</span>
      <span aria-hidden className={cn("danger-hatch ml-auto h-full min-h-5 w-6 self-stretch", threat && "opacity-90")} />
    </div>
  );
}
