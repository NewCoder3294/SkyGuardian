"use client";

import { useEffect, useRef, useState } from "react";
import { DangerStripe } from "@/components/tactical";
import type { DetectionLayer } from "@/lib/useWorldClient";
import { isThreat } from "@/lib/threats";

interface Props {
  detections: Record<string, DetectionLayer>;
}

/** How long the alert keeps showing after the last threat sighting before it
 *  auto-clears. Long enough that a single-frame detection still gives the
 *  operator (and the judges) something to see; short enough that a sustained
 *  clean frame stream still clears the banner promptly. */
const HOLD_MS = 5_000;

/**
 * Bottom-right alert that fires whenever YOLO sees a weapon-class object in
 * the current frame. Positioned *inside the video container* (its parent must
 * be `position: relative`) so it sits in the operator's video pane bottom-
 * right rather than the viewport corner — the viewport corner sits behind
 * the right-side ConsolePanel and is easy to miss.
 *
 * Visual: dark card with a thick signal-red border + a hatched red danger
 * stripe header (the kit's `DangerStripe tone="threat"`), monospaced threat
 * list. Pulse on the dot. Pure B&W elsewhere; red is reserved for exactly
 * this signal — an actual detected threat.
 *
 * Persistence: every fresh threat sighting refreshes a 5 s hold window. The
 * alert disappears 5 s after the LAST threat-bearing frame, not immediately
 * on the next clean frame — perception fps is bursty (~3 fps) and the model
 * sometimes drops a detection between two solid ones, which used to make the
 * banner flicker. The hold also gives the operator time to actually read it.
 */
export function ThreatAlert({ detections }: Props) {
  const [active, setActive] = useState<string[]>([]);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    // Pull the current frame's threat labels (dedupe by lowercase key).
    const found = new Set<string>();
    const nowSec = Date.now() / 1000;
    for (const layer of Object.values(detections)) {
      // Backend marks stale layers with t=0; the 2 s window also bounds an
      // intermittently-broadcasting source.
      if (layer.t <= 0 || nowSec - layer.t > 2) continue;
      for (const b of layer.boxes) {
        if (!isThreat(b.label)) continue;
        found.add(b.label.toLowerCase());
      }
    }

    if (found.size === 0) {
      // No threats this frame — leave the existing hold timer running. The
      // alert will drop on its own when HOLD_MS elapses with no refresh.
      return;
    }

    // Threat present: publish the label set and (re)arm the hold timer.
    setActive([...found].sort());
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
    }
    timerRef.current = window.setTimeout(() => {
      setActive([]);
      timerRef.current = null;
    }, HOLD_MS);
  }, [detections]);

  // Clear the pending dismissal if the component unmounts mid-hold so we
  // don't fire setActive on a dead component.
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  if (active.length === 0) return null;

  return (
    <div
      role="alert"
      className="tac-corners pointer-events-none absolute bottom-5 right-5 z-50 w-80 overflow-hidden border border-fail/70 bg-surface/95 shadow-[0_0_0_1px_oklch(0.60_0.205_27_/_0.45),0_10px_30px_oklch(0.10_0.01_140_/_0.6)] backdrop-blur-md"
    >
      <DangerStripe tone="threat" className="bg-fail/15 py-2 pr-2">
        <span className="inline-flex items-center gap-2">
          <span className="relative inline-flex h-2.5 w-2.5">
            <span className="absolute inset-0 animate-ping rounded-full bg-fail opacity-60" />
            <span className="relative inline-block h-2.5 w-2.5 rounded-full bg-fail" />
          </span>
          <span className="font-sans text-[11px] font-bold uppercase tracking-[0.35em]">
            Threat detected
          </span>
        </span>
      </DangerStripe>
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
        Auto-clears 5 s after last sighting
      </div>
    </div>
  );
}
