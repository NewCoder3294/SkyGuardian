"use client";

import { useEffect, useRef } from "react";
import type { DetectionEvent } from "@/lib/useWorldClient";

/**
 * Append-only console of detection events from the perception pipeline.
 * Newest at the top. Each frame block lists every box's label, confidence,
 * and normalised image-plane centre — what the brain is currently labelling
 * in the live feed.
 */
export function ConsolePanel({ log }: { log: DetectionEvent[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Pin scroll to top whenever a new event lands (most recent first).
  useEffect(() => {
    containerRef.current?.scrollTo({ top: 0 });
  }, [log.length]);

  return (
    <aside className="flex h-full min-h-0 flex-col border-l border-border bg-surface/60">
      <header className="flex items-center justify-between border-b border-border bg-surface px-4 py-3">
        <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.3em] text-accent">
          ◢ Detection log
        </span>
        <span className="border border-border-strong bg-surface-elevated px-2 py-0.5 font-mono text-[10px] tabular-nums text-text-muted">
          {log.length.toString().padStart(2, "0")}
        </span>
      </header>
      {log.length === 0 ? (
        <div className="flex flex-1 items-center justify-center px-4 text-center font-mono text-[10px] uppercase tracking-widest text-text-dim">
          waiting for detections…
        </div>
      ) : (
        <div ref={containerRef} className="flex-1 overflow-auto">
          {log.map((ev, i) => (
            <article
              key={`${ev.t}-${i}`}
              className="border-b border-border px-4 py-2.5 transition-colors hover:bg-surface-elevated/60"
            >
              <div className="mb-1 flex items-baseline justify-between font-mono text-[10px] uppercase tracking-[0.25em] text-text-dim">
                <span className="tabular-nums text-text-muted">{fmtTime(ev.t)}</span>
                <span className="border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-accent">
                  {ev.boxes.length} det
                </span>
              </div>
              <ul className="space-y-0.5">
                {ev.boxes.map((b, j) => (
                  <li
                    key={j}
                    className="font-mono text-[11px] text-text"
                  >
                    <span className="truncate uppercase tracking-wide">{b.label}</span>
                  </li>
                ))}
              </ul>
            </article>
          ))}
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
