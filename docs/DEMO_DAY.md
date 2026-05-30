# Demo Day Runbook — SkyGuardian (Laptop + Phone)

Field-tested checklist for running the live demo. For the architecture/topology
rationale see [DEMO.md](./DEMO.md); this doc is the **do-this-in-order** version
with the gotchas we actually hit.

---

## 0. One-time prep (do before demo day, needs internet)

1. **Backend venv with ML deps** (heavy, ~once):
   ```bash
   cd backend && .venv/bin/python -m pip install -r requirements.txt
   ```
   Verify: `.venv/bin/python -c "import torch, ultralytics, cv2; print('ok')"`

2. **Cache buildings for the demo site** (real OSM footprints, served offline):
   ```bash
   cd ~/recon-companion
   python3 scripts/fetch_buildings.py --lat <LAT> --lng <LNG> --radius 400
   ```
   Writes `.context/buildings.json`. The dashboard reads it live (no restart).
   Re-run with the demo site's coordinates — buildings only show for the area
   you cache. Without this, the map renders the grid but **no buildings**.

3. **(Optional) YOLO weights** for recon detections:
   put a `-world` checkpoint somewhere and pass `YOLO_WEIGHTS=/path/...pt`.
   Without weights the recon map runs SLAM-only (no detection boxes).

---

## 1. Network (the part that bit us)

The phone must share a network with the laptop for the map link.

- **Tello AP isolates clients** on some firmware — the laptop and phone both join
  `TELLO-xxxx` but **cannot reach each other** (`192.168.10.x` times out). If the
  phone's map stays empty and `http://192.168.10.<laptop>:8000/health` hangs in
  the phone's browser, this is why.
- **Working fallback we used: iPhone Personal Hotspot.** Laptop joins the phone's
  hotspot; the laptop appears at `172.20.10.x` and the phone reaches it reliably.
  > Trade-off: a phone on its own hotspot is **not** on the Tello AP, so it can't
  > fly the Tello on that link. Use the hotspot path to demo the **map sync**;
  > use the Tello AP for the **flight** portion (see DEMO.md topology).

**Get the laptop's current IP for the phone:**
```bash
ifconfig | awk '/^[a-z]/{i=$1} /inet /{print i, $2}' | grep -v 127.0.0.1
```
Pick the address on the network the phone is also on (`172.20.10.x` hotspot or
`192.168.10.x` Tello AP).

---

## 2. Start the laptop (the brain)

Two terminals.

**Backend** — launch via the **venv's** uvicorn (a bare `uvicorn` grabs the wrong
Python, e.g. Anaconda, and fails with `No module named 'cv2'`):
```bash
cd backend
TELLO_DISABLE=1 DASHBOARD_ORIGINS=http://localhost:3001 \
  .venv/bin/python -m uvicorn app.server:app --host 0.0.0.0 --port 8000
```

**Dashboard:**
```bash
cd frontend && npm run dev      # http://localhost:3001/operator
```

**Verify:**
```bash
curl localhost:8000/health
# → {"ok":true,"tello":"disabled","perception":"running",...}
```
`"tello":"disabled"` is mandatory — it means the laptop won't fight the phone for
the Tello.

> If port 8000 says "address already in use", a stale uvicorn is holding it:
> `pkill -f "uvicorn app.server:app"` then restart.

---

## 3. Connect the phone

1. Phone on the same network as the laptop (hotspot for map demo).
2. App → **MISSION LINK** field → `ws://<laptop-ip>:8000/ws`
   (e.g. `ws://172.20.10.8:8000/ws`). Must include `ws://` and `/ws`.
3. Tap **CONNECT**.

**Confirm it actually joined** (the app shows "connected" optimistically, so check
the server side):
```bash
curl localhost:8000/health        # clients count goes up by 1
grep "WebSocket /ws" <backend-log> | grep -v 127.0.0.1 | tail   # phone IP appears
```

---

## 4. What to show

| Surface | Shows |
|---|---|
| **Dashboard** `:3001/operator` | Recon map (buildings + SLAM + YOLO entities), Intel tabs, `FollowInset` radar (Tello range/bearing) |
| **Phone** | Same world model live + on-device follow track |

- **Map sync proof:** phone's `device_location` (needs Location permission) appears
  as a **soldier dot on both** the phone and the dashboard simultaneously.
- **Follow inset:** once the phone publishes `follow_state`, the dashboard radar
  shows the Tello's relative range/bearing (not co-registered with the SLAM map —
  it's a relative inset by design).

---

## 5. Pre-flight checklist

- [ ] `/health` → `"tello":"disabled"`
- [ ] Buildings cached for the demo site (`/map/buildings` returns JSON, not 404)
- [ ] Phone connected (server-side client count confirmed)
- [ ] Soldier dot visible on both screens
- [ ] Phone hard stop/recall button works (don't rely on voice)
- [ ] Tello battery charged; clear follow area

---

## 6. Map options (current vs. planned)

- **Current (default):** local-frame tactical map with **real OSM building
  footprints** overlaid (from `fetch_buildings.py`). Offline, abstract backdrop.
- **Planned alternative:** a real slippy-map basemap (streets + buildings as a
  visual tile layer) under the entities, pre-cached for offline use, with the
  local-frame map kept as a toggle. See the "OSM tile basemap" follow-up.
