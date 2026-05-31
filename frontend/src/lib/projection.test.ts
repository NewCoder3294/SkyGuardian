import { describe, it, expect } from "vitest";
import { localMetersToLatLng } from "./projection";

describe("localMetersToLatLng", () => {
  const origin = { lat: 32.8791, lng: -117.2322 };
  it("returns origin for (0,0)", () => {
    const p = localMetersToLatLng(origin, 0, 0);
    expect(p.lat).toBeCloseTo(origin.lat, 9);
    expect(p.lng).toBeCloseTo(origin.lng, 9);
  });
  it("north offset increases lat by ~m/111320", () => {
    const p = localMetersToLatLng(origin, 0, 1113.2);
    expect(p.lat - origin.lat).toBeCloseTo(0.01, 4);
  });
  it("east offset widens by 1/cos(lat)", () => {
    const p = localMetersToLatLng(origin, 1000, 0);
    expect(p.lng).toBeGreaterThan(origin.lng);
  });
});
