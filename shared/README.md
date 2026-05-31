# shared/ — cross-platform contract source (track: spine)

**Responsibility.** Hold the two integration contracts the whole system meets at,
as TypeScript types the web dashboard imports. This is one of **three copies, one
shape** — keep them in sync by hand:

- [`contracts.ts`](./contracts.ts) — TS (this dir) → web dashboard imports it.
- [`../backend/app/contracts.py`](../backend/app/contracts.py) — Pydantic, the
  **source of truth** (validated at the WS boundary).
- [`../mobile/Sources/Contracts.swift`](../mobile/Sources/Contracts.swift) —
  `Codable` mirror for the iOS app.

The Python file owns the shape; the TS and Swift files mirror it. There is no
codegen — a change to one is a manual change to all three.

**Owns**

- ✅ `contracts.ts` — Contract A (Entity) + Contract B (WS protocol) as TS types.
  Server messages: `world_snapshot · mission_state · health · detections ·
  follow_state · buildings_updated`. Client messages: `intent · device_location ·
  entity_report · label_event` (plus the bidirectional `follow_state`, listed under
  `ServerMessage` here since the dashboard only consumes the rebroadcast).

**Interfaces**

- *Imported by:* the web dashboard via `../frontend/src/lib/contracts.ts`, which
  re-exports this file (`export * from "../../../shared/contracts"`). No runtime
  deps; types only.
- *Mirrors:* `contracts.py` (Pydantic) ↔ `Contracts.swift` (Codable).

## Contract A — world model entity

The shared world-model shape. Local frame, metres, no GPS.

- `EntityType` = `poi · hazard · object · soldier · drone`
- `EntityStatus` = `active · stale · lost` (owned by the world model, not producers)
- `EntitySource` = `yolo · slam · follow · manual`
- `Vec3 { x, y, z }` — Python defaults `z` to `0.0`; TS/Swift always carry all three.
- `Entity { id, type, position: Vec3, confidence (0..1), timestamp (unix s),
  source, label?, ttl_s, status }`

Python defaults `confidence=1.0`, `label=None`, `ttl_s=5.0`, `status=active` on
upsert, but the world model always emits a fully-populated entity — so the TS and
Swift mirrors treat `ttl_s` and `status` as required (only `label` is optional).

## Contract B — WebSocket protocol

Closed intent vocabulary (`Command` = `follow_me · hold · recall · stop`) — voice
and UI map onto exactly these, no free text. `stop` / `recall` are always-live and
highest priority, honored from any stage (see `PRIORITY_COMMANDS` in
`contracts.py`).

**server → clients** (`ServerMessage`):

- `world_snapshot { entities[], t }`
- `mission_state { stage, last_error, t }`
- `health { tello, mavic, perception, t }`
- `detections { source, boxes[], image_w, image_h, t }` — most-recent YOLO boxes
  for one video stream. `source` = `"leader"` (recon Mavic) | `"follower"`
  (companion Tello) — it names the stream the boxes belong to so the dashboard
  knows which `<img>` to overlay. Each
  `DetectionBox { label, confidence (0..1), cx, cy, w, h }` is centre + size in
  normalised image-plane units (0..1), so the dashboard overlay scales to any
  source resolution; `image_w/h` are advisory pixel dimensions (Python ints,
  default `0`).
- `follow_state { active, phase, distance_m, bearing_deg, source, target_type?,
  target_label?, t }` — the companion Tello's position **relative to the soldier**,
  for a self-contained follow inset. NOT in the SLAM map frame: the phone's follow
  frame and the Mavic SLAM frame aren't co-registered, so this carries only range +
  bearing, never absolute map coordinates. `active` is true when the drone is
  airborne under follow control; `phase` ∈ `disarmed · searching · confirming ·
  following · lost · manual · stale`; `distance_m` is the soldier → Tello range in
  metres (bounded `0..200`); `bearing_deg` is the Tello bearing relative to the
  soldier (`-360..360`); `source` is advisory (defaults `"phone"`, not trusted for
  any decision). `target_type` ∈ `visual_me · tag` (or `null` when not following)
  says what the lock is on — `visual_me` is the default `ObjectTracker` lock on the
  soldier, `tag` is an AprilTag designating another target; `target_label` is a raw
  id hint only (e.g. the tag id `"7"`, `null` for `visual_me`) — the human display
  string is composed on the dashboard, not sent here. Python rejects NaN/inf
  (`allow_inf_nan=False`) so a malformed payload can't poison the render. This
  message is *bidirectional* — see below.
- `buildings_updated { origin: GeoPoint, radius_m, count, t }` — signal that the
  served OSM buildings layer changed (operator set a new operational area). Clients
  re-GET `/map/buildings` on receipt; the polygon blob is intentionally NOT carried
  over the socket. `GeoPoint { lat, lng }` is a WGS84 pair geo-referencing the
  local map frame's origin.

**clients → server** (`ClientMessage`):

- `intent { command, source, t }` — `source` = `"phone"` | `"dashboard"`.
- `device_location { position, source, t }` — `source` = `"phone"`.
- `follow_state { … }` — same shape as above. The **phone** runs the follow loop
  and publishes this to the laptop; the laptop validates it (`parse_client_message`
  accepts `follow_state`) and rebroadcasts it to the dashboard, so the one message
  flows phone→laptop then laptop→dashboard. The phone only ever sends the five live
  phases; `stale` is server-injected when the phone's stream ages out
  (`_FOLLOW_STALE_S` fail-stale TTL in `server.py`).
- `entity_report { entities[], source, t }` — `source` = `"phone"`. Phone-localized
  entities (operator + drone) in the shared **world** frame (north-up metres, launch
  anchor tag = origin): the phone co-registers against the same launch tag the Mavic
  uses, so these upsert directly into the world model and render on both maps.
  Bounded (`entities` ≤ 8) and NaN/inf-rejecting so a malformed payload can't poison
  the snapshot.
- `label_event { kind, source, label?, corrected_label?, box?, note?, t }` — an
  operator label decision recorded for the data flywheel: `kind` ∈ `confirm ·
  reject · correct` (confirm a true positive, reject a false positive, or correct
  the class). `box` (if present) is `[cx, cy, w, h]` normalized `0..1` (exactly four
  floats).

Each message is discriminated on the `type` field. This contract carries only
**mission-level** intent (`hold` / `recall` / `follow_me` / `stop`), device
location, phone-localized world entities, and operator label events to the backend
— it is *not* the Tello flight-control path. In the current build the phone is the
primary Tello controller and flies the drone directly over the Tello AP
(`192.168.10.1:8889`); the backend's `FollowController` is an alternate controller,
armed one-at-a-time behind a real code interlock (`ArmingLock`,
`backend/app/follow/arming.py` — arming owner `"phone"` disarms every laptop
controller; see CLAUDE.md). So `intent` here is advisory mission state the backend
arbitrates into the world model, not a command relayed to the drone.

## Build notes

- TS source mirrors Python field-for-field. Snake_case wire keys (`ttl_s`,
  `last_error`, `image_w`, `image_h`) are on the wire as-is. The Swift side maps
  the keys it decodes via `CodingKeys` — `ttl_s` on `Entity` and `last_error` on
  `MissionState`. `image_w` / `image_h` belong to `detections`, which has no Swift
  struct (see below), so they are never decoded there.
- **Swift mirror is partial on the server side.** `ServerMessage` in
  `Contracts.swift` decodes `world_snapshot` / `mission_state` / `health` and
  folds everything else (including `detections` and `follow_state`) into
  `.unknown(type)` — there are no Swift `Detections` or inbound `FollowState`
  structs. The phone *produces* follow state and the dashboard renders the inset,
  so the phone never needs to decode it; this is intentional, not drift. If the
  phone ever needs boxes or the rebroadcast follow state, add the struct + a
  matching `case` there.
- **`follow_state` is the one bidirectional message.** Swift mirrors it as
  `FollowStateMessage` (`Encodable` only) — the phone *sends* it (snake_case keys
  `distance_m` / `bearing_deg` / `target_type` / `target_label` on the wire as-is,
  no `CodingKeys` needed). On the Python side `FollowState` is in **both**
  `ServerMessage` and `ClientMessage`, and `parse_client_message` accepts it inbound.
  TS lists it under `ServerMessage` (the dashboard only consumes the rebroadcast).
- **The other phone→server messages are Swift `Encodable`-only too.**
  `EntityReportMessage` (`entity_report`) and `LabelEventMessage` (`label_event`)
  are outbound-only mirrors on the phone (`LabelEventMessage` maps `corrected_label`
  via `CodingKeys`); the phone never decodes them back. `BuildingsUpdated` /
  `GeoPoint` have no Swift struct — like `detections`, they fold into
  `.unknown(type)` on the phone, which only needs the world snapshot + mission/health.
- Validation is one-directional: Python rejects malformed/unknown **client**
  payloads at the WS boundary (`parse_client_message` raises on unknown `type`,
  Pydantic raises on a bad enum/field), so the backend fails loud, not silent.
  There is no symmetric validation of server messages on the TS/Swift side beyond
  the type discriminator.
- When you add/rename a field or enum case, edit **all three** files in the same
  change (and check whether the Swift `ServerMessage` switch needs a new case).

## Notes on tooling

- This is a standalone `.ts` with no `package.json` or `tsconfig` in `shared/`;
  no build step or type-check wiring lives here. Type-checking happens in the
  consuming `frontend/` project.
