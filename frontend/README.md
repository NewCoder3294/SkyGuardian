# `frontend/` — Operator dashboard (Next.js)

The laptop-side operator view. A subscriber to the brain's WebSocket
spine: renders the live leader (Mavic) feed with YOLO overlays, the local-frame
map, a threat board, and a health strip. It never duplicates state and never
commands the Tello. The WS hook (`useWorldClient`) exposes an `intent`-send path
(same contract the [iOS app](../mobile/README.md) uses), but the current shell
mounts no Tello controls, so in practice the dashboard is observe-only.
Offline-only; no external dependencies at runtime.

Stack: Next.js 14 (App Router) + React 18 + Tailwind 3 + TypeScript. The 3D map
uses `@react-three/fiber` / `@react-three/drei` (three.js). No state library —
state is a single WS hook (`useWorldClient`) plus local component state.

## How it talks to the brain

Two transports, both pointed at the same laptop host:

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
   HTTP origin from the WS URL so video and REST stay on the same host/port.
   - Live leader feed: `VideoFeed` polls `GET /video/leader.jpg` as single
     frames at ~10 Hz (Blob → object URL), *not* `multipart/x-mixed-replace` —
     a polled JPEG lets the tab settle between frames instead of spinning
     forever. YOLO boxes from the `detections` WS layer are drawn on an overlay
     canvas, letterbox-corrected.
   - Source control: `SourceSelector` polls `GET /video/source` and POSTs
     `/video/source/rtmp` or `/video/source/upload` (multipart) to switch
     between the live RTMP pipeline and an uploaded clip.
   - Playback: for an uploaded clip, `VideoPlayer` plays
     `GET /video/file/{name}` natively and overlays boxes from a sidecar
     `GET /video/detections/{name}` JSON, keyed by playhead time.

### WebSocket URL — important

The dashboard defaults to `ws://localhost:8001/ws`
(`DEFAULT_WS` in `src/app/page.tsx`). The backend (`backend/run.sh`) binds
`0.0.0.0:8000`. So out of the box you **must** point the dashboard at the brain
explicitly via the `NEXT_PUBLIC_WS_URL` env var — e.g. the brain on this laptop:

```bash
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws npm run dev
```

On a LAN, use the brain's address (`ws://<laptop-ip>:8000/ws`); all derived
HTTP/MJPEG URLs follow the same host automatically.

## Layout

`src/app/page.tsx` is the whole shell. A header (logo + live `Clock`), the
`StatusBar` telemetry strip, and three tabs (persisted to `localStorage`):

- **Feed** — `SourceSelector` toolbar over either the live `VideoFeed` or the
  playback `VideoPlayer`, with a `ConsolePanel` detection log on the side.
- **Map** — `LocalMap3D`, an orbitable three.js scene of the local frame
  (launch point at origin). Operational entities only; SLAM landmark points
  (`lm_*` ids) are filtered out via `lib/entities.ts`.
- **Intel** — `IntelPanel` threat board: one row per detected class with
  count, average confidence, and time-since-last-seen.

`ThreatAlert` floats over every tab and fires when a weapon-class label (see
`lib/threats.ts`) is in a recent frame; it auto-clears on a clean frame.

Both live and playback modes feed the same components: in file mode the page
synthesises the same `Health`/`detections`/entity shapes from the playback JSON
(`lib/playback.ts`) so downstream components need no special-casing.

### Components (`src/components/`)
`Clock`, `StatusBar`, `SourceSelector`, `VideoFeed`, `VideoPlayer`,
`ConsolePanel`, `IntelPanel`, `ThreatAlert`, `LocalMap3D`. `LocalMap`
(2D canvas) and `EntityList` exist but are not currently mounted by `page.tsx`.

### Lib (`src/lib/`)
`contracts.ts` (re-exports the shared wire types), `useWorldClient.ts` (WS
hook), `feedUrl.ts` (`ws://` → `http://` derivation), `playback.ts` (clip
JSON types + frame lookup), `entities.ts` (landmark filter), `projection.ts`
(`MapProjection`, mirror of the mobile/Swift projection), `status.ts`
(binary ONLINE/OFFLINE tiers), `threats.ts` (threat class set).

## Design tokens

Dark tactical theme. Tokens live in `src/app/globals.css` (CSS vars: deep-navy
`--bg #06121f`, cyan `--accent #22d3ee`, hairline borders) and are surfaced to
Tailwind via `tailwind.config.ts` (`bg`, `surface`, `accent`, `ok`/`fail`,
`shadow-glow-cyan`, etc.). Status is strictly binary — ONLINE (cyan) or OFFLINE
(red), no intermediate tier.

## Run

```bash
cd frontend
npm install
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws npm run dev   # dev on http://localhost:3001
```

The dev/start ports are pinned to **3001** in `package.json` so the dashboard
doesn't collide with anything else on 3000. Scripts:

- `npm run dev` — `next dev -p 3001`
- `npm run build` — `next build`
- `npm start` — `next start -p 3001` (serves the production build)
- `npm run lint` — `next lint`

Start the brain first (`cd backend && ./run.sh`); the dashboard reconnects on
its own once the WS is reachable.
