# `frontend/` — Operator dashboard (Next.js)

The laptop-side operator view. A subscriber to the brain's WebSocket spine:
renders the live leader (Mavic) feed with YOLO overlays, a top-down local-frame
map over pre-cached OSM building footprints, an on-device intel reasoner
(summary card + operator chat), a threat board, and a health strip. It never
duplicates state and never commands the Tello. The WS hook (`useWorldClient`)
exposes an `intent`-send path (same contract the [iOS app](../mobile/README.md)
uses), but the current shell mounts no Tello controls, so in practice the
dashboard is observe-only. Offline-only; no external dependencies at runtime.

Stack: Next.js 14 (App Router) + React 18 + Tailwind 3 + TypeScript. The 3D map
component (`LocalMap3D`) uses `@react-three/fiber` / `@react-three/drei`
(three.js), but the live shell renders the 2D canvas map (`LocalMap2D`); the 3D
scene and a few other components exist unmounted (see below). No state library —
state is a single WS hook (`useWorldClient`) plus local component state. Tests
run on Vitest.

## How it talks to the brain

Two transports, both pointed at the same laptop host. The host/port is resolved
once and shared so the WS world model and the HTTP video/intel/buildings always
hit the same process:

1. **WebSocket** — one durable connection in `src/lib/useWorldClient.ts`
   (`useWorldClient`). It decodes the `ServerMessage` union from
   [`shared/contracts.ts`](../shared/contracts.ts) (`world_snapshot`,
   `mission_state`, `health`, `detections`) and publishes it to React state.
   Auto-reconnects every 1 s on drop (`RECONNECT_DELAY_MS`). The hook also
   returns a `send(command)` that wraps a `Command`
   (`follow_me | hold | recall | stop`) into an `IntentMessage`
   (`{ type: "intent", command, source: "dashboard", t }`) — but no component
   currently calls it, so the dashboard sends nothing upstream today.
2. **HTTP (MJPEG/JPEG + REST)** — `src/lib/feedUrl.ts#httpFromWs` derives the
   HTTP origin from the WS URL (`ws://` → `http://`, `wss://` → `https://`) so
   video, intel, and REST stay on the same host/port. `page.tsx` derives both
   the leader feed URL and an `apiBase` from the resolved WS URL.
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
   - **Buildings:** the map components fetch `GET /map/buildings` once (a single
     JSON blob of OSM footprints projected into the local frame, pre-cached by
     `scripts/fetch_buildings.py`). A 404 is treated as "no buildings cached"
     and the map still renders.
   - **Intel:** `IntelSummaryCard` polls `GET /intel/summary` (~every 2 s);
     `IntelChat` POSTs `/intel/chat` with the running message history. Both are
     served by the brain's local Ollama reasoner — fully offline.

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

`src/app/page.tsx` is the whole shell. A header (logo lockup + live `Clock`),
the `StatusBar` telemetry strip, and three tabs (persisted to `localStorage`
under `sg.tab`):

- **Feed** — `SourceSelector` toolbar over either the live `VideoFeed` or the
  playback `VideoPlayer`, with a `ConsolePanel` detection log on the side.
- **Map** — `LocalMap2D`, a pan/zoom top-down canvas of the local frame (launch
  point at origin, north up, metric grid + scale bar). It draws the cached OSM
  building footprints and operational world-model entities; SLAM landmark points
  (`lm_*` ids) are filtered out via `lib/entities.ts`. A compact
  `IntelSummaryCard` floats in the lower-left corner.
- **Intel** — a full `IntelSummaryCard` (latest on-device assessment + threat
  level), the `IntelPanel` threat board (one row per detected class with count,
  average confidence, and time-since-last-seen), and an `IntelChat` operator
  Q&A panel docked on the right (≥md).

`ThreatAlert` floats over every tab and fires when a weapon-class label
(`lib/threats.ts`) is in a recent frame; it auto-clears on a clean frame.

Both live and playback modes feed the same components: in file mode the page
synthesises the same `Health`/`detections`/entity shapes from the playback JSON
(`lib/playback.ts`) so downstream components need no special-casing.

### Components (`src/components/`)
Mounted by `page.tsx`: `Clock`, `StatusBar`, `SourceSelector`, `VideoFeed`,
`VideoPlayer`, `ConsolePanel`, `IntelSummaryCard`, `IntelPanel`, `IntelChat`,
`LocalMap2D`, `ThreatAlert`.
Present but **not** currently mounted: `LocalMap3D` (+ its `Buildings` R3F
meshes), `LocalMap` (older 2D canvas), `EntityList`.

### Lib (`src/lib/`)
`contracts.ts` (re-exports the shared wire types), `wsConfig.ts`
(`DEFAULT_WS_URL` + `resolveWsUrl`), `useWorldClient.ts` (WS hook), `feedUrl.ts`
(`ws://` → `http://` derivation), `playback.ts` (clip JSON types + frame
lookup), `entities.ts` (landmark filter), `projection.ts` (`MapProjection`,
mirror of the mobile/Swift projection — used by the unmounted `LocalMap`),
`status.ts` (binary ONLINE/OFFLINE tiers), `threats.ts` (threat class set).
Vitest specs: `feedUrl.test.ts`, `wsConfig.test.ts`.

## Design tokens

Light tactical (C2) theme. Tokens live in `src/app/globals.css` as oklch CSS
vars — warm parchment base (`--bg`), near-white panel surfaces, deep olive ink
text, hairline borders — and are surfaced to Tailwind via `tailwind.config.ts`
(`bg`, `surface`, `surface-elevated`, `border`/`border-strong`, `text`/`-muted`/
`-dim`, `accent`, `ok`/`warn`/`fail`, `cta`, `shadow-glow-cyan`/`card`, etc.).
Colour discipline (do not break): **green** (`--ok`) = a system is doing its
job, **amber** (`--accent`) = telemetry / values / reticles, **red** (`--fail`)
= threat or a lost channel and nothing else. Hard corners (the global
`borderRadius` collapses to 0–2 px; only LED dots stay `full`). `.tac-corners`
draws the C2 framing brackets; `.hud-grid` the survey graticule. `StatusBar`
treats every channel as strictly binary — ONLINE or OFFLINE, no middle tier
(`lib/status.ts`).

## Run

```bash
cd frontend
npm install
npm run dev                                            # http://localhost:3001
# remote/LAN brain:
NEXT_PUBLIC_WS_URL=ws://192.168.10.1:8000/ws npm run dev
```

Dev/start ports are pinned to **3001** in `package.json` so the dashboard
doesn't collide with anything else on 3000. Scripts:

- `npm run dev` — `next dev -p 3001`
- `npm run build` — `next build`
- `npm start` — `next start -p 3001` (serves the production build)
- `npm run lint` — `next lint`
- `npm test` — `vitest run` (one-shot); `npm run test:watch` for watch mode

Start the brain first (`cd backend && ./run.sh`, binds `0.0.0.0:8000`); the
dashboard reconnects on its own once the WS is reachable. The intel summary/chat
panels degrade gracefully if the brain's local Ollama reasoner is unavailable.
