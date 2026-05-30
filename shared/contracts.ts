// Shared integration contracts — TS mirror of backend/app/contracts.py.
// Both the web dashboard and the mobile app import these types so all three
// subsystems agree on the wire format. Keep in sync with the Python source of truth.

// ---------------------------------------------------------------------------
// Contract A — World model entity
// ---------------------------------------------------------------------------

export type EntityType = "poi" | "hazard" | "object" | "soldier" | "drone";
export type EntityStatus = "active" | "stale" | "lost";
export type EntitySource = "yolo" | "slam" | "follow" | "manual";

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface Entity {
  id: string;
  type: EntityType;
  position: Vec3;
  confidence: number; // 0..1
  timestamp: number; // unix seconds
  source: EntitySource;
  label?: string | null;
  ttl_s: number;
  status: EntityStatus;
}

// ---------------------------------------------------------------------------
// Contract B — WebSocket messages
// ---------------------------------------------------------------------------

// Closed intent vocabulary. Voice + UI map onto exactly these. No free text.
export type Command = "follow_me" | "hold" | "recall" | "stop";

// --- server -> clients ---
export interface WorldSnapshot {
  type: "world_snapshot";
  entities: Entity[];
  t: number;
}

export interface MissionState {
  type: "mission_state";
  stage: string;
  last_error: string | null;
  t: number;
}

export interface Health {
  type: "health";
  tello: string;
  mavic: string;
  perception: string;
  t: number;
}

export interface DetectionBox {
  label: string;
  confidence: number; // 0..1
  cx: number;         // normalised image-plane centre (0..1)
  cy: number;
  w: number;          // normalised box width (0..1)
  h: number;
}

export interface Detections {
  type: "detections";
  source: string;     // "leader" (recon Mavic) | "follower" (companion Tello)
  boxes: DetectionBox[];
  image_w: number;
  image_h: number;
  t: number;
}

/**
 * Relative follow geometry between the soldier and the companion Tello. Reported
 * by the phone (which runs the follow loop) and rebroadcast by the laptop. NOT in
 * the SLAM map frame — range + bearing only, for a self-contained follow inset.
 */
export interface FollowState {
  type: "follow_state";
  active: boolean;       // drone airborne under follow control
  phase: string;         // disarmed | searching | confirming | following | lost | manual | stale ("stale" is server-injected)
  distance_m: number;    // soldier → Tello range, metres
  bearing_deg: number;   // Tello bearing relative to the soldier, degrees
  t: number;
}

export type ServerMessage =
  | WorldSnapshot
  | MissionState
  | Health
  | Detections
  | FollowState;

// --- clients -> server ---
export interface IntentMessage {
  type: "intent";
  command: Command;
  source: "phone" | "dashboard";
  t: number;
}

export interface DeviceLocation {
  type: "device_location";
  position: Vec3;
  source: "phone";
  t: number;
}

export type ClientMessage = IntentMessage | DeviceLocation;
