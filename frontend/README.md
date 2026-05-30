# `frontend/` — Web dashboard (Track 3 · Clients)

**Status: WIP.** This directory contains the Next.js operator dashboard.

**Responsibility:** operator map view. Subscribes to the spine; renders the live
entity set. Never duplicates state, never commands the Tello directly (sends
intent only). Mirrors what the [iOS app](../mobile/README.md) already does, on
the laptop.

## Stack (per CLAUDE.md)
Next.js + Tailwind. The dashboard renders the live feed, detection overlay,
health/status strip, local map, 3D map, entity list, intel panel, console, and
threat alert surface.

## Interface (Contract B)
- **Subscribes:** `world_snapshot`, `mission_state`, `health`, `detections` over `ws://<laptop>:8001/ws`.
- **Sends:** `intent` (`follow_me` / `hold` / `recall` / `stop`) — wire to a hard STOP button too.
- Import wire types from [`../shared/contracts.ts`](../shared/contracts.ts) (`Entity`, `Command`, the WS message union).

## Getting started
```bash
cd frontend
npm install
npm run dev
```
