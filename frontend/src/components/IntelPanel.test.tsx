import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IntelPanel } from "./IntelPanel";
import type { DetectionBox } from "@/lib/contracts";
import type { DetectionEvent } from "@/lib/useWorldClient";

function box(label: string): DetectionBox {
  return { label, confidence: 0.9, cx: 0.5, cy: 0.5, w: 0.1, h: 0.1 };
}

function rowSeen(label: string): string {
  const cell = screen.getByText(label).closest("tr");
  if (!cell) throw new Error(`no row for ${label}`);
  // Columns: Visible | Class | Seen | Last
  const tds = within(cell).getAllByRole("cell");
  return tds[2].textContent ?? "";
}

describe("IntelPanel seenCount", () => {
  beforeEach(() => {
    // Deterministic clock so "visible now" math is stable.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("counts a label once per frame regardless of crowd size", () => {
    const now = Date.now() / 1000;
    // One frame with three people, one frame with one person => 2 sightings.
    const log: DetectionEvent[] = [
      { t: now, source: "leader", boxes: [box("person"), box("person"), box("person")] },
      { t: now - 1, source: "leader", boxes: [box("person")] },
    ];
    render(<IntelPanel detections={{}} detectionLog={log} />);
    expect(rowSeen("PERSON")).toBe("2");
  });

  it("counts distinct labels in the same frame separately", () => {
    const now = Date.now() / 1000;
    const log: DetectionEvent[] = [
      { t: now, source: "leader", boxes: [box("person"), box("car"), box("car")] },
    ];
    render(<IntelPanel detections={{}} detectionLog={log} />);
    expect(rowSeen("PERSON")).toBe("1");
    expect(rowSeen("CAR")).toBe("1");
  });
});
