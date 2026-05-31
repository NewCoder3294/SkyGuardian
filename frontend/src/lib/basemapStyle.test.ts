import { describe, it, expect } from "vitest";
import { buildBasemapStyle } from "./basemapStyle";

describe("buildBasemapStyle", () => {
  const style = buildBasemapStyle("http://localhost:8000");
  it("has no remote URLs (offline guard)", () => {
    const json = JSON.stringify(style);
    const urls = json.match(/https?:\/\/[^"']+/g) ?? [];
    for (const u of urls) expect(u.startsWith("http://localhost:8000")).toBe(true);
  });
  it("uses local glyphs + pmtiles source, no sprite", () => {
    expect(style.glyphs).toContain("http://localhost:8000/map/fonts/");
    expect(JSON.stringify(style.sources)).toContain("pmtiles://");
    expect((style as Record<string, unknown>).sprite).toBeUndefined();
  });
  it("is monochrome (no saturated hue tokens)", () => {
    const json = JSON.stringify(style);
    expect(json).not.toMatch(/#(?:ff0000|00ff00|1d4ed8|0000ff)/i);
  });
});
