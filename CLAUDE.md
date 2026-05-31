# CLAUDE.md — SkyGuardian (Recon & Companion Drone System)

## Mission

An offline-first situational awareness system for dismounted soldiers.

- A **manned recon Mavic** surveys an area, detects relevant points, and builds a live map using SLAM.
- A **Tello companion drone** follows the soldier (buddy/pet) as a mobile sensor.
- A **mobile app** lets soldiers read the map and talk to the Tello, so they understand a space before moving into it.

Built for environments with no connectivity. Everything runs locally. No cloud, no internet, no GPS.

## Hard constraints (do not violate)

- **Offline-first.** No cloud calls, no internet dependency, no external APIs at runtime. All models and services run on local hardware.
- **No GPS.** Positioning is relative, anchored to landmarks plus a launch point.
- **This is recon and situational awareness only.** No engagement, no targeting, no attack behavior. Out of scope entirely.
- **Single plain Tello** (AP mode, no station mode, no swarm).
- **One Tello controller armed at a time.** The Tello is commanded directly by whichever controller is armed — normally the phone (on-device follow loop + voice). The laptop backend ships an alternate controller (FollowController) plus a backend approach loop; never arm both against the same Tello at once. A **code interlock now exists** (`backend/app/follow/arming.py` `ArmingLock` + the phone-side rc/ArmingLock model in `FollowCoordinator`): the laptop's follow/approach controllers must hold the exclusive lock before driving the Tello, and arming owner `"phone"` disarms every laptop controller. It backstops, but does not replace, the operating rule (the phone commands the Tello over its own AP, outside the laptop's lock).
  - **Backend flight-path hardening (only exercised with the laptop armed).** Three earlier flight-control gaps — flagged in the deep audit — are now **fixed** in source, and matter only when the laptop `FollowController`/approach loop is the **armed** controller (`TELLO_DISABLE=0`); the supported `TELLO_DISABLE=1` phone-flies demo never starts those producers: (1) **RECALL is bounded** — `follow/controller.py` hovers on no tag reading (never blind-thrust) and caps total recall time (`_RECALL_MAX_S = 8.0`), then trips the mission's named failure to STOPPED so recall can't drive forever; (2) **arming follows the resulting stage** — `_route_arming_for_command(stage, lock)` is routed on `new_stage = mission.apply(cmd)` (not the raw command), so a rejected transition no longer hands the lock to "approach", and STOPPED releases every laptop owner (disarms); (3) **stale-frame follow is closed** — `TelloVideoSource.read_jpeg()` now enforces a freshness window (`_FRESH_WINDOW_S` + `_latest_t`), returning `None` on a stale/frozen video stream so the follow loop treats it as "tag lost -> hover" instead of station-keeping on a frozen frame.
- **Fresh repo, built during the event.** Reimplement from prior approaches, do not copy a pre-existing codebase wholesale.

## Roles

**Mavic (manned recon, piloted by a human)**
- Not autonomously flown. A person pilots it. Software consumes its video feed.
- Video arrives via the existing server stream.
- Runs YOLO (local) to detect relevant points and objects.
- Runs SLAM (local) for camera pose and a local map frame (same approach as the previous hackathon's recon mapping).
- Writes detected entities and positions into the world model.

**Tello (soldier companion)**
- Follows the soldier using an AprilTag worn by the soldier (badge/back), reading bearing and distance to station-keep.
- Plain Tello: it is its own WiFi AP. The active controller (normally the phone) joins the Tello AP and commands it directly over UDP (`192.168.10.1:8889`).
- The Tello must only ever take commands from one source at a time. Exactly one controller — the phone OR the laptop backend — is armed against it; never both.

**Laptop (the brain)**
- Runs the world model and a local server (WebSocket) that is the single source of truth for map + entities.
- Runs YOLO and SLAM on the Mavic feed; serves the web dashboard from the same local server.
- Ships a backend Tello controller (`FollowController` + `TelloClient`) and a backend approach loop as the laptop-side flight path, gated behind the `ArmingLock` interlock. In the current build the phone is the primary Tello controller, so the laptop's controllers stay disarmed (arming owner `"phone"`) whenever the phone is flying the drone (see "One Tello controller armed at a time").
- Runs a **Designator** (`backend/app/designation.py`): each broadcast tick it picks the top-priority recon detection (YOLO-sourced, **ACTIVE** status, high-value label, ranked by confidence then proximity to launch) and publishes it as a synthetic `designated_target` entity the dashboard reticles. The broadcast loop takes one `world.snapshot()` per tick and passes it to both designation and the broadcast (no double-tick). Read-only situational awareness — it commands nothing.

**Phone (mobile client)**
- Reads the map and entities from the laptop server (subscribe, do not duplicate state).
- Is the primary Tello controller: captures voice fully on-device (Apple `SFSpeechRecognizer` with `requiresOnDeviceRecognition`, no cloud) and maps the transcript to structured drone actions by deterministic keyword match (`DroneIntent.match`), then runs the AprilTag follow loop on-device, commanding the Tello directly over the Tello AP (`TelloCommander` → `192.168.10.1:8889`). (A Cactus/Gemma function-call mapper, `DronePilot`, is compiled in but not yet wired into the live voice loop — STT was moved off Cactus because Gemma 3n's `cactus_transcribe` path has no STT backend. Cactus/Gemma still powers on-device reasoning + vision.)
- Still sends mission-level intent (hold/recall) and its own device location to the laptop over the WebSocket for "follow me" context.
- **Co-registers with the laptop world frame.** The phone observes the same **launch anchor AprilTag** the Mavic uses (`AnchorCamera` on the back camera) and `FrameAligner` co-registers the phone's launch frame with the shared world frame (both north-up, so alignment is a pure translation refreshed each time the tag is re-seen). The phone then publishes world-frame entities (`EntityReport`, operator + drone) that upsert directly into the laptop world model and render on both maps — no longer just a relative inset.
- Runs a soldier-commanded **scout** maneuver (`ScoutController`): on command the pet leaves the follow, explores ahead in a few short bounded legs, rotates to scan at each, then retraces its exact path home and resumes following. Soldier-directed and bounded (leg count, rotation, time) — not autonomous pursuit; LAND/STOP preempt at any time.
- Runs **on-device object detection on the Tello feed** (`TelloObjectDetector`): a bundled CoreML YOLOv8n (COCO, NMS baked in) draws bounding boxes over the companion video, throttled so it never starves the follow loop. Fully on-device.

## Architecture

```
            [ Soldier w/ Phone ] ----AP (rc/takeoff/land)----> [ Tello ]
                  |   ^                                     (follows soldier
   mission intent |   | map + entities                      via AprilTag;
   (hold/recall)  |   | (subscribe)                          on-device loop)
   + device loc   v   |
[ Manned Mavic ] --video--> [ LAPTOP (brain) ]   (backend FollowController is an
                                |  YOLO (detect)   alternate Tello controller —
                                |  SLAM (pose/map) left disarmed while the phone flies)
                                |  World model     |
                                |  Local WS server |
                                v
                       [ Web dashboard ]  +  [ Mobile app ]
                          (both subscribe to the same local server)
```

## Repo structure (current)

```
backend/                 # the brain (Python, FastAPI)
  app/
    server.py            # FastAPI app + WS endpoint; binds 0.0.0.0:8000.
                         #   Also: intel summary/chat + /map/buildings + video
                         #   upload/MJPEG/JPEG HTTP routes; RTMP default; CORS
                         #   allowlist + optional OPERATOR_KEY hardening.
                         #   Rebroadcasts the phone's follow_state with a fail-
                         #   stale TTL (_FOLLOW_STALE_S); TELLO_DISABLE=1 skips
                         #   the laptop Tello controller (dual-live demo).
    contracts.py         # wire format (source of truth; mirrored by shared/ + mobile)
                         #   incl. FollowState (relative Tello range/bearing/phase
                         #   from the soldier; phases disarmed/searching/confirming/
                         #   following/lost/manual/stale; bounded, no NaN/inf).
    world_model.py       # single source of truth for entities
    state_machine.py     # mission/connection state
    ws_hub.py            # WebSocket fan-out to both clients
    clock.py video.py    # shared clock; Mavic video source handling
    reasoning/           # on-device "Gemini Live" equivalent (local Ollama)
      intel.py           #   IntelReasoner (periodic vision/text assessment),
                         #   IntelChat (operator Q&A), IntelSummary, ollama_alive
    tello/               # only code that talks to the Tello
      client.py          #   TelloClient (djitellopy-backed)
      video.py           #   TelloVideoSource
    follow/              # soldier-follow (AprilTag)
      apriltag.py        #   tag detection
      controller.py      #   FollowController (bearing/distance station-keeping)
    perception/          # Mavic feed: detect + map
      pipeline.py yolo.py depth.py fusion.py file_processor.py
                         #   yolo.py supports a YOLO-World custom vocabulary +
                         #   an optional second COCO YOLOv8 ensemble detector.
      slam/              #   vo.py anchor.py backend.py local_map.py types.py
                         #   euroc.py orbslam3_runner.py
  run.sh                 # uvicorn app.server:app --host 0.0.0.0 --port 8000
  requirements.txt       # incl. python-multipart (upload)
  tests/                 # pytest; run: cd backend && .venv/bin/python -m pytest -q
                         #   test_contracts test_state_machine test_video
                         #   test_world_model test_upload_guards slam/*

frontend/                # web dashboard (Next.js + Tailwind, runs on port 3000)
  src/app/               # layout.tsx globals.css
    page.tsx             #   marketing landing page (public-facing)
    operator/page.tsx    #   operator dashboard (Feed/Map/Intel tabs)
  src/components/        # Clock ConsolePanel EntityList IntelPanel IntelChat
                         # IntelSummaryCard Buildings LocalMap LocalMap2D
                         # LocalMap3D SourceSelector StatusBar ThreatAlert
                         # VideoFeed VideoPlayer FollowInset (renders follow_state)
  src/lib/               # contracts entities feedUrl playback projection
                         # status threats useWorldClient wsConfig
                         # (+ vitest: feedUrl.test.ts wsConfig.test.ts)
                         # Pulls MJPEG/JPEG + WS (:8000) from the brain.

mobile/                  # iOS / SwiftUI client (pairs with Cactus/Gemma on-device)
  Sources/               # ReconCompanionApp ContentView WorldClient OSMMapView
                         # LocalMapView MapProjection AprilTagDetector ObjectTracker
                         # FollowController FollowCoordinator Cactus CactusService
                         # VoiceController IntentParser DroneFunction DronePilot
                         # TelloCommander TelloDirectStream TelloVideoView MJPEGView
                         # ModelDownloader LocationProvider Localizer StatusBar
                         # ControlBar Theme Contracts
                         #   FollowCoordinator drives the airborne target-confirm
                         #   flow (.confirming phase + confirmTarget()); TelloVideoView
                         #   shows the confirm bar. WorldClient.sendFollowState publishes
                         #   follow_state to the laptop. Contracts mirrors FollowState.
                         #   The laptop-intent ControlBar shows only on the Map tab
                         #   (hidden on Feed, where the phone flies the Tello).
  Tests/                 # ContractsTests FollowControllerTests IntentParserTests
                         # MapProjectionTests WorldClientConfigTests

shared/contracts.ts      # TS mirror of backend/app/contracts.py (incl. FollowState)
docs/                    # DEMO.md (live dual-live demo runbook), README,
                         # MOBILE, SLAM, VIDEO, VOICE
scripts/                 # asc.py, run_slam_video.py, fetch_buildings.py
.context/buildings.json  # pre-cached OSM building polygons (offline map layer;
                         # generated once by scripts/fetch_buildings.py, served
                         # read-only at /map/buildings)
models/  captures/       # local data dirs (weights, recorded feeds)
```

## Tech stack

**Brain (laptop, Python)**
- `djitellopy` for Tello control (bind the UDP socket to the Tello WiFi interface IP).
- `ultralytics` YOLO for detection (local weights). When `YOLO_WEIGHTS` is set to a `-world` checkpoint it runs YOLO-World open-vocabulary driven by a defense-relevant prompt set (`server.py` `_DEFAULT_VOCAB`; override with `YOLO_CLASSES`); an optional second standard YOLOv8/COCO detector can be ensembled in (`YOLO_COCO_WEIGHTS` / `YOLO_COCO_KEEP`). With `YOLO_WEIGHTS` unset, perception falls back to the best bundled COCO model present — **default recon model is now `yolov8s` (preferred over `yolov8n`)** so recon detection + target designation work out of the box (weights gitignored; absence degrades to SLAM-only). Other knobs: `YOLO_IMGSZ`, `YOLO_CONF`, `DEPTH_MODEL`/`DEPTH_SCALE`, `ANCHOR_TAG_SIZE_M`, `FOLLOW_TAG_SIZE_M`, `PERCEPTION_FPS`.
- On-device reasoning (`app/reasoning/intel.py`): the offline equivalent of the prior hackathon's Gemini Live. A local Ollama vision/text model (default `gemma3:4b`) periodically assesses the latest frame + YOLO labels (`IntelReasoner`), and answers operator questions over the same context (`IntelChat`). `httpx` to a local Ollama at `127.0.0.1:11434`; no cloud. Env: `INTEL_MODEL` (default `gemma3:4b`, `off` disables), `INTEL_VISION` (**default now `1`** — image-aware reasoning for the demo; `0` falls back to the text-only path, which is ~30x faster), `INTEL_INTERVAL_S` (default `5`). The periodic intel loop, the on-demand `/intel/deep-look`, and `/intel/chat` all share **one** local Ollama (`127.0.0.1:11434`) and are serialized behind a single process-wide `asyncio.Lock` (`_get_ollama_lock()`), so only one inference runs at a time and they never double the load (the periodic loop also exposes a `running` flag for the `/intel/summary` UI). Auto-disabled if Ollama is unreachable.
- **Detection note (what detects what, and what does not).** Recon runs `yolov8s` (COCO classes) on the laptop over the Mavic feed; the phone runs an on-device CoreML `yolov8n` (COCO) over the Tello feed (`TelloObjectDetector`). **Neither detects weapons** — both are COCO-class only (person, vehicle, backpack, etc.). Open-vocabulary defense detection (YOLO-World custom vocab, the `-world` checkpoint path) is the heavier follow-up, not the default.
- SLAM: monocular VO (ORB-SLAM3 or equivalent), local. Local frame only, no GPS.
- `opencv` + AprilTag detection (`pupil-apriltags` or OpenCV's aruco/apriltag module) for the soldier-follow tag.
- `fastapi` + `websockets` for the local server. Bind to `0.0.0.0`. HTTP surface is hardened: CORS allowlist (`DASHBOARD_ORIGINS`), optional `OPERATOR_KEY` header gate on state-mutating routes, `MAX_UPLOAD_MB` + video-extension allowlist on upload. Dashboard "RTMP" button targets a local MediaMTX relay (`MAVIC_RTMP_DEFAULT`, default `url:rtmp://127.0.0.1:1935/live`).
- Offline map layer: `scripts/fetch_buildings.py` pulls OSM building polygons once (requires internet at fetch time only), projects them into the local frame, and writes `.context/buildings.json`, which the backend serves read-only at `/map/buildings` — zero runtime network.
- Follow telemetry: the laptop rebroadcasts the phone's `FollowState` (relative Tello range/bearing/phase from the soldier, never map coordinates) and downgrades it to a visible `stale` phase via a fail-stale TTL (`_FOLLOW_STALE_S`) when the phone stream ages out. `TELLO_DISABLE=1` makes the backend skip connecting to / commanding the Tello — the configuration for the dual-live demo (laptop runs Mavic recon + dashboard while the phone flies the Tello).

**Voice (phone, on-device)**
- Cactus running Gemma for local STT plus intent. Cactus is mobile-first, so run it on the phone.
- Constrain output to a fixed command vocabulary (structured intent enum), not free text.

**Web dashboard (laptop)**
- Next.js 14 + Tailwind. Runs on port 3000; pulls MJPEG/JPEG video + the WS world model from the brain (default `ws://localhost:8000/ws`, via `src/lib/wsConfig.ts`; override with `NEXT_PUBLIC_WS_URL`).
- `/` is a public-facing marketing landing page (`src/app/page.tsx`); the operator dashboard lives at `/operator` (`src/app/operator/page.tsx`) with Feed/Map/Intel tabs.
- Renders the world model as a top-down 2D tactical map (`LocalMap2D`) and a `three.js` 3D scene (`LocalMap3D`/`Buildings`), both overlaying the pre-cached OSM footprints from `/map/buildings`. The intel reasoner surfaces as `IntelSummaryCard` (periodic assessment) and `IntelChat` (operator Q&A). `FollowInset` renders the rebroadcast `FollowState` (Tello follow phase + relative range/bearing).
- Dark tactical aesthetic. Define design tokens first (layered near-black, one accent, hairline borders, mono numerals). Avoid generic defaults.

**Mobile app (phone)**
- iOS / SwiftUI (pairs with Cactus on-device). Map view plus voice control plus device location.
- `ObjectTracker` (Vision `VNTrackObjectRequest`) adds tag-free, class-agnostic visual lock-and-follow ("track that boat") alongside the AprilTag follow. `Localizer` builds a phone-side map (operator + drone placed by tag distance/bearing rotated by compass heading, with movement trails) so the map renders with no laptop in the loop.

## World model / data

Entities, each with: `id`, `type` (point of interest, hazard, object, soldier, drone), `position` (local frame), `status`, `confidence`, `timestamp`, `source`.

Map is a local frame anchored to landmarks plus launch point. Plot entities as they are detected. Both clients render the same entity set live.

## Networking (offline, local only)

- Plain Tello is AP-only: laptop built-in WiFi connects to the Tello network to fly it.
- Laptop needs a second interface (USB WiFi dongle or USB-ethernet to a travel router with no WAN) to reach the phone, since it cannot be on the Tello AP and the phone network on one adapter.
- Bind the map server to `0.0.0.0`. Bind the Tello socket to the Tello WiFi interface IP.
- Verify routing with `route get <dest>` for each interface.
- If the two-interface routing fights you, fallback: put the phone on the Tello AP alongside the laptop (one network, no multi-homing).

## Command flow

1. Phone turns speech into a structured drone action locally (Cactus/Gemma function-calling).
2. Phone sends flight commands **directly** to the Tello over the Tello AP (`rc` / `takeoff` / `land` / `emergency`); the on-device AprilTag follow loop sends `rc` at a fixed cadence the same way.
3. Mission-level intent (hold/recall) and device location still go to the laptop over the WebSocket; the laptop owns the world model and streams map + state back to both clients. The phone also co-registers against the launch anchor tag (`AnchorCamera` + `FrameAligner`) and publishes world-frame entities (`EntityReport`) that upsert into the world model directly.
4. The laptop's backend `FollowController` + approach loop is an alternate flight path and MUST stay disarmed while the phone is flying. A real **code interlock now exists** (`ArmingLock`, `backend/app/follow/arming.py`): the laptop controllers must hold the exclusive lock before driving the Tello, and arming owner `"phone"` disarms them. The operating rule still stands because the phone talks to the Tello over its own AP, outside the laptop's lock.

> Deviation note: earlier drafts of this spec made the laptop the sole Tello controller and routed phone intent through it. The build pivoted to phone-direct control (on-device follow + voice); this section reflects the code as built. The arming interlock that was the recommended follow-up now exists (`ArmingLock`), and the backend flight path it guards is hardened (bounded RECALL, stage-gated arming, freshness-windowed Tello video) — see "One Tello controller armed at a time".

Make a hard stop/recall control a button on the phone, not voice only.

## Build order (front-load the hard part)

1. **Local server + world model + WebSocket plumbing.** The spine both clients read from.
2. **Tello follow-me (AprilTag on soldier).** The only genuinely new robotics piece and the schedule risk. Build and tune this as a standalone milestone first.
3. **Mavic recon: YOLO + SLAM → entities into the world model.**
4. **Web dashboard map view.**
5. **Mobile app: map view + device location.**
6. **Voice: Cactus/Gemma on phone → structured commands → direct Tello control (on-device).**
7. **Polish, error handling, and a mission/connection state view so failures are diagnosable by stage.**

## Non-goals

No attack, engagement, targeting, or balloon popping. No cloud. No internet. No GPS. No drone swarm. No autonomous Mavic flight.
