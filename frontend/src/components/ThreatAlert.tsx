"use client";

import { useMemo } from "react";
import type { DetectionLayer } from "@/lib/useWorldClient";
import { isThreat } from "@/lib/threats";

interface Props {
  detections: Record<string, DetectionLayer>;
}

/**
 * Bottom-right floating alert that fires whenever YOLO sees a weapon-class
 * object in the current frame. Visible on every tab. Auto-clears the moment
 * a clean frame arrives — no manual dismiss needed.
 *
 * Visual: white card with a thick red border + red header bar, monospaced
 * threat list. Pulse on the dot. Pure B&W elsewhere; red is reserved for
 * exactly this signal.
 */
export function ThreatAlert({ detections }: Props) {
  const active = useMemo(() => {
    // Dedupe threats by label; we keep the first sighting in this frame.
    const labels = new Map<string, string>();
    const now = Date.now() / 1000;
    for (const layer of Object.values(detections)) {
      // Treat anything older than 2 s as cleared.
      if (now - layer.t > 2) continue;
      for (const b of layer.boxes) {
        if (!isThreat(b.label)) continue;
        const key = b.label.toLowerCase();
        if (!labels.has(key)) labels.set(key, b.label);
      }
    }
    return [...labels.values()].sort();
  }, [detections]);

  if (active.length === 0) return null;

  return (
    <div
      role="alert"
      className="tac-corners pointer-events-none fixed bottom-5 right-5 z-50 w-80 overflow-hidden border border-fail/70 bg-surface/95 shadow-[0_0_0_1px_oklch(0.60_0.205_27_/_0.45),0_10px_30px_oklch(0.10_0.01_140_/_0.6)] backdrop-blur-md"
    >
      <div className="flex items-center gap-2 bg-fail/15 px-4 py-2 text-fail">
        <span className="relative inline-flex h-2.5 w-2.5">
          <span className="absolute inset-0 animate-ping rounded-full bg-fail opacity-60" />
          <span className="relative inline-block h-2.5 w-2.5 rounded-full bg-fail" />
        </span>
        <span className="font-sans text-[11px] font-bold uppercase tracking-[0.35em]">
          Threat detected
        </span>
      </div>
      <ul className="divide-y divide-border">
        {active.map((label) => (
          <li
            key={label}
            className="px-4 py-2.5"
          >
            <span className="font-sans text-sm font-semibold uppercase tracking-wider text-text">
              {label}
            </span>
          </li>
        ))}
      </ul>
      <div className="border-t border-border bg-surface-elevated px-4 py-1.5 font-mono text-[9px] uppercase tracking-[0.3em] text-text-dim">
        Auto-clears on clean frame
      </div>
    </div>
  );
}
