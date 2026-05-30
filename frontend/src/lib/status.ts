/** Maps a channel's raw value to a traffic-light tier. Keep this module the
 *  single source of truth so StatusBar, sidebar widgets, and any future status
 *  surface all classify state the same way. */

export type StatusTier = "ok" | "warn" | "fail" | "neutral";

export function linkTier(kind: string): StatusTier {
  switch (kind) {
    case "connected": return "ok";
    case "connecting": return "warn";
    case "failed": return "fail";
    case "disconnected":
    default: return "fail";
  }
}

/** Leader video link health: `mavic` field in the Health message. */
export function leaderTier(value: string | undefined): StatusTier {
  switch (value) {
    case "streaming": return "ok";
    case "linking": return "warn";
    case "offline": return "fail";
    case undefined: return "neutral";
    default: return "neutral";
  }
}

/** Follower (companion) link health: `tello` field. */
export function followerTier(value: string | undefined): StatusTier {
  switch (value) {
    case "connected": return "ok";
    case "connecting": return "warn";
    case "lost":
    case "error":
    case "disconnected": return "fail";
    case undefined: return "neutral";
    default: return "neutral";
  }
}

/** Perception pipeline health: `perception` field. */
export function perceptionTier(value: string | undefined): StatusTier {
  switch (value) {
    case "ok": return "ok";
    case "running":
    case "degraded": return "warn";
    case "error": return "fail";
    case undefined: return "neutral";
    default: return "neutral";
  }
}

/** Tailwind bg class for a tier dot. */
export function dotClass(tier: StatusTier): string {
  switch (tier) {
    case "ok": return "bg-ok";
    case "warn": return "bg-warn";
    case "fail": return "bg-fail";
    case "neutral": return "bg-text-dim";
  }
}
