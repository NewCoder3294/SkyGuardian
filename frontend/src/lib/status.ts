/** Binary status — every channel is either ONLINE or OFFLINE. No amber/yellow/
 *  intermediate tier. If a system isn't actively producing what it's supposed
 *  to, it's offline.
 *
 *  Presentation is strict monochrome: a channel going down is a loss-of-link
 *  event, NOT a threat, so it never renders red. ONLINE = solid ink, OFFLINE =
 *  hollow/dim ink. Red (`--fail`) is reserved exclusively for actual threats
 *  (see ThreatAlert). */

export type StatusTier = "ok" | "fail";

export function linkTier(kind: string): StatusTier {
  return kind === "connected" ? "ok" : "fail";
}

/** Leader video link health: `mavic` field in the Health message.
 *  ONLINE only when real frames are being decoded. */
export function leaderTier(value: string | undefined): StatusTier {
  return value === "streaming" ? "ok" : "fail";
}

/** Perception pipeline health: `perception` field.
 *  ONLINE only when the SLAM anchor is locked and YOLO is loaded —
 *  i.e. the brain is actually mapping things. */
export function perceptionTier(value: string | undefined): StatusTier {
  return value === "ok" ? "ok" : "fail";
}

/** Tailwind class(es) for a tier dot. ONLINE = solid ink dot; OFFLINE = hollow
 *  dashed ink ring (monochrome — down is loss-of-link, not a threat, so no red). */
export function dotClass(tier: StatusTier): string {
  return tier === "ok"
    ? "bg-text"
    : "border border-dashed border-text-dim bg-transparent";
}

/** Tailwind text class for a channel label. ONLINE reads at muted ink, OFFLINE
 *  drops to dim ink (never red). */
export function labelClass(tier: StatusTier): string {
  return tier === "ok" ? "text-text-muted" : "text-text-dim";
}

/** Display label for a tier — always one of two words. */
export function tierLabel(tier: StatusTier): string {
  return tier === "ok" ? "ONLINE" : "OFFLINE";
}
