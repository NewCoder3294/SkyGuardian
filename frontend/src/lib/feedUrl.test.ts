import { describe, it, expect } from "vitest";
import { httpFromWs } from "./feedUrl";
import { DEFAULT_WS_URL } from "./wsConfig";

/**
 * httpFromWs is what keeps the dashboard's video feed and REST calls on the
 * SAME host and port as the world-model WebSocket. If it drifted, the map
 * (WS) and the video/intel (HTTP) could point at different processes. These
 * tests pin that invariant so "everything comes from one brain" holds.
 */
describe("httpFromWs", () => {
  it("maps ws:// to http://", () => {
    expect(httpFromWs("ws://localhost:8000/ws", "/health")).toBe(
      "http://localhost:8000/health",
    );
  });

  it("maps wss:// to https://", () => {
    expect(httpFromWs("wss://brain.local:8000/ws", "/health")).toBe(
      "https://brain.local:8000/health",
    );
  });

  it("preserves the host and port from the WS URL", () => {
    expect(httpFromWs("ws://192.168.10.1:8000/ws", "/video/leader.jpg")).toBe(
      "http://192.168.10.1:8000/video/leader.jpg",
    );
  });

  it("returns a bare origin (no trailing slash) for an empty path", () => {
    expect(httpFromWs("ws://localhost:8000/ws", "")).toBe(
      "http://localhost:8000",
    );
  });

  it("adds a leading slash when the path is missing one", () => {
    expect(httpFromWs("ws://localhost:8000/ws", "video/source")).toBe(
      "http://localhost:8000/video/source",
    );
  });

  it("falls back to the raw path when the WS URL is malformed", () => {
    expect(httpFromWs("not-a-url", "/health")).toBe("/health");
  });
});

/**
 * Same-brain integration check: the video feed and the API base the dashboard
 * derives from the default WS must land on the exact origin the WS connects to
 * (host + port). This is the end-to-end guarantee behind the :8000 fix.
 */
describe("default brain endpoints stay on one origin", () => {
  const brainOrigin = new URL(DEFAULT_WS_URL).origin.replace(/^ws/, "http");

  it("derives the leader video feed from the same origin as the WS", () => {
    expect(httpFromWs(DEFAULT_WS_URL, "/video/leader.jpg")).toBe(
      `${brainOrigin}/video/leader.jpg`,
    );
  });

  it("derives the API base from the same origin as the WS", () => {
    expect(httpFromWs(DEFAULT_WS_URL, "")).toBe(brainOrigin);
  });

  it("puts the video feed on port 8000", () => {
    expect(new URL(httpFromWs(DEFAULT_WS_URL, "/video/leader.jpg")).port).toBe(
      "8000",
    );
  });
});
