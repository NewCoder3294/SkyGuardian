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
    <aside className="flex h-full min-h-0 flex-col border-l border-border bg-surface">
      <header className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.3em] text-text-dim">
          Detection log
        </span>
        <span className="font-mono text-[10px] tabular-nums text-text-muted">
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
              className="border-b border-border px-3 py-2"
            >
              <div className="mb-1 flex items-baseline justify-between font-mono text-[10px] uppercase tracking-[0.25em] text-text-dim">
                <span className="tabular-nums">{fmtTime(ev.t)}</span>
                <span>{ev.boxes.length} det</span>
              </div>
              <ul className="space-y-0.5">
                {ev.boxes.map((b, j) => (
                  <li
                    key={j}
                    className="grid grid-cols-[1fr_auto] items-baseline font-mono text-[11px] text-text"
                  >
                    <span className="truncate uppercase tracking-wide">
                      {b.label}
                    </span>
                    <span className="tabular-nums text-text-muted">
                      {(b.confidence * 100).toFixed(0)}%
                    </span>
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
