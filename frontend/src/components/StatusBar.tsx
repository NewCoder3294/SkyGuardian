"use client";

import type { Health } from "@/lib/contracts";
import type { ConnectionState } from "@/lib/useWorldClient";
import {
  dotClass,
  leaderTier,
  linkTier,
  perceptionTier,
  tierLabel,
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
 * Read-only telemetry strip. Every channel is binary: ONLINE (green) or
 * OFFLINE (red) — no intermediate states. The eye doesn't have to think.
 */
export function StatusBar({
  connection,
  lastError,
  health,
  entityCount,
  detectionCount,
}: Props) {
  const linkT = linkTier(connection.kind);
  const leaderT = leaderTier(health?.mavic);
  const percT = perceptionTier(health?.perception);

  return (
    <div className="border-b border-border bg-surface/50 px-5 py-3 backdrop-blur-sm">
      <div className="flex flex-wrap items-center gap-3">
        <SystemChannel label="Link" value={tierLabel(linkT)} tier={linkT} />
        <SystemChannel label="Leader" value={tierLabel(leaderT)} tier={leaderT} />
        <SystemChannel label="Perception" value={tierLabel(percT)} tier={percT} />

        <span className="h-6 w-px bg-border" aria-hidden />

        <CountChannel label="World" value={entityCount} />
        <CountChannel label="Detections" value={detectionCount} />
      </div>
      {lastError && (
        <div className="mt-2 inline-flex items-center gap-2 rounded-md border border-fail/60 bg-fail/10 px-3 py-1 font-mono text-[10px] uppercase tracking-widest text-fail">
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
  const isOk = tier === "ok";
  return (
    <div
      className={`flex items-center gap-2.5 rounded-full border px-3 py-1.5 ${
        isOk
          ? "border-accent/40 bg-accent/5"
          : "border-border-strong bg-surface-elevated"
      }`}
    >
      <Dot tier={tier} />
      <div className="flex flex-col leading-tight">
        <span className="font-sans text-[9px] uppercase tracking-[0.25em] text-text-dim">
          {label}
        </span>
        <span
          className={`font-sans text-[12px] font-semibold ${
            isOk ? "text-accent" : "text-text"
          }`}
        >
          {value}
        </span>
      </div>
    </div>
  );
}

function CountChannel({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2.5 rounded-full border border-border-strong bg-surface-elevated px-3 py-1.5">
      <div className="flex flex-col leading-tight">
        <span className="font-sans text-[9px] uppercase tracking-[0.25em] text-text-dim">
          {label}
        </span>
        <span className="font-mono text-[12px] font-semibold tabular-nums text-text">
          {value.toString().padStart(2, "0")}
        </span>
      </div>
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
      <span
        className={`relative h-2.5 w-2.5 rounded-full ${dotClass(tier)} ${
          isLive ? "shadow-glow-cyan" : ""
        }`}
      />
    </span>
  );
}
