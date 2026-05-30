"use client";

import type { Health } from "@/lib/contracts";
import type { ConnectionState } from "@/lib/useWorldClient";
import {
  dotClass,
  leaderTier,
  linkTier,
  perceptionTier,
  type StatusTier,
} from "@/lib/status";

interface Props {
  connection: ConnectionState;
  lastError: string | null;
  health: Health | null;
  entityCount: number;
  detectionCount: number;
}

/**
 * Read-only telemetry strip. Two visually distinct groups so the eye can land
 * fast: SYSTEM (link health, traffic-light) on the left; COUNTERS (numeric
 * world / detections, neutral) on the right. Bigger value type, smaller
 * label, separator divider between groups.
 */
export function StatusBar({
  connection,
  lastError,
  health,
  entityCount,
  detectionCount,
}: Props) {
  return (
    <div className="border-b border-border bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <SystemChannel label="Link" value={linkLabel(connection)} tier={linkTier(connection.kind)} />
        <SystemChannel label="Leader" value={(health?.mavic ?? "—").toUpperCase()} tier={leaderTier(health?.mavic)} />
        <SystemChannel label="Perception" value={(health?.perception ?? "—").toUpperCase()} tier={perceptionTier(health?.perception)} />

        <span className="h-6 w-px bg-border" aria-hidden />

        <CountChannel label="World" value={entityCount} />
        <CountChannel label="Detections" value={detectionCount} />
      </div>
      {lastError && (
        <div className="mt-2 inline-block rounded-sm border border-fail bg-white px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest text-fail">
          ▲ Fault: {lastError}
        </div>
      )}
    </div>
  );
}

function SystemChannel({
  label,
  value,
  tier,
}: {
  label: string;
  value: string;
  tier: StatusTier;
}) {
  return (
    <div className="flex items-center gap-2.5">
      <Dot tier={tier} />
      <div className="flex flex-col leading-tight">
        <span className="font-mono text-[9px] uppercase tracking-[0.25em] text-text-dim">
          {label}
        </span>
        <span className="font-mono text-[13px] font-semibold text-text">
          {value}
        </span>
      </div>
    </div>
  );
}

function CountChannel({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col leading-tight">
      <span className="font-mono text-[9px] uppercase tracking-[0.25em] text-text-dim">
        {label}
      </span>
      <span className="font-mono text-[13px] font-semibold tabular-nums text-text">
        {value.toString().padStart(2, "0")}
      </span>
    </div>
  );
}

function Dot({ tier }: { tier: StatusTier }) {
  const isLive = tier === "ok";
  return (
    <span className="relative inline-flex h-2.5 w-2.5 items-center justify-center" aria-hidden>
      {isLive && (
        <span className={`absolute h-2.5 w-2.5 rounded-full ${dotClass(tier)} opacity-50 animate-ping`} />
      )}
      <span className={`relative h-2.5 w-2.5 rounded-full ${dotClass(tier)}`} />
    </span>
  );
}

function linkLabel(c: ConnectionState): string {
  switch (c.kind) {
    case "disconnected": return "OFFLINE";
    case "connecting": return "LINKING";
    case "connected": return "ONLINE";
    case "failed": return "FAULT";
  }
}
