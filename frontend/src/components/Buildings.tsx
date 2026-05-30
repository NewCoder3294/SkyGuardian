"use client";

import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";

/**
 * Real-world OSM building footprints, extruded as 3D meshes in the local
 * SLAM frame. Data is pre-cached server-side by `scripts/fetch_buildings.py`
 * and served at /map/buildings as a single JSON blob — no runtime network
 * calls, no API keys. Works fully offline.
 */

interface BuildingRecord {
  id: number | null;
  name: string | null;
  height_m: number;
  polygon: [number, number][]; // [east_m, north_m] pairs in our local frame
}

interface BuildingsPayload {
  origin: { lat: number; lng: number };
  radius_m: number;
  count: number;
  buildings: BuildingRecord[];
}

interface Props {
  apiBase: string;
  /** Hide buildings beyond this radius from origin (metres) so the dashboard
   *  isn't crowded by distant downtown blocks. 0 = no clip. */
  clipRadiusM?: number;
  opacity?: number;
}

export function Buildings({ apiBase, clipRadiusM = 0, opacity = 0.55 }: Props) {
  const [data, setData] = useState<BuildingsPayload | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let stopped = false;
    fetch(`${apiBase}/map/buildings`, { cache: "no-store" })
      .then(async (res) => {
        if (res.status === 404) {
          if (!stopped) setMissing(true);
          return null;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as BuildingsPayload;
      })
      .then((d) => {
        if (!stopped && d) setData(d);
      })
      .catch(() => {
        if (!stopped) setMissing(true);
      });
    return () => {
      stopped = true;
    };
  }, [apiBase]);

  const meshes = useMemo(() => {
    if (!data) return [] as { key: string; geometry: THREE.ExtrudeGeometry; pos: [number, number, number] }[];
    const out: { key: string; geometry: THREE.ExtrudeGeometry; pos: [number, number, number] }[] = [];

    for (const b of data.buildings) {
      if (b.polygon.length < 3) continue;
      // Optional clip: skip polygons whose centroid is past the operator's
      // working radius. Keeps the dashboard from being overwhelmed by an
      // entire downtown.
      if (clipRadiusM > 0) {
        const cx = b.polygon.reduce((s, p) => s + p[0], 0) / b.polygon.length;
        const cy = b.polygon.reduce((s, p) => s + p[1], 0) / b.polygon.length;
        if (cx * cx + cy * cy > clipRadiusM * clipRadiusM) continue;
      }

      const shape = new THREE.Shape();
      // Polygons live in (east_m, north_m). Our scene maps world.y → three.z
      // (negated) via worldToScene; here we draw the 2D footprint in shape
      // space, then place the extrude along three.y for vertical height. The
      // group rotation/translation matches LocalMap3D's axis convention.
      const first = b.polygon[0];
      shape.moveTo(first[0], -first[1]);
      for (let i = 1; i < b.polygon.length; i++) {
        shape.lineTo(b.polygon[i][0], -b.polygon[i][1]);
      }
      shape.closePath();
      const geometry = new THREE.ExtrudeGeometry(shape, {
        depth: Math.max(2, b.height_m),
        bevelEnabled: false,
      });
      // ExtrudeGeometry extrudes along +Z. We want the height to come up
      // along +Y in scene space (up). Rotate the geometry so the footprint
      // lies on the XZ plane and the extrusion direction becomes +Y.
      geometry.rotateX(-Math.PI / 2);
      out.push({
        key: `${b.id ?? "rel"}-${out.length}`,
        geometry,
        pos: [0, 0, 0],
      });
    }
    return out;
  }, [data, clipRadiusM]);

  // Cleanup on unmount / data change.
  useEffect(() => {
    return () => {
      for (const m of meshes) m.geometry.dispose();
    };
  }, [meshes]);

  if (missing || !data) return null;

  return (
    <group>
      {meshes.map((m) => (
        <mesh key={m.key} geometry={m.geometry} position={m.pos}>
          <meshStandardMaterial
            color="#3a4736"
            emissive="#7d6a35"
            emissiveIntensity={0.12}
            transparent
            opacity={opacity}
            roughness={0.5}
            metalness={0.15}
          />
        </mesh>
      ))}
    </group>
  );
}
