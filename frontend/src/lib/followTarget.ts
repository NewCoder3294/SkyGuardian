import type { FollowState } from "./contracts";

/**
 * Human display label for the follow target, composed from target_type +
 * target_label. Kept out of the FollowInset component so it can be unit-tested.
 * Returns null when nothing is being followed.
 */
export function followTargetLabel(state: FollowState | null): string | null {
  if (!state || !state.target_type) return null;
  if (state.target_type === "visual_me") return "ME (visual)";
  return state.target_label ? `TAG #${state.target_label}` : "TAG";
}
