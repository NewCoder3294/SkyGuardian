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
    type Row = { label: string; confidence: number };
    const rows = new Map<string, Row>();
    const now = Date.now() / 1000;
    for (const layer of Object.values(detections)) {
      // Treat anything older than 2 s as cleared.
      if (now - layer.t > 2) continue;
      for (const b of layer.boxes) {
        if (!isThreat(b.label)) continue;
        const key = b.label.toLowerCase();
        const prev = rows.get(key);
        if (!prev || b.confidence > prev.confidence) {
          rows.set(key, { label: b.label, confidence: b.confidence });
        }
      }
    }
    return [...rows.values()].sort((a, b) => b.confidence - a.confidence);
  }, [detections]);

  if (active.length === 0) return null;

  return (
    <div
      role="alert"
      className="pointer-events-none fixed bottom-4 right-4 z-50 w-72 border-2 border-fail bg-white shadow-[0_0_0_2px_rgba(255,255,255,0.95),0_8px_24px_rgba(0,0,0,0.25)]"
    >
      <div className="flex items-center gap-2 bg-fail px-3 py-1.5 text-white">
        <span className="relative inline-flex h-2.5 w-2.5">
          <span className="absolute inset-0 animate-ping rounded-full bg-white opacity-60" />
          <span className="relative inline-block h-2.5 w-2.5 rounded-full bg-white" />
        </span>
        <span className="font-mono text-[11px] font-bold uppercase tracking-[0.35em]">
          Threat detected
        </span>
      </div>
      <ul className="divide-y divide-border">
        {active.map((row) => (
          <li
            key={row.label}
            className="flex items-baseline justify-between gap-3 px-3 py-2"
          >
            <span className="font-mono text-sm font-semibold uppercase tracking-wider text-text">
              {row.label}
            </span>
            <span className="font-mono text-xs tabular-nums text-fail">
              {(row.confidence * 100).toFixed(0)}%
            </span>
          </li>
        ))}
      </ul>
      <div className="border-t border-border bg-surface px-3 py-1 font-mono text-[9px] uppercase tracking-[0.3em] text-text-dim">
        Auto-clears on clean frame
      </div>
    </div>
  );
}
