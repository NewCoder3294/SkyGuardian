# `frontend/` — Web dashboard (Track 3 · Clients)

**Status: ⬜ not started.** This dir holds only this README — no Next.js app yet.
See the [root status table](../README.md#status).

**Responsibility:** operator map view. Subscribes to the spine; renders the live
entity set. Never duplicates state, never commands the Tello directly (sends
intent only). Mirrors what the [iOS app](../mobile/README.md) already does, on
the laptop.

## Stack (per CLAUDE.md)
Next.js + Tailwind + shadcn. React Flow for any graph view. Motion for transitions.
Dark tactical aesthetic — define design tokens first (layered near-black, one
accent, hairline borders, mono numerals). Avoid generic defaults.

## Interface (Contract B)
- **Subscribes:** `world_snapshot`, `mission_state`, `health` over `ws://<laptop>:8011/ws`.
- **Sends:** `intent` (`follow_me` / `hold` / `recall` / `stop`) — wire to a hard STOP button too.
- Import wire types from [`../shared/contracts.ts`](../shared/contracts.ts) (`Entity`, `Command`, the WS message union).

## Getting started (Track 3 owner)
```bash
cd frontend
npx create-next-app@latest . --ts --tailwind --eslint --app
# then add a WS client that consumes shared/contracts.ts and renders entities on a 2D local-frame map
```
Build against the mock: run the backend with `USE_MOCK=1` (default) — entities
drift around the local frame with no hardware attached.
