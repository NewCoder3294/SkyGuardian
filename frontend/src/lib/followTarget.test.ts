import { describe, it, expect } from "vitest";
import { followTargetLabel } from "./followTarget";
import type { FollowState } from "./contracts";

const base: FollowState = {
  type: "follow_state", active: true, phase: "following",
  distance_m: 2, bearing_deg: 0, t: 1,
};

describe("followTargetLabel", () => {
  it("labels a visual-me lock", () => {
    expect(followTargetLabel({ ...base, target_type: "visual_me" })).toBe("ME (visual)");
  });
  it("labels a tag lock with its id", () => {
    expect(followTargetLabel({ ...base, target_type: "tag", target_label: "7" })).toBe("TAG #7");
  });
  it("labels a tag lock with no id", () => {
    expect(followTargetLabel({ ...base, target_type: "tag" })).toBe("TAG");
  });
  it("returns null when there is no target", () => {
    expect(followTargetLabel({ ...base, target_type: null })).toBeNull();
    expect(followTargetLabel(null)).toBeNull();
  });
});
