"use client";

import { useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { Grid, Html, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { Entity, EntityStatus, EntityType, Vec3 } from "@/lib/contracts";
import { isDesignatedTarget } from "@/lib/entities";
import { SectionHeader, StatusTag } from "@/components/tactical";
import { Buildings } from "./Buildings";

/**
 * 3D top-down/perspective scene of the local frame. All data here is already
 * 3D — SLAM camera pose, sparse landmarks, and (when the depth model is on)
 * YOLO entities — so the scene's just rendering what the brain already
 * computes. Orbit / zoom / pan via mouse.
 *
 * Axis convention:
 *   - World (x, y, z) = (east, north, up) — the canonical SLAM convention.
 *   - Three.js Y is up. Map world.z → three.y, world.y → three.-z so
 *     "forward in world" comes out of the screen.
 *
 * Pure B&W: all geometry is black or grey, no hue. Status alpha thins lost
 * entities. Landmarks (point cloud) shown only when `showLandmarks` is true.
 */
interface Props {
  entities: Entity[];
  landmarks?: Entity[];
  spanMeters?: number;
  showLandmarks?: boolean;
  /** Backend origin so we can fetch the cached buildings JSON. */
  apiBase?: string;
  /** Building-clip radius (metres). 0 = show everything in the cache. */
  buildingsRadiusM?: number;
  /** Optional single-line status (entity count, playback time, etc.). */
  statusLine?: string;
  /** Increments each time the buildings cache is refreshed (from useWorldClient). */
  buildingsVersion?: number;
  /** "indoor" hides the OSM buildings layer — they're geographic city footprints
   *  with no relationship to an indoor SLAM frame. Default "outdoor". */
  environment?: "outdoor" | "indoor";
}

export function LocalMap3D({
  entities,
  landmarks = [],
  spanMeters = 20,
  showLandmarks = false,
  apiBase,
  buildingsRadiusM = 0,
  statusLine,
  buildingsVersion,
  environment = "outdoor",
}: Props) {
  // When a buildings layer is configured we frame the camera against the
  // building radius (not the SLAM span) so the campus is visible on first
  // paint. Otherwise stick with the tight SLAM-only default. Indoor mode
  // collapses to the SLAM span regardless of building config so the camera
  // doesn't start zoomed-out staring at empty space.
  const showBuildings = environment === "outdoor";
  const cameraSpan = showBuildings && buildingsRadiusM > 0 ? buildingsRadiusM * 0.9 : spanMeters;
  return (
    <div className="relative h-full w-full bg-bg">
      <Canvas
        camera={{ position: [cameraSpan, cameraSpan, cameraSpan], fov: 45 }}
        style={{ background: "#f1f1f0" }}
        dpr={[1, 2]}
      >
        <ambientLight intensity={0.5} />
        <directionalLight position={[10, 20, 10]} intensity={0.5} color="#ffffff" />
        <directionalLight position={[-10, 15, -10]} intensity={0.25} color="#cfcfcf" />

        <SceneFloor span={cameraSpan} />
        <OriginMarker />
        {showBuildings && apiBase && (
          <Buildings apiBase={apiBase} clipRadiusM={buildingsRadiusM} buildingsVersion={buildingsVersion} />
        )}

        {entities.map((e) => (
          <EntityMarker key={e.id} entity={e} />
        ))}

        {showLandmarks &&
          landmarks.length > 0 && (
            <LandmarkCloud landmarks={landmarks} />
          )}

        <OrbitControls
          makeDefault
          enablePan
          minDistance={2}
          // Allow zooming far enough to see the full buildings cache when
          // present; otherwise stick with a comfortable SLAM-only range.
          maxDistance={Math.max(spanMeters * 4, buildingsRadiusM * 2.5, 50)}
          target={[0, 0, 0]}
        />
      </Canvas>
      <ViewLegend statusLine={statusLine} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scene primitives
// ---------------------------------------------------------------------------

function SceneFloor({ span }: { span: number }) {
  // Scale grid cell + section sizes with the camera span so the floor stays
  // readable from a 20 m SLAM view all the way out to an 800 m AO overview.
  // Roughly: ~50 cells per side, with major lines every 5 cells.
  const cellSize = Math.max(1, Math.round(span / 50));
  const sectionSize = cellSize * 5;
  return (
    <>
      <Grid
        args={[span * 4, span * 4]}
        position={[0, 0, 0]}
        cellSize={cellSize}
        cellThickness={0.6}
        cellColor="#1f1f1f"
        sectionSize={sectionSize}
        sectionThickness={1.2}
        sectionColor="#3a3a3a"
        fadeDistance={span * 3}
        fadeStrength={1.2}
        followCamera={false}
        infiniteGrid
      />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.001, 0]} receiveShadow>
        <planeGeometry args={[span * 8, span * 8]} />
        <meshBasicMaterial color="#141414" transparent opacity={0} />
      </mesh>
    </>
  );
}

function OriginMarker() {
  return (
    <group position={[0, 0.01, 0]}>
      <mesh>
        <cylinderGeometry args={[0.12, 0.12, 0.02, 24]} />
        <meshBasicMaterial color="#1a1a1a" />
      </mesh>
      <mesh position={[0, 0.05, 0]}>
        <ringGeometry args={[0.18, 0.22, 32]} />
        <meshBasicMaterial color="#1a1a1a" transparent opacity={0.5} side={2} />
      </mesh>
      <Html position={[0, 0.55, 0]} center distanceFactor={8} zIndexRange={[0, 0]}>
        <div className="pointer-events-none whitespace-nowrap border border-accent/60 bg-surface/85 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.3em] text-accent backdrop-blur-sm">
          Launch
        </div>
      </Html>
    </group>
  );
}

function EntityMarker({ entity }: { entity: Entity }) {
  const pos = worldToScene(entity.position);
  const alpha = STATUS_ALPHA[entity.status];
  const label = (entity.label ?? entity.id).toUpperCase();
  const designated = isDesignatedTarget(entity);

  return (
    <group position={pos}>
      {/* Designated recon target gets a red targeting reticle behind the glyph,
          matching LocalMap2D's drawDesignationReticle so the cue survives a
          2D->3D view toggle. */}
      {designated && <DesignationReticle alpha={alpha} />}
      {renderShape(entity.type, alpha)}
      <Html
        position={[0, shapeHeight(entity.type) + 0.3, 0]}
        center
        distanceFactor={8}
        zIndexRange={[0, 0]}
      >
        <div
          className={`pointer-events-none whitespace-nowrap border bg-surface/85 px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider backdrop-blur-sm ${
            designated ? "border-fail/70 text-fail" : "border-accent/40 text-accent"
          }`}
          style={{ opacity: alpha }}
        >
          {label}
        </div>
      </Html>
    </group>
  );
}

/** Red targeting reticle (ring + raised marker ring) for the designated recon
 *  target. Mirrors LocalMap2D's drawDesignationReticle. */
function DesignationReticle({ alpha }: { alpha: number }) {
  return (
    <group rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
      <mesh>
        <ringGeometry args={[0.5, 0.58, 40]} />
        <meshBasicMaterial color="#e0483a" transparent opacity={alpha} side={2} />
      </mesh>
      <mesh>
        <ringGeometry args={[0.72, 0.76, 40]} />
        <meshBasicMaterial
          color="#e0483a"
          transparent
          opacity={alpha * 0.5}
          side={2}
        />
      </mesh>
    </group>
  );
}

function LandmarkCloud({ landmarks }: { landmarks: Entity[] }) {
  const positions = useMemo(() => {
    const arr = new Float32Array(landmarks.length * 3);
    for (let i = 0; i < landmarks.length; i++) {
      const p = worldToScene(landmarks[i].position);
      arr[i * 3 + 0] = p[0];
      arr[i * 3 + 1] = p[1];
      arr[i * 3 + 2] = p[2];
    }
    return arr;
  }, [landmarks]);

  return (
    <points>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
        />
      </bufferGeometry>
      <pointsMaterial color="#8a8a8a" size={0.06} sizeAttenuation transparent opacity={0.5} />
    </points>
  );
}

function ViewLegend({ statusLine }: { statusLine?: string }) {
  return (
    <div className="tac-corners pointer-events-none absolute left-4 top-4 border border-border-strong bg-surface/80 backdrop-blur-sm">
      <SectionHeader
        index="01"
        label="Local Frame"
        aside={<StatusTag state="live" label="3D" />}
        className="py-1.5"
      />
      <div className="space-y-1 px-3 pb-2 font-mono text-[10px] uppercase tracking-widest text-text-muted">
        <div className="text-text-dim">Drag · orbit · scroll zoom</div>
        {statusLine && <div className="text-text-muted">{statusLine}</div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shape per entity type
// ---------------------------------------------------------------------------

function renderShape(type: EntityType, alpha: number): JSX.Element {
  // Hazards lock to signal red (the only hue — reserved for threats); every
  // other track reads monochrome ink (solid markers near-black, secondary grey).
  const color =
    type === "hazard" ? "#e0483a" : type === "soldier" ? "#5a5a5a" : "#1a1a1a";
  const mat = (
    <meshStandardMaterial
      color={color}
      emissive={color}
      emissiveIntensity={0.5}
      transparent
      opacity={alpha}
      roughness={0.35}
      metalness={0.2}
    />
  );

  switch (type) {
    case "soldier":
      return (
        <mesh position={[0, 0.4, 0]}>
          <cylinderGeometry args={[0.18, 0.18, 0.8, 24]} />
          {mat}
        </mesh>
      );
    case "drone":
      return (
        <mesh position={[0, 0.25, 0]} rotation={[0, 0, 0]}>
          <coneGeometry args={[0.25, 0.5, 4]} />
          {mat}
        </mesh>
      );
    case "poi":
      return (
        <mesh position={[0, 0.2, 0]} rotation={[0, Math.PI / 4, 0]}>
          <torusGeometry args={[0.22, 0.04, 12, 24]} />
          {mat}
        </mesh>
      );
    case "hazard":
      return (
        <group position={[0, 0.25, 0]}>
          <mesh rotation={[0, 0, Math.PI / 4]}>
            <boxGeometry args={[0.5, 0.06, 0.06]} />
            {mat}
          </mesh>
          <mesh rotation={[0, 0, -Math.PI / 4]}>
            <boxGeometry args={[0.5, 0.06, 0.06]} />
            {mat}
          </mesh>
        </group>
      );
    case "object":
    default:
      return (
        <mesh position={[0, 0.12, 0]}>
          <sphereGeometry args={[0.1, 16, 16]} />
          {mat}
        </mesh>
      );
  }
}

function shapeHeight(t: EntityType): number {
  switch (t) {
    case "soldier": return 0.8;
    case "drone": return 0.5;
    case "poi": return 0.4;
    case "hazard": return 0.5;
    case "object":
    default: return 0.25;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_ALPHA: Record<EntityStatus, number> = {
  active: 1.0,
  stale: 0.55,
  lost: 0.28,
};

function worldToScene(p: Vec3): [number, number, number] {
  // World convention: +x right, +y forward, +z up.
  // Three.js: +x right, +y up, +z toward camera (so forward = -z).
  return [p.x, p.z, -p.y];
}

// Silence unused-import lint for THREE — its types are picked up implicitly.
void THREE;
