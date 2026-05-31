# `frontend/` — Marketing landing + operator dashboard (Next.js)

Two routes in one Next.js app:

- **`/`** (`src/app/page.tsx`) — the SkyGuardian **marketing landing page**.
  Image-led, observe-nothing: a fixed nav + hero over `next/image` photos
  (`/hero-drone-city.png`), a YouTube demo embed, and
  problem/capability/operator-view/missions/markets/roadmap/team/CTA sections.
  Decorative C2 effects only (`hud-grid-drift`, `scan-beam`, `signal-dot`,
  `node-pulse` — defined in `globals.css`); no WS, no video stream, no live
  data. The header carries a Bow-Capital hackathon credit, a "Request demo" link
  (`https://strvx.com/book`), and an "Operator" link; the hero and CTA carry
  "Open operator UI" links. Every operator link points at `/operator`.
- **`/operator`** (`src/app/operator/page.tsx`) — the laptop-side **operator
  dashboard** (this used to live at `/`). A subscriber to the brain's WebSocket
  spine: renders the live leader (Mavic) feed with YOLO overlays, a top-down (2D)
  or three.js (3D) local-frame map over pre-cached OSM building footprints, an
  on-device intel reasoner (summary card + operator chat), a threat board, a
  health strip, a soldier-centred follow radar (`FollowInset`), and a Foundry
  mission-data view. It never duplicates state and never commands the Tello. The
  WS hook (`useWorldClient`) exposes an `intent`-send path (same contract the
  [iOS app](../mobile/README.md) uses), but the dashboard mounts no Tello
  controls, so in practice it is observe-only. The world model is offline-only;
  the optional Foundry "Data" tab is the one surface that can reach out (to a
  Palantir Foundry ontology, server-side only).

**To reach the dashboard**, navigate to `/operator` (the root `/` is now the
landing page) — e.g. `http://localhost:3000/operator`, or click "Operator" /
"Open operator UI" in the landing header/hero/CTA.

Stack: Next.js 14 (App Router) + React 18 + Tailwind 3 + TypeScript. The 3D map
component (`LocalMap3D`) uses `@react-three/fiber` / `@react-three/drei`
(three.js); the operator Map tab can toggle between `LocalMap2D` and
`LocalMap3D` and between `outdoor`/`indoor` environments (both persisted to
`localStorage`). A few components exist unmounted (see below). No state library —
state is a single WS hook (`useWorldClient`) plus local component state. Tests
run on Vitest.

## How it talks to the brain

Two transports, both pointed at the same laptop host. The host/port is resolved
once and shared so the WS world model and the HTTP video/intel/buildings always
hit the same process:

1. **WebSocket** — one durable connection in `src/lib/useWorldClient.ts`
   (`useWorldClient`). It decodes the `ServerMessage` union from
   [`shared/contracts.ts`](../shared/contracts.ts) (`world_snapshot`,
   `mission_state`, `health`, `detections`, `follow_state`, `buildings_updated`)
   and publishes it to React state — including a `followState: FollowState | null`
   that drives the `FollowInset` follow radar on the Map tab. A
   `buildings_updated` frame bumps a `buildingsVersion` counter so the map
   components re-fetch `/map/buildings` (e.g. after the operator re-anchors the
   buildings layer). Auto-reconnects every 1 s on drop (`RECONNECT_DELAY_MS`).
   The hook also returns a `send(command)` that wraps a `Command`
   (`follow_me | hold | recall | stop`) into an `IntentMessage`
   (`{ type: "intent", command, source: "dashboard", t }`) — but no component
   currently calls it, so the dashboard sends nothing upstream today.
2. **HTTP (MJPEG/JPEG + REST)** — `src/lib/feedUrl.ts#httpFromWs` derives the
   HTTP origin from the WS URL (`ws://` → `http://`, `wss://` → `https://`) so
   video, intel, and REST stay on the same host/port. `operator/page.tsx` derives
   both the leader feed URL and an `apiBase` from the resolved WS URL.
   - **Live leader feed:** `VideoFeed` polls `GET /video/leader.jpg` as single
     frames at ~10 Hz (Blob → object URL), *not* `multipart/x-mixed-replace` —
     a polled JPEG lets the tab settle between frames instead of spinning
     forever. YOLO boxes from the `detections` WS layer are drawn on an overlay
     canvas, letterbox-corrected; threat-class labels (`lib/threats.ts`) lock
     to red, everything else amber.
   - **Source control:** `SourceSelector` polls `GET /video/source` and POSTs
     `/video/source/rtmp` or `/video/source/upload` (multipart) to switch
     between the live RTMP pipeline and an uploaded clip. When armed for RTMP
     but not yet streaming it surfaces the publish URL (from the source's
     `rtmp_default`) with a copy button.
   - **Playback:** for an uploaded clip, `VideoPlayer` plays
     `GET /video/file/{name}` natively and overlays boxes from a sidecar
     `GET /video/detections/{name}` JSON, keyed by playhead time.
   - **Buildings:** the map components fetch `GET /map/buildings` (a single
     JSON blob of OSM footprints projected into the local frame, pre-cached by
     `scripts/fetch_buildings.py`); they re-fetch whenever `buildingsVersion`
     bumps. A 404 is treated as "no buildings cached" and the map still renders.
   - **Operational area:** on the Map tab, outdoors, `OperationalArea` POSTs
     `/map/area` (`{ lat, lng, radius_m }`, `radius_m` defaults to 400) to
     re-anchor the buildings layer on a new lat/long. This is a **pre-mission
     staging** action that hits the internet (OSM Overpass) at fetch time only;
     a 503 (no internet) surfaces as "No internet: pre-mission only". It sends no
     auth header (same as `SourceSelector`).
   - **Intel:** `IntelSummaryCard` polls `GET /intel/summary` (~every 2 s);
     `IntelChat` POSTs `/intel/chat` with the running message history. Both are
     served by the brain's local Ollama reasoner — fully offline.
   - **Foundry data (optional):** the "Data" tab and the `/data` deep link both
     render `FoundryDataView`, which GETs the Next.js route `/api/foundry`
     (server-side, reads `CaptureMission` + `DetectionClass` objects from a
     Palantir Foundry ontology). Its "Ask the Data" box POSTs `/api/foundry/ask`,
     which executes a published AIP query function (`FOUNDRY_AIP_FUNCTION`) when
     configured; otherwise the client falls back to a deterministic local
     responder (`lib/foundryData.ts` `answerData`). `FOUNDRY_TOKEN` stays
     server-side and never reaches the client bundle. Not configured → the view
     prints a setup card; this is the only surface that touches the network at
     runtime, and the rest of the dashboard works without it.

### WebSocket URL

The dashboard defaults to `ws://localhost:8000/ws` (`DEFAULT_WS_URL` in
`src/lib/wsConfig.ts`), which matches the backend bind (`backend/run.sh` →
`0.0.0.0:8000`) and the mobile client's default. So out of the box, with the
brain on the same laptop, **no configuration is needed**.

`NEXT_PUBLIC_WS_URL` overrides the default for a remote/on-LAN brain. An
override only wins when it's a non-empty, non-whitespace string (`resolveWsUrl`),
so a blank env var can never produce an invalid `ws://` target:

```bash
NEXT_PUBLIC_WS_URL=ws://192.168.10.1:8000/ws npm run dev
```

All derived HTTP/MJPEG/intel URLs follow the same host/port automatically. This
single-origin invariant is pinned by `feedUrl.test.ts` and `wsConfig.test.ts`.

## Layout

`src/app/operator/page.tsx` is the whole dashboard shell (`/operator`). The
shell wears the monochrome `operator-theme` class (see Design tokens). A header
(logo lockup + live `Clock`), the `StatusBar` telemetry strip, and four tabs
(persisted to `localStorage` under `sg.tab`):

- **Feed** — `SourceSelector` toolbar over either the live `VideoFeed` or the
  playback `VideoPlayer`, with a `ConsolePanel` detection log on the side.
- **Map** — a `LocalMap2D` / `LocalMap3D` pair toggled by a `MapViewToggle`
  (view persisted under `sg.mapView`): a pan/zoom top-down canvas (2D) or a
  three.js scene (3D) of the local frame (launch point at origin, north up,
  metric grid + scale bar). Both draw the cached OSM building footprints and
  operational world-model entities; SLAM landmark points (`lm_*` ids) are
  filtered out via `lib/entities.ts`. The designated recon target (the reserved
  `designated_target` id) gets a red targeting reticle on both maps. An
  `EnvironmentToggle` (persisted under `sg.environment`) switches `outdoor`
  (buildings shown, the `OperationalArea` re-anchor form visible) vs `indoor`
  (buildings + ops-area hidden — the OSM footprints are city lat/lon polygons
  with no relation to an indoor scene). A compact `IntelSummaryCard` floats in
  the lower-left corner, and a `FollowInset` follow radar floats in the
  upper-right whenever `followState` is present.
- **Intel** — a full `IntelSummaryCard` (latest on-device assessment + threat
  level), the `IntelPanel` threat board (one row per detected class with count,
  average confidence, and time-since-last-seen), and an `IntelChat` operator
  Q&A panel docked on the right (≥md).
- **Data** — `FoundryDataView`: a read-only Palantir Foundry mission-data view
  (mission cards, detections-by-class bars, count-up stat tiles, and the "Ask
  the Data" box). Reads `/api/foundry`; renders a "Not Configured" card until
  the `FOUNDRY_*` env is set. The same view is also reachable standalone at
  `/data` (`src/app/data/page.tsx`).

`ThreatAlert` floats over every tab and fires when a weapon-class label
(`lib/threats.ts`) is in a recent frame; it auto-clears on a clean frame.

`FollowInset` (`src/components/FollowInset.tsx`) is a small **soldier-centred
radar** on the Map tab. The soldier sits at centre (facing straight up = bearing
0°, +deg clockwise); the companion Tello plots as a range/bearing dot on an
adaptive ring scale, fed by the `followState.distance_m` / `bearing_deg` from the
`follow_state` WS layer. It is deliberately **not** co-registered with the SLAM
map — the phone's follow frame and the Mavic SLAM frame don't share a reference —
so it stands alone, and renders nothing until the phone has reported. It also
shows a **follow-target badge** composed by `followTargetLabel`
(`lib/followTarget.ts`) from `FollowState.target_type` / `target_label`: a
`visual_me` lock reads `ME (visual)`, a tag reads `TAG #<id>` (or `TAG` with no
id), and nothing renders when no target is set. Phase colouring uses the C2
class tokens: `following` → `text-ok`; `manual` and `confirming` →
`text-accent`; `lost` or `stale` → `text-fail`. Under the dashboard's monochrome
`operator-theme`, `--ok`/`--accent` resolve to ink and only `--fail` stays the
signal-red hue. `stale` specifically means the phone's link aged out (the
brain's `_FOLLOW_STALE_S` fail-stale TTL fired), so the inset labels it "link
lost" — a frozen reading can't be mistaken for a live follow.

Both live and playback modes feed the same components: in file mode the page
synthesises the same `Health`/`detections`/entity shapes from the playback JSON
(`lib/playback.ts`) so downstream components need no special-casing.

### Components (`src/components/`)
Mounted by `operator/page.tsx`: `Clock`, `StatusBar`, `SourceSelector`,
`VideoFeed`, `VideoPlayer`, `ConsolePanel`, `IntelSummaryCard`, `IntelPanel`,
`IntelChat`, `LocalMap2D`, `LocalMap3D` (Map tab 2D/3D toggle; `LocalMap3D`
renders its `Buildings` R3F meshes), `OperationalArea` (Map tab, outdoor),
`FollowInset`, `ThreatAlert`, `FoundryDataView` (Data tab; also the `/data`
deep link). Present but **not** currently mounted: `LocalMap` (older 2D canvas),
`EntityList`. (The landing page at `src/app/page.tsx` uses no `src/components/` —
its visuals are `next/image` photos plus CSS effect helpers from `globals.css`.)

### Lib (`src/lib/`)
`contracts.ts` (re-exports the shared wire types), `wsConfig.ts`
(`DEFAULT_WS_URL` + `resolveWsUrl`), `useWorldClient.ts` (WS hook), `feedUrl.ts`
(`ws://` → `http://` derivation), `playback.ts` (clip JSON types + frame
lookup), `entities.ts` (landmark filter + `designated_target` helpers),
`trails.ts` (`TrailStore` movement-trail accumulator, used by `LocalMap2D`),
`followTarget.ts` (`followTargetLabel` ME/TAG badge helper), `projection.ts`
(`MapProjection`, mirror of the mobile/Swift projection — used by the unmounted
`LocalMap`), `status.ts` (binary ONLINE/OFFLINE tiers), `threats.ts` (threat
class set), `foundryData.ts` (client types + the deterministic local query
responder), `foundryServer.ts` (server-only Foundry fetch + AIP context
helpers). Vitest specs: `feedUrl.test.ts`, `wsConfig.test.ts`,
`useWorldClient.test.ts`, `followTarget.test.ts`, `trails.test.ts`,
`foundryServer.test.ts`, plus component specs `IntelPanel.test.tsx` and
`OperationalArea.test.tsx`.

## Design tokens

Two scoped light-tactical (C2) themes share one token set, both as oklch CSS
vars in `src/app/globals.css` and surfaced to Tailwind via `tailwind.config.ts`
(`bg`, `surface`, `surface-elevated`, `border`/`border-strong`, `text`/`-muted`/
`-dim`, `accent`, `ok`/`warn`/`fail`, `cta`, `shadow-glow-cyan`/`card`, etc.).

- **`:root` (landing page)** — warm parchment base (`--bg`), near-white panel
  surfaces, deep olive ink text, hairline borders. Colour discipline: **green**
  (`--ok`) = a system doing its job, **amber** (`--accent`) = telemetry / values
  / reticles, **red** (`--fail`) = threat or a lost channel and nothing else.
- **`.operator-theme` (the `/operator` dashboard shell)** — overrides the same
  vars to a strict monochrome black-and-white on light paper. Status reads by
  ink value + pattern + shape + motion; `--ok`/`--warn`/`--accent`/`--cta` all
  resolve to ink/grey, and **`--fail` (signal red) is the only hue**, reserved
  strictly for threats.

Hard corners (the global `borderRadius` collapses to 0–2 px; only LED dots stay
`full`). `.tac-corners` draws the C2 framing brackets; `.hud-grid` /
`.hud-grid-drift` the survey graticule; `.scan-beam` and the `signal-dot` /
`node-pulse` helpers add the landing-page motion. `StatusBar` treats every
channel as strictly binary — ONLINE or OFFLINE, no middle tier (`lib/status.ts`).

## Run

```bash
cd frontend
npm install
npm run dev                                  # landing: http://localhost:3000
                                             # dashboard: http://localhost:3000/operator
# remote/LAN brain:
NEXT_PUBLIC_WS_URL=ws://192.168.10.1:8000/ws npm run dev
```

`http://localhost:3000/` serves the marketing landing page; the operator
dashboard is at **`/operator`**. Dev/start ports are pinned to **3000** in
`package.json` so the app doesn't collide with anything else on 3000. Scripts:

- `npm run dev` — `next dev -p 3000`
- `npm run build` — `next build`
- `npm start` — `next start -p 3000` (serves the production build)
- `npm run lint` — `next lint`
- `npm test` — `vitest run` (one-shot); `npm run test:watch` for watch mode

Start the brain first (`cd backend && ./run.sh`, binds `0.0.0.0:8000`); the
dashboard reconnects on its own once the WS is reachable. The intel summary/chat
panels degrade gracefully if the brain's local Ollama reasoner is unavailable.

The "Data" tab is optional: set `FOUNDRY_HOST`, `FOUNDRY_TOKEN`, and
`FOUNDRY_ONTOLOGY_RID` in `frontend/.env.local` to read mission data from a
Palantir Foundry ontology (and `FOUNDRY_AIP_FUNCTION` for the AIP-backed "Ask
the Data" box). These are read server-side only and never reach the client
bundle; unset, the tab shows a "Not Configured" card and the rest of the
dashboard is unaffected.
