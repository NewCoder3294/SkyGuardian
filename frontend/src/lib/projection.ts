import type { Vec3 } from "./contracts";

/**
 * Mirror of mobile/Sources/MapProjection.swift. Origin at view centre = launch
 * point. World +y is up, screen +y is down. Square-fit: spanMeters across the
 * shorter dimension.
 */
export class MapProjection {
  constructor(public spanMeters: number = 20) {}

  scale(width: number, height: number): number {
    return Math.min(width, height) / Math.max(this.spanMeters, 0.001);
  }

  project(p: Vec3, width: number, height: number): { x: number; y: number } {
    const s = this.scale(width, height);
    return {
      x: width / 2 + p.x * s,
      y: height / 2 - p.y * s,
    };
  }
}
