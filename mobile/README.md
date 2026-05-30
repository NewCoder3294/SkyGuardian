# `mobile/` — Soldier mobile app (Track 3 · Clients)

React Native. Map view + device location + voice control. The soldier's window
into the world model and the way they talk to the system.

## Stack (per CLAUDE.md)
React Native (pairs with Cactus for on-device voice). Map view + voice control +
device location.

## Responsibilities
- **Subscribe** to the spine and render the same entity set as the dashboard.
- Send `device_location` (its own GPS-free relative position input) for follow-me context.
- Send `intent` — and a **hard STOP/recall button** that is not voice-only.
- Host the **voice** layer (see `mobile/voice/`).

## Interface
- `ws://<laptop>:8000/ws`; import wire types from `../shared/contracts.ts`.
- Sends only `intent` and `device_location`. Never commands the Tello directly.

## Sub-area: voice (Track 3, stage 6 — cut first if time-constrained)
Cactus running Gemma for local STT + intent. Constrain output to the closed
`Command` enum (`follow_me` / `hold` / `recall` / `stop`) — structured intent, not free text.
