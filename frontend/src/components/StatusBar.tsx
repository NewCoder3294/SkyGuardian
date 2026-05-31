"use client";

import type { Health } from "@/lib/contracts";
import type { ConnectionState } from "@/lib/useWorldClient";
import {
  dotClass,
  labelClass,
  leaderTier,
  linkTier,
  perceptionTier,
  tierLabel,
  type StatusTier,
} from "@/lib/status";

interface Props {
  connection: ConnectionState;
  health: Health | null;
  entityCount: number;
  detectionCount: number;
}

/**
 * Compact telemetry readout for the header. Every channel is binary: ONLINE
 * (solid ink dot) or OFFLINE (hollow dashed ink ring) — the dot shape carries
 * the state so the eye doesn't have to read. Strict monochrome: a down channel
 * is loss-of-link, not a threat, so it never goes red (red is reserved for the
 * ThreatAlert path). Lives inline next to the clock rather than as its own
 * band; the fault line is surfaced separately by the page so a healthy system
 * stays at two header rows.
 */
export function StatusBar({
  connection,
  health,
  entityCount,
  detectionCount,
}: Props) {
  const linkT = linkTier(connection.kind);
  const leaderT = leaderTier(health?.mavic);
  const percT = perceptionTier(health?.perception);

  return (
    <div className="flex items-center gap-4 font-mono">
      <div className="flex items-center gap-3.5">
        <Channel label="Link" tier={linkT} />
        <Channel label="Leader" tier={leaderT} />
        <Channel label="Perception" tier={percT} />
      </div>
      <span className="h-4 w-px bg-border" aria-hidden />
      <div className="flex items-center gap-3.5">
        <Count label="Trk" value={entityCount} />
        <Count label="Frm" value={detectionCount} />
      </div>
    </div>
  );
}

function Channel({ label, tier }: { label: string; tier: StatusTier }) {
  return (
    <span
      className="flex items-center gap-1.5"
      title={`${label}: ${tierLabel(tier)}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dotClass(tier)}`} aria-hidden />
      <span className={`text-[10px] uppercase tracking-[0.2em] ${labelClass(tier)}`}>
        {label}
      </span>
    </span>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-[10px] uppercase tracking-[0.2em] text-text-dim">
        {label}
      </span>
      <span className="text-[12px] font-semibold tabular-nums text-accent">
        {value.toString().padStart(2, "0")}
      </span>
    </span>
  );
}
