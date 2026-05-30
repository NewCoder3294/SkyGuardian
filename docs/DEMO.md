# Live Demo Runbook — Laptop + Phone Together

Goal: run **both ends live at once** — the laptop does Mavic recon (YOLO + SLAM →
world model → dashboard) while the phone flies the Tello to follow the soldier,
and the phone sees the laptop's map in real time.

This is the **phone-direct** topology: the phone is the sole Tello controller; the
laptop never touches the Tello (see [CLAUDE.md](../CLAUDE.md) → "One Tello
controller armed at a time").

---

## 1. Network topology (the binding constraint)

An iPhone can only join one WiFi at a time, and it **must** be on the Tello AP to
fly the Tello. So everything lives on **one network: the Tello's own AP**.

```
        Tello AP (SSID TELLO-xxxxxx, gateway 192.168.10.1)
        ├── Tello            192.168.10.1   (flown by the phone)
        ├── Phone            192.168.10.x   ── flies Tello (UDP :8889)
        │                                   └─ subscribes to laptop WS (:8000)
        └── Laptop           192.168.10.y   ── serves WS + dashboard (binds 0.0.0.0)
                                            └─ Mavic recon via LOCAL RTMP relay
                                               (127.0.0.1:1935, never on the AP)
```

- The **laptop joins the Tello AP** purely so the phone can reach its WebSocket
  server. With `TELLO_DISABLE=1` (below) the laptop does **not** connect to the
  Tello despite being on the same AP.
- The **Mavic feed stays local to the laptop**: push it into the laptop's own RTMP
  relay (MediaMTX on `127.0.0.1:1935`, the built-in default) via HDMI capture from
  the DJI controller or the DJI app. It never crosses the Tello AP.

---

## 2. Laptop (the brain)

```bash
cd backend
TELLO_DISABLE=1 \              # laptop never commands the Tello (phone owns it)
MAVIC_SOURCE=url:rtmp://127.0.0.1:1935/live \   # or omit and click "RTMP" in the dashboard
DASHBOARD_ORIGINS=http://localhost:3001 \
./run.sh                       # uvicorn app.server:app --host 0.0.0.0 --port 8000
```

Then the dashboard (separate terminal):

```bash
cd frontend && npm run dev     # http://localhost:3001 — operator dashboard at /operator
```

`/` is the marketing landing page; open **`http://localhost:3001/operator`** for the
live operator dashboard (Feed/Map/Intel tabs, with the `FollowInset` radar).

Optional env:
- `INTEL_MODEL=gemma3:4b` (default) for on-device reasoning; `INTEL_MODEL=off` to skip. Needs a local Ollama.
- `YOLO_WEIGHTS=/path/to/yolov8x-worldv2.pt` for open-vocab detection (defense vocab loads by default for `-world` checkpoints).
- `OPERATOR_KEY=...` to require `X-Operator-Key` on the source-swap/upload POSTs.

**Verify the laptop is NOT touching the Tello:** `curl localhost:8000/health` →
`"tello": "disabled"`. (Without the flag it would say `connecting`/`connected` and
fight the phone.)

---

## 3. Phone (Tello controller + map client)

1. Join the **Tello AP** in iOS WiFi settings.
2. Point the app at the laptop: set `WorldClient.serverURL` to
   `ws://192.168.10.y:8000/ws` (the laptop's Tello-AP IP — default is
   `ws://127.0.0.1:8000/ws`, which only works in the simulator). Set it via the
   app's server field or a launch arg.
3. Arm follow: the phone runs the on-device AprilTag follow loop and commands the
   Tello directly over `192.168.10.1:8889`.

The soldier wears the follow AprilTag (size `FOLLOW_TAG_SIZE_M`, default 0.18 m;
filter to a tag id with `FOLLOW_TAG_ID`).

---

## 4. What shows where

| Surface | Sees |
|---|---|
| **Phone map** | Mavic recon entities (subscribed from laptop WS) **+** the Tello/operator follow track (computed on-device) |
| **Laptop dashboard** | Mavic recon (YOLO detections, SLAM map, intel) **+** the Tello follow as a relative **radar inset** (`FollowInset`) |

> ✅ The phone now publishes its follow geometry to the laptop. The phone computes
> the follow on-device (`Localizer` / follow loop) and sends `follow_state`
> (relative range + bearing + phase) over the WS; the laptop **rebroadcasts** it
> and the dashboard renders it as the `FollowInset` radar (soldier at centre,
> Tello range/bearing). It is a **relative inset, not co-registered with the SLAM
> map** — the phone's follow frame and the Mavic SLAM frame don't share a
> reference, so the Tello is shown as range/bearing rather than placed on the map.
> If the phone stream ages out (2 s), the inset downgrades to a visible `stale`
> phase rather than silently freezing.

---

## 5. Pre-flight safety checklist

- [ ] Laptop `/health` reports `"tello": "disabled"` — only the phone commands the Tello.
- [ ] Phone is on the Tello AP and its `serverURL` points at the laptop's AP IP.
- [ ] Operator dashboard at `:3001/operator` shows the Mavic feed linking/streaming (and the `FollowInset` radar once the phone publishes follow state).
- [ ] Hard stop/recall button on the phone works (don't rely on voice alone).
- [ ] Tello battery checked; clear follow area.

---

## 6. Troubleshooting

- **Phone map empty:** `serverURL` wrong or laptop not on the AP. `curl http://192.168.10.y:8000/health` from a laptop browser on the AP.
- **Dashboard shows no Mavic video:** the RTMP relay has no publisher yet — start the DJI → `127.0.0.1:1935/live` push; the dashboard shows the publish URL while waiting for the first frame.
- **Tello unresponsive / jittery:** confirm laptop health says `tello: disabled`. If it says `connected`, the laptop is contending — restart it with `TELLO_DISABLE=1`.
- **CORS error in the dashboard console:** add the dashboard's exact origin to `DASHBOARD_ORIGINS`.
