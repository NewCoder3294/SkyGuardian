import { describe, it, expect } from "vitest";
import { TrailStore } from "./trails";

describe("TrailStore", () => {
  it("starts a trail for a moving entity", () => {
    const store = new TrailStore();
    store.update([{ id: "drone", type: "drone", x: 0, y: 0 }]);
    store.update([{ id: "drone", type: "drone", x: 1, y: 0 }]);
    expect(store.get("drone")).toEqual([{ x: 0, y: 0 }, { x: 1, y: 0 }]);
  });

  it("dedupes sub-threshold jitter", () => {
    const store = new TrailStore(0.2 /* min metres */);
    store.update([{ id: "drone", type: "drone", x: 0, y: 0 }]);
    store.update([{ id: "drone", type: "drone", x: 0.1, y: 0 }]); // < 0.2 m
    expect(store.get("drone")).toEqual([{ x: 0, y: 0 }]);
  });

  it("caps the ring buffer", () => {
    const store = new TrailStore(0, 3 /* cap */);
    for (let i = 0; i < 5; i++) {
      store.update([{ id: "drone", type: "drone", x: i, y: 0 }]);
    }
    expect(store.get("drone")).toEqual([{ x: 2, y: 0 }, { x: 3, y: 0 }, { x: 4, y: 0 }]);
  });

  it("ignores non-moving entity types", () => {
    const store = new TrailStore();
    store.update([{ id: "poi1", type: "poi", x: 0, y: 0 }]);
    expect(store.get("poi1")).toEqual([]);
  });

  it("clears a trail when its entity disappears", () => {
    const store = new TrailStore();
    store.update([{ id: "drone", type: "drone", x: 0, y: 0 }]);
    store.update([]); // entity gone
    expect(store.get("drone")).toEqual([]);
  });
});
