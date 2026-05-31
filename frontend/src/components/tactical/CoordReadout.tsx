import * as React from "react";
import { cn } from "@/lib/cn";
export function formatLatLng(lat?: number | null, lng?: number | null): string {
  if (lat == null || lng == null || Number.isNaN(lat) || Number.isNaN(lng)) return "—";
  return `${Math.abs(lat).toFixed(4)}°${lat >= 0 ? "N" : "S"}  ${Math.abs(lng).toFixed(4)}°${lng >= 0 ? "E" : "W"}`;
}
interface CoordReadoutProps { lat?: number | null; lng?: number | null; label?: string; className?: string; }
export function CoordReadout({ lat, lng, label = "POS", className }: CoordReadoutProps) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-mono text-[11px] tabular-nums", className)}>
      <span className="text-text-dim">{label}</span>
      <span className="text-text">{formatLatLng(lat, lng)}</span>
    </span>
  );
}
