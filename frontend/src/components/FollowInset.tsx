"use client";

import type { FollowState } from "@/lib/contracts";
import { followTargetLabel } from "@/lib/followTarget";

/**
 * Relative follow widget: the companion Tello's range + bearing from the soldier,
 * drawn as a small radar with the soldier at centre. Deliberately self-contained —
 * NOT co-registered with the SLAM map — because the phone's follow frame and the
 * Mavic SLAM frame don't share a reference. Reads `follow_state` from the brain
 * (originated on the phone). Renders nothing until the phone has reported.
 */
export function FollowInset({ state }: { state: FollowState | null }) {
  if (!state) return null;

  const targetLabel = followTargetLabel(state);

  // "stale" = the laptop hasn't heard from the phone recently (link dead/wedged);
  // surfaced in red so a frozen reading can't be mistaken for a live follow.
  const phaseColor =
    state.phase === "following"
      ? "text-ok"
      : state.phase === "lost" || state.phase === "stale"
        ? "text-fail"
        : state.phase === "manual" || state.phase === "confirming"
          ? "text-accent"
          : "text-text-dim";

  const subtitle =
    state.phase === "stale" ? "link lost" : state.active ? null : "on deck";

  // Radar geometry. Bearing 0° = soldier's facing (straight up); +deg clockwise.
  const R = 46; // px radius of the outer ring
  const cx = 56;
  const cy = 56;
  const maxRange = Math.max(4, state.distance_m * 1.25); // adaptive ring scale
  const rNorm = state.active ? Math.min(state.distance_m / maxRange, 1) : 0;
  const a = (state.bearing_deg * Math.PI) / 180;
  const tx = cx + R * rNorm * Math.sin(a);
  const ty = cy - R * rNorm * Math.cos(a);

  return (
    <div className="flex items-center gap-3 border border-border-strong bg-surface-elevated/95 px-3 py-2 font-mono backdrop-blur">
      <svg width="112" height="112" viewBox="0 0 112 112" aria-hidden>
        {/* range rings */}
        <circle cx={cx} cy={cy} r={R} className="fill-none stroke-border" strokeWidth="1" />
        <circle cx={cx} cy={cy} r={R * 0.5} className="fill-none stroke-border/60" strokeWidth="1" />
        {/* facing axis */}
        <line x1={cx} y1={cy} x2={cx} y2={cy - R} className="stroke-border/60" strokeWidth="1" />
        {/* soldier at centre */}
        <circle cx={cx} cy={cy} r="3.5" className="fill-accent" />
        {/* tello, when airborne */}
        {state.active && (
          <>
            <line
              x1={cx}
              y1={cy}
              x2={tx}
              y2={ty}
              className={state.phase === "following" ? "stroke-ok" : "stroke-fail"}
              strokeWidth="1.5"
            />
            <circle
              cx={tx}
              cy={ty}
              r="4"
              className={state.phase === "following" ? "fill-ok" : "fill-fail"}
            />
          </>
        )}
      </svg>
      <div className="flex flex-col gap-0.5 pr-1">
        <span className="text-[9px] uppercase tracking-[0.3em] text-text-dim">Follow · Tello</span>
        <span className={`text-[13px] font-semibold uppercase tracking-[0.15em] ${phaseColor}`}>
          {state.phase}
        </span>
        {targetLabel && (
          <span className="text-[10px] uppercase tracking-[0.15em] text-text-dim">
            {targetLabel}
          </span>
        )}
        {state.active ? (
          <span className="text-[11px] text-text-muted">
            {state.distance_m.toFixed(1)} m · {Math.round(state.bearing_deg)}°
          </span>
        ) : (
          <span className={`text-[11px] ${state.phase === "stale" ? "text-fail" : "text-text-dim"}`}>
            {subtitle}
          </span>
        )}
      </div>
    </div>
  );
}
