import type { EntityType } from "./contracts";

export interface TrailPoint {
  x: number;
  y: number;
}

interface MovingInput {
  id: string;
  type: EntityType;
  x: number;
  y: number;
}

/** Moving entity types that get a path. Mirrors mobile WorldClient.appendTrails. */
const MOVING: ReadonlySet<EntityType> = new Set(["soldier", "drone"]);

/**
 * Accumulates per-entity movement trails from the WS entity stream — the
 * dashboard equivalent of mobile/Sources/Localizer.swift's droneTrail. Dedupes
 * sub-threshold jitter, caps history, and clears a trail when its entity leaves
 * the snapshot.
 */
export class TrailStore {
  private trails = new Map<string, TrailPoint[]>();

  constructor(
    private minMetres = 0.2,
    private cap = 240,
  ) {}

  update(entities: MovingInput[]): void {
    const seen = new Set<string>();
    for (const e of entities) {
      if (!MOVING.has(e.type)) continue;
      seen.add(e.id);
      const pts = this.trails.get(e.id) ?? [];
      const last = pts[pts.length - 1];
      if (last) {
        const dx = last.x - e.x;
        const dy = last.y - e.y;
        if (dx * dx + dy * dy < this.minMetres * this.minMetres) continue;
      }
      pts.push({ x: e.x, y: e.y });
      if (pts.length > this.cap) pts.splice(0, pts.length - this.cap);
      this.trails.set(e.id, pts);
    }
    for (const id of this.trails.keys()) {
      if (!seen.has(id)) this.trails.delete(id);
    }
  }

  get(id: string): TrailPoint[] {
    return this.trails.get(id) ?? [];
  }

  all(): Map<string, TrailPoint[]> {
    return this.trails;
  }
}
