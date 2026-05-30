# `frontend/` — Web dashboard (Track 3 · Clients)

Operator map view. Subscribes to the spine; renders the live entity set. Never
duplicates state, never commands the Tello directly (sends intent only).

## Stack (per CLAUDE.md)
Next.js + Tailwind + shadcn. React Flow for any graph view. Motion for transitions.
Dark tactical aesthetic — define design tokens first (layered near-black, one
accent, hairline borders, mono numerals). Avoid generic defaults.

## Interface
- **Subscribes:** `world_snapshot`, `mission_state`, `health` over `ws://<laptop>:8000/ws`.
- **Sends:** `intent` (`follow_me` / `hold` / `recall` / `stop`) — wire to a hard STOP button too.
- Import wire types from `../shared/contracts.ts`.

## Getting started (Track 3 owner)
```bash
cd frontend
npx create-next-app@latest . --ts --tailwind --eslint --app
# then add a WS client that consumes shared/contracts.ts and renders entities on a 2D local-frame map
```
Build against the mock: run the backend with `USE_MOCK=1` (default) — entities
drift around the local frame with no hardware attached.
