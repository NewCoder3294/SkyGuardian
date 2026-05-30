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
- Plain Tello: it is its own WiFi AP, so the laptop connects directly to it and is the sole controller.
- The Tello never takes commands from two sources. Only the laptop commands it.

**Laptop (the brain)**
- Owns the Tello connection and is the only thing that sends it flight commands.
- Runs the world model and a local server (WebSocket) that is the single source of truth.
- Runs YOLO and SLAM on the Mavic feed.
- Serves the web dashboard and the mobile app from the same local server.

**Phone (mobile client)**
- Reads the map and entities from the laptop server (subscribe, do not duplicate state).
- Sends voice commands and intent to the laptop (never to the Tello directly).
- Provides its own device location for "follow me" context.

## Architecture

```
            [ Soldier w/ Phone ]
                  |  voice intent (Cactus/Gemma, on-device) + map subscribe
                  v
[ Manned Mavic ] --video--> [ LAPTOP (brain) ] <--AP--> [ Tello (follows soldier via AprilTag) ]
                                |  YOLO (detect)   |
                                |  SLAM (pose/map) |
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
    server.py            # FastAPI app + WebSocket endpoint; binds 0.0.0.0:8000
    contracts.py         # wire format (source of truth; mirrored by shared/ + mobile)
    world_model.py       # single source of truth for entities
    state_machine.py     # mission/connection state
    ws_hub.py            # WebSocket fan-out to both clients
    clock.py video.py    # shared clock; Mavic video source handling
    tello/               # only code that talks to the Tello
      client.py          #   TelloClient (djitellopy-backed)
      video.py           #   TelloVideoSource
    follow/              # soldier-follow (AprilTag)
      apriltag.py        #   tag detection
      controller.py      #   FollowController (bearing/distance station-keeping)
    perception/          # Mavic feed: detect + map
      pipeline.py yolo.py depth.py fusion.py file_processor.py
      slam/              #   vo.py anchor.py backend.py local_map.py types.py
                         #   euroc.py orbslam3_runner.py
  run.sh                 # uvicorn app.server:app --host 0.0.0.0 --port 8000
  requirements.txt
  tests/                 # pytest; run: cd backend && .venv/bin/python -m pytest -q

frontend/                # web dashboard (Next.js + Tailwind, runs on port 3001)
  src/app/               # layout.tsx page.tsx globals.css
  src/components/        # Clock ConsolePanel EntityList IntelPanel LocalMap
                         # LocalMap3D SourceSelector StatusBar ThreatAlert
                         # VideoFeed VideoPlayer
  src/lib/               # contracts entities feedUrl playback projection
                         # status threats useWorldClient
                         # Pulls MJPEG/JPEG from the brain.

mobile/                  # iOS / SwiftUI client (pairs with Cactus/Gemma on-device)
  Sources/               # ReconCompanionApp ContentView WorldClient OSMMapView
                         # LocalMapView MapProjection AprilTagDetector
                         # FollowController FollowCoordinator Cactus CactusService
                         # VoiceController IntentParser DroneFunction DronePilot
                         # TelloCommander TelloDirectStream TelloVideoView MJPEGView
                         # ModelDownloader LocationProvider StatusBar ControlBar
                         # Theme Contracts
  Tests/                 # ContractsTests FollowControllerTests
                         # IntentParserTests MapProjectionTests

shared/contracts.ts      # TS mirror of backend/app/contracts.py
scripts/                 # asc.py, run_slam_video.py
models/  captures/       # local data dirs (weights, recorded feeds)
```

## Tech stack

**Brain (laptop, Python)**
- `djitellopy` for Tello control (bind the UDP socket to the Tello WiFi interface IP).
- `ultralytics` YOLO for detection (local weights).
- SLAM: monocular VO (ORB-SLAM3 or equivalent), local. Local frame only, no GPS.
- `opencv` + AprilTag detection (`pupil-apriltags` or OpenCV's aruco/apriltag module) for the soldier-follow tag.
- `fastapi` + `websockets` for the local server. Bind to `0.0.0.0`.

**Voice (phone, on-device)**
- Cactus running Gemma for local STT plus intent. Cactus is mobile-first, so run it on the phone.
- Constrain output to a fixed command vocabulary (structured intent enum), not free text.

**Web dashboard (laptop)**
- Next.js 14 + Tailwind. Runs on port 3001; pulls MJPEG/JPEG video from the brain.
- Dark tactical aesthetic. Define design tokens first (layered near-black, one accent, hairline borders, mono numerals). Avoid generic defaults.

**Mobile app (phone)**
- iOS / SwiftUI (pairs with Cactus on-device). Map view plus voice control plus device location.

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

1. Phone turns speech into a structured intent locally (Cactus/Gemma).
2. Phone sends the intent JSON to the laptop over the WebSocket.
3. Laptop validates and arbitrates, then commands the Tello.
4. Laptop streams map and state back to both clients.

Make a hard stop/recall control a button on the phone, not voice only.

## Build order (front-load the hard part)

1. **Local server + world model + WebSocket plumbing.** The spine both clients read from.
2. **Tello follow-me (AprilTag on soldier).** The only genuinely new robotics piece and the schedule risk. Build and tune this as a standalone milestone first.
3. **Mavic recon: YOLO + SLAM → entities into the world model.**
4. **Web dashboard map view.**
5. **Mobile app: map view + device location.**
6. **Voice: Cactus/Gemma on phone → structured commands → laptop.**
7. **Polish, error handling, and a mission/connection state view so failures are diagnosable by stage.**

## Non-goals

No attack, engagement, targeting, or balloon popping. No cloud. No internet. No GPS. No drone swarm. No autonomous Mavic flight.
