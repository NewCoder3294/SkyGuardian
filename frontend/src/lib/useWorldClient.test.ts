import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useWorldClient } from "./useWorldClient";

class FakeWS {
  static last: FakeWS | null = null;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  readyState = 1;
  constructor(public url: string) {
    FakeWS.last = this;
  }
  send() {}
  close() {}
}

describe("useWorldClient buildings_updated", () => {
  beforeEach(() => {
    (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS as unknown;
  });
  afterEach(() => vi.restoreAllMocks());

  it("bumps buildingsVersion on a buildings_updated frame", () => {
    const { result } = renderHook(() => useWorldClient("ws://x/ws"));
    const v0 = result.current.buildingsVersion;
    act(() => {
      FakeWS.last!.onmessage!({
        data: JSON.stringify({
          type: "buildings_updated",
          origin: { lat: 1, lng: 2 },
          radius_m: 400,
          count: 5,
          t: 1,
        }),
      });
    });
    expect(result.current.buildingsVersion).toBe(v0 + 1);
  });
});
