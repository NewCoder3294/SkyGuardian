import { describe, it, expect } from "vitest";
import { DEFAULT_WS_URL, resolveWsUrl } from "./wsConfig";

/**
 * The brain's address must agree across all three clients. The backend binds
 * :8000 (backend/run.sh) and the mobile client defaults to :8000
 * (mobile/Sources/WorldClient.swift). These tests pin the dashboard to the same
 * port so a regression that points it elsewhere (the :8001 bug) fails loudly.
 */
describe("DEFAULT_WS_URL", () => {
  it("targets port 8000 to match the backend bind and the mobile client", () => {
    expect(new URL(DEFAULT_WS_URL).port).toBe("8000");
  });

  it("uses the ws scheme", () => {
    expect(new URL(DEFAULT_WS_URL).protocol).toBe("ws:");
  });

  it("subscribes to the /ws endpoint", () => {
    expect(new URL(DEFAULT_WS_URL).pathname).toBe("/ws");
  });
});

describe("resolveWsUrl", () => {
  it("returns the default when no override is set", () => {
    expect(resolveWsUrl(undefined)).toBe(DEFAULT_WS_URL);
  });

  it("returns the default when the override is null", () => {
    expect(resolveWsUrl(null)).toBe(DEFAULT_WS_URL);
  });

  it("returns the default when the override is an empty string", () => {
    expect(resolveWsUrl("")).toBe(DEFAULT_WS_URL);
  });

  it("returns the default when the override is only whitespace", () => {
    expect(resolveWsUrl("   ")).toBe(DEFAULT_WS_URL);
  });

  it("uses a remote-brain override when one is provided", () => {
    expect(resolveWsUrl("ws://192.168.10.1:8000/ws")).toBe(
      "ws://192.168.10.1:8000/ws",
    );
  });
});
