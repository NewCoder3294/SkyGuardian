/** Binary status — every channel is either ONLINE (green) or OFFLINE (red).
 *  No amber/yellow/intermediate tier. If a system isn't actively producing
 *  what it's supposed to, it's offline. */

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

/** Tailwind bg class for a tier dot. */
export function dotClass(tier: StatusTier): string {
  return tier === "ok" ? "bg-ok" : "bg-fail";
}

/** Display label for a tier — always one of two words. */
export function tierLabel(tier: StatusTier): string {
  return tier === "ok" ? "ONLINE" : "OFFLINE";
}
