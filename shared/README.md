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
codegen — a change to one is a manual change to all three. See the spine section
in [`../README.md`](../README.md#the-spine--two-contracts-everything-meets-at).

**Owns**

- ✅ `contracts.ts` — Contract A (Entity) + Contract B (WS protocol) as TS types.

**Interfaces**

- *Imported by:* the web dashboard (⬜ not started). No runtime deps; types only.
- *Mirrors:* `contracts.py` (Pydantic) ↔ `Contracts.swift` (Codable).

## Contract A — world model entity

The shared world-model shape. Local frame, metres, no GPS.

- `EntityType` = `poi · hazard · object · soldier · drone`
- `EntityStatus` = `active · stale · lost` (owned by the world model, not producers)
- `EntitySource` = `yolo · slam · follow · manual`
- `Entity { id, type, position: Vec3, confidence (0..1), timestamp (unix s),
  source, label?, ttl_s, status }`
- `Vec3 { x, y, z }`

## Contract B — WebSocket protocol

Closed intent vocabulary (`Command` = `follow_me · hold · recall · stop`) — voice
and UI map onto exactly these, no free text. `stop` / `recall` are always-live and
highest priority (see `PRIORITY_COMMANDS` in `contracts.py`).

- **server → clients** (`ServerMessage`): `world_snapshot { entities[], t }` ·
  `mission_state { stage, last_error, t }` · `health { tello, mavic, perception, t }`
- **clients → server** (`ClientMessage`): `intent { command, source, t }` ·
  `device_location { position, source, t }`

Each message is discriminated on the `type` field. Clients **never** command the
Tello directly — they send `intent`; the backend state machine arbitrates.

## Build notes

- TS source mirrors Python field-for-field. Snake_case wire keys (`ttl_s`,
  `last_error`) are preserved; the Swift side maps them via `CodingKeys`.
- The TS `Entity.status` / `ttl_s` are present here even though the Python
  producer defaults them — the world model always emits a fully-populated entity.
- When you add/rename a field or enum case, edit **all three** files in the same
  change. Python validation will reject any drifted client payload at the WS
  boundary (`parse_client_message`), so the backend fails loud, not silent.

## Planned

- ⬜ Web dashboard consuming these types (`../README.md` lists it not started).
- ⬜ No build step / type-check wiring lives here yet; this is a standalone `.ts`
  with no `package.json` or `tsconfig` in `shared/`.
