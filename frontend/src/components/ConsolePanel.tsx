"use client";

import { useEffect, useRef } from "react";
import type { DetectionEvent } from "@/lib/useWorldClient";
import { isThreat } from "@/lib/threats";
import { cn } from "@/lib/cn";
import { SectionHeader, StandbyState, StatusTag } from "@/components/tactical";

/**
 * Append-only console of detection events from the perception pipeline.
 * Newest at the top. Each frame block lists every box's label, confidence,
 * and normalised image-plane centre — what the brain is currently labelling
 * in the live feed.
 */
export function ConsolePanel({
  log,
  onClear,
}: {
  log: DetectionEvent[];
  /** Optional operator hook to wipe the rolling log. When omitted, no
   *  clear button is rendered — useful for read-only / playback views. */
  onClear?: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Pin scroll to top whenever a new event lands (most recent first).
  useEffect(() => {
    containerRef.current?.scrollTo({ top: 0 });
  }, [log.length]);

  // Flash a row exactly once, the first time its key is rendered. We remember
  // every key we've already drawn; a key absent from the set is "new" and gets
  // `.alert-blink` (a one-shot CSS animation — no timers, no global state).
  const seenRef = useRef<Set<string>>(new Set());

  return (
    <aside className="flex h-full min-h-0 flex-col border-l border-border bg-surface/60">
      <SectionHeader
        index="01"
        label="Detection Log"
        as="h2"
        className="border-b border-border bg-surface"
        aside={
          <div className="flex items-center gap-2">
            {log.length === 0 ? (
              <StatusTag state="idle" label="Standby" />
            ) : (
              <span className="border border-border-strong bg-surface-elevated px-2 py-0.5 font-mono text-[10px] tabular-nums text-text-muted">
                {log.length.toString().padStart(2, "0")}
              </span>
            )}
            {onClear && log.length > 0 && (
              <button
                type="button"
                onClick={onClear}
                aria-label="Clear detection log"
                className="border border-border-strong bg-surface-elevated px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.3em] text-text-muted transition hover:border-accent/60 hover:text-accent"
              >
                Clear
              </button>
            )}
          </div>
        }
      />
      {log.length === 0 ? (
        <div className="flex-1" style={{ minHeight: "12rem" }}>
          <StandbyState title="Awaiting detections" caveat="0 events" grid={false} />
        </div>
      ) : (
        <div ref={containerRef} className="flex-1 overflow-auto">
          {log.map((ev, i) => {
            const key = `${ev.t}-${i}`;
            const isNew = !seenRef.current.has(key);
            seenRef.current.add(key);
            const threat = ev.boxes.some((b) => isThreat(b.label));
            return (
              <article
                key={key}
                className={cn(
                  "border-b border-border px-4 py-2.5 transition-colors hover:bg-surface-elevated/60",
                  isNew && "alert-blink",
                )}
              >
                <div className="mb-1 flex items-baseline justify-between font-mono text-[10px] uppercase tracking-[0.25em]">
                  <span className="tabular-nums text-text-dim">{fmtTime(ev.t)}</span>
                  <span
                    className={cn(
                      "border px-1.5 py-0.5",
                      threat
                        ? "border-fail text-fail"
                        : "border-border-strong bg-surface-elevated text-text-muted",
                    )}
                  >
                    {ev.boxes.length} det
                  </span>
                </div>
                <ul className="space-y-0.5">
                  {ev.boxes.map((b, j) => {
                    const boxThreat = isThreat(b.label);
                    return (
                      <li
                        key={j}
                        className={cn(
                          "font-mono text-[11px]",
                          boxThreat ? "text-fail" : "text-text-muted",
                        )}
                      >
                        <span className="truncate capitalize tracking-wide">
                          {b.label}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </article>
            );
          })}
        </div>
      )}
    </aside>
  );
}

function fmtTime(unixSeconds: number): string {
  const d = new Date(unixSeconds * 1000);
  const hh = d.getHours().toString().padStart(2, "0");
  const mm = d.getMinutes().toString().padStart(2, "0");
  const ss = d.getSeconds().toString().padStart(2, "0");
  const ms = d.getMilliseconds().toString().padStart(3, "0");
  return `${hh}:${mm}:${ss}.${ms.slice(0, 1)}`;
}
