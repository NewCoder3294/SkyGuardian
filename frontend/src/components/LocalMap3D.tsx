"use client";

import { useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { Grid, Html, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { Entity, EntityStatus, EntityType, Vec3 } from "@/lib/contracts";

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
}

export function LocalMap3D({
  entities,
  landmarks = [],
  spanMeters = 20,
  showLandmarks = false,
}: Props) {
  return (
    <div className="relative h-full w-full bg-bg">
      <Canvas
        camera={{ position: [spanMeters * 0.8, spanMeters * 0.8, spanMeters * 0.8], fov: 45 }}
        style={{ background: "#ffffff" }}
        dpr={[1, 2]}
      >
        <ambientLight intensity={0.55} />
        <directionalLight position={[10, 20, 10]} intensity={0.35} />
        <directionalLight position={[-10, 15, -10]} intensity={0.2} />

        <SceneFloor span={spanMeters} />
        <OriginMarker />

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
          maxDistance={spanMeters * 4}
          target={[0, 0, 0]}
        />
      </Canvas>
      <ViewLegend />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scene primitives
// ---------------------------------------------------------------------------

function SceneFloor({ span }: { span: number }) {
  return (
    <>
      <Grid
        args={[span * 4, span * 4]}
        position={[0, 0, 0]}
        cellSize={1}
        cellThickness={0.7}
        cellColor="#dcdcdc"
        sectionSize={5}
        sectionThickness={1.1}
        sectionColor="#b0b0b0"
        fadeDistance={span * 3}
        fadeStrength={1}
        followCamera={false}
        infiniteGrid
      />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.001, 0]} receiveShadow>
        <planeGeometry args={[span * 8, span * 8]} />
        <meshBasicMaterial color="#ffffff" transparent opacity={0} />
      </mesh>
    </>
  );
}

function OriginMarker() {
  return (
    <group position={[0, 0.01, 0]}>
      <mesh>
        <cylinderGeometry args={[0.08, 0.08, 0.02, 24]} />
        <meshBasicMaterial color="#0a0a0a" />
      </mesh>
      <Html position={[0, 0.45, 0]} center distanceFactor={8} zIndexRange={[0, 0]}>
        <div className="pointer-events-none whitespace-nowrap font-mono text-[10px] uppercase tracking-[0.3em] text-text">
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

  return (
    <group position={pos}>
      {renderShape(entity.type, alpha)}
      <Html
        position={[0, shapeHeight(entity.type) + 0.3, 0]}
        center
        distanceFactor={8}
        zIndexRange={[0, 0]}
      >
        <div
          className="pointer-events-none whitespace-nowrap rounded-sm border border-border bg-white px-1 py-0.5 font-mono text-[10px] uppercase tracking-wider text-text"
          style={{ opacity: alpha }}
        >
          {label}
        </div>
      </Html>
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
      <pointsMaterial color="#525252" size={0.06} sizeAttenuation transparent opacity={0.5} />
    </points>
  );
}

function ViewLegend() {
  return (
    <div className="pointer-events-none absolute left-3 top-3 space-y-0.5 font-mono text-[10px] uppercase tracking-widest text-text-dim">
      <div>Local frame · 3D</div>
      <div>Drag · orbit · scroll zoom</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shape per entity type
// ---------------------------------------------------------------------------

function renderShape(type: EntityType, alpha: number): JSX.Element {
  const mat = (
    <meshStandardMaterial
      color="#0a0a0a"
      transparent
      opacity={alpha}
      roughness={0.6}
      metalness={0.05}
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
