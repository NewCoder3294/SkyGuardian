import { describe, it, expect } from "vitest";
import { buildMissionContext } from "./foundryServer";

/**
 * buildMissionContext grounds the AIP language model. These tests pin its two
 * guarantees: it surfaces every mission's per-class counts, and it is
 * deterministic (stable mission + class ordering) so the same ontology data
 * always produces the same prompt — no Date/random, safe to feed an LLM.
 */
describe("buildMissionContext", () => {
  const missions = [
    {
      missionId: "ridge-delta",
      framesOut: 6,
      trainCount: 4,
      valCount: 2,
      gemmaLabeledCount: 3,
    },
    {
      missionId: "overwatch-charlie",
      framesOut: 10,
      trainCount: 8,
      valCount: 2,
      gemmaLabeledCount: 10,
    },
  ];
  const classes = [
    { missionId: "overwatch-charlie", label: "vehicle", count: 9 },
    { missionId: "overwatch-charlie", label: "gun_truck", count: 5 },
    { missionId: "ridge-delta", label: "structure", count: 3 },
  ];

  it("orders missions deterministically by id regardless of input order", () => {
    const ctx = buildMissionContext(missions, classes);
    expect(ctx.indexOf("overwatch-charlie")).toBeLessThan(
      ctx.indexOf("ridge-delta"),
    );
  });

  it("lists each mission's per-class detection counts, highest first", () => {
    const ctx = buildMissionContext(missions, classes);
    const line = ctx
      .split("\n")
      .find((l) => l.startsWith("- overwatch-charlie"));
    expect(line).toContain("vehicle=9");
    expect(line).toContain("gun_truck=5");
    // count desc within a mission
    expect(line!.indexOf("vehicle=9")).toBeLessThan(line!.indexOf("gun_truck=5"));
  });

  it("includes a cross-mission detection total per label", () => {
    const ctx = buildMissionContext(missions, classes);
    expect(ctx).toContain("DETECTION TOTALS (all missions):");
    expect(ctx).toContain("vehicle=9");
    expect(ctx).toContain("structure=3");
  });

  it("is a pure function — identical input yields identical output", () => {
    expect(buildMissionContext(missions, classes)).toBe(
      buildMissionContext(missions, classes),
    );
  });

  it("handles an empty ontology without throwing", () => {
    const ctx = buildMissionContext([], []);
    expect(ctx).toContain("MISSIONS (0):");
    expect(ctx).toContain("DETECTION TOTALS (all missions): none");
  });
});
