"use client";

import { useMemo } from "react";
import type { DetectionBox } from "@/lib/contracts";
import type { DetectionEvent, DetectionLayer } from "@/lib/useWorldClient";
import { isThreat } from "@/lib/threats";

interface Props {
  detections: Record<string, DetectionLayer>;
  detectionLog?: DetectionEvent[];
}

/**
 * Operator threat board. One row per class the perception system has seen
 * recently — class label, threat flag, total times seen this session, average
 * confidence, time-since-last-sighting. Currently visible classes sort to top.
 * Threats (weapons / explosives) are flagged in red.
 */
export function IntelPanel({ detections, detectionLog }: Props) {
  const board = useMemo(() => buildBoard(detections, detectionLog ?? []), [detections, detectionLog]);
  const activeThreats = board.filter((r) => r.visibleNow && r.isThreat).length;

  return (
    <div className="h-full overflow-auto bg-bg p-5">
      <section className="tac-corners overflow-hidden border border-border bg-surface shadow-card">
        <header className="flex items-baseline justify-between border-b border-border bg-surface-elevated px-5 py-3">
          <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.3em] text-accent">
            ◢ Threat board
          </span>
          <div className="flex items-baseline gap-2">
            {activeThreats > 0 && (
              <span className="border border-fail/40 bg-fail/10 px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.25em] text-fail">
                ▲ {activeThreats} threat{activeThreats > 1 ? "s" : ""} live
              </span>
            )}
            <span className="border border-border-strong bg-surface px-2.5 py-0.5 font-mono text-[10px] tabular-nums text-text-muted">
              {board.length.toString().padStart(2, "0")} classes
            </span>
          </div>
        </header>
        {board.length === 0 ? (
          <div className="px-5 py-10 text-center font-mono text-[10px] uppercase tracking-widest text-text-dim">
            no detections yet — point the leader at something
          </div>
        ) : (
          <table className="w-full border-collapse font-mono text-[12px]">
            <thead>
              <tr className="border-b border-border bg-surface/60 text-text-dim">
                <Th>Visible</Th>
                <Th left>Class</Th>
                <Th right>Seen</Th>
                <Th right>Last</Th>
              </tr>
            </thead>
            <tbody>
              {board.map((row) => (
                <tr
                  key={row.label}
                  className={`border-b border-border transition-colors hover:bg-surface-elevated/60 ${
                    row.isThreat && row.visibleNow ? "bg-fail/5" : ""
                  }`}
                >
                  <td className="px-4 py-2.5">
                    <span
                      aria-hidden
                      className={`inline-block h-2 w-2 rounded-full ${
                        row.visibleNow
                          ? row.isThreat
                            ? "bg-fail"
                            : "bg-ok shadow-glow-cyan"
                          : "bg-text-dim"
                      }`}
                    />
                  </td>
                  <td className="px-4 py-2.5 uppercase tracking-wider">
                    <span className={row.isThreat ? "text-fail" : "text-text"}>
                      {row.isThreat && "▲ "}{row.label}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-text-muted">
                    {row.seenCount}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-text-muted">
                    {fmtAge(row.lastSeenT)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------

interface BoardRow {
  label: string;
  seenCount: number;
  visibleNow: boolean;
  lastSeenT: number;
  isThreat: boolean;
}

function buildBoard(
  detections: Record<string, { boxes: DetectionBox[]; t: number; source: string }>,
  log: DetectionEvent[],
): BoardRow[] {
  const counts = new Map<string, { n: number; lastT: number }>();
  for (const ev of log) {
    // "Seen" means times-seen (sightings), not instance count: count each
    // label once per frame so a crowd of N people in one frame is one sighting,
    // not N. Dedupe the frame's labels before incrementing.
    const labelsInFrame = new Set(ev.boxes.map((b) => b.label.toLowerCase()));
    for (const key of labelsInFrame) {
      const prev = counts.get(key) ?? { n: 0, lastT: 0 };
      counts.set(key, {
        n: prev.n + 1,
        lastT: Math.max(prev.lastT, ev.t),
      });
    }
  }

  const visibleNow = new Set<string>();
  for (const layer of Object.values(detections)) {
    if (Date.now() / 1000 - layer.t > 2) continue;
    for (const b of layer.boxes) visibleNow.add(b.label.toLowerCase());
  }

  return [...counts.entries()]
    .map(([label, c]) => ({
      label: label.toUpperCase(),
      seenCount: c.n,
      visibleNow: visibleNow.has(label),
      lastSeenT: c.lastT,
      isThreat: isThreat(label),
    }))
    .sort((a, b) => {
      // Live threats first, then live non-threats, then non-live by seen count.
      const aRank = (a.visibleNow ? 2 : 0) + (a.isThreat ? 1 : 0);
      const bRank = (b.visibleNow ? 2 : 0) + (b.isThreat ? 1 : 0);
      if (aRank !== bRank) return bRank - aRank;
      return b.seenCount - a.seenCount;
    });
}

function Th({
  children,
  left = false,
  right = false,
}: {
  children: React.ReactNode;
  left?: boolean;
  right?: boolean;
}) {
  return (
    <th
      className={`px-3 py-2 text-[9px] uppercase tracking-[0.25em] font-normal ${
        left ? "text-left" : right ? "text-right" : "text-center"
      }`}
    >
      {children}
    </th>
  );
}

function fmtAge(t: number): string {
  if (!t) return "—";
  const seconds = Date.now() / 1000 - t;
  if (seconds < 1) return "now";
  if (seconds < 60) return `${seconds.toFixed(0)}s ago`;
  return `${Math.floor(seconds / 60)}m ago`;
}
