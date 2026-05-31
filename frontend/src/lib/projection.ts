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

const M_PER_DEG_LAT = 111_320;

/** Convert local-frame metres (east, north; launch=origin) to lat/lng.
 * Equirectangular approximation, fine for a bounded operational area. */
export function localMetersToLatLng(
  origin: { lat: number; lng: number },
  east_m: number,
  north_m: number,
): { lat: number; lng: number } {
  const lat = origin.lat + north_m / M_PER_DEG_LAT;
  const lng =
    origin.lng + east_m / (M_PER_DEG_LAT * Math.max(Math.cos((origin.lat * Math.PI) / 180), 1e-6));
  return { lat, lng };
}
