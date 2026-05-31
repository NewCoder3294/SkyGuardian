# Data Flywheel — Collect / Clean / Package — Design

**Date:** 2026-05-30 · **Track:** Backend perception + offline ML data pipeline

## Goal

Capture what SkyGuardian sees in the field, clean it, and package it into training-ready
datasets — so the models (YOLO detector first, Gemma reasoning later) can be improved
between missions. **For the hackathon, scope is collect → clean → package only.** Actual
model training and any Palantir Foundry upload are deferred, but the packaging output is
Foundry-ready (a stable `manifest.json`) so those steps drop in later without rework.

## Hard constraints (must hold)

- **Offline-first.** Collection and cleaning/packaging are pure local-disk operations. No
  network, no cloud, no external APIs. (Foundry export is a deferred, explicitly-online
  step outside this scope.)
- **Opt-in collection.** Capture writes to disk and is OFF by default (`CAPTURE_ENABLED`),
  so normal missions are unaffected unless an operator turns it on.
- **Never destabilize the live system.** The capture hook must never throw into the
  perception loop or block it; failures are swallowed and logged, capture is best-effort.
- **Bounded disk.** Capture respects a max-size budget and stops/rotates rather than
  filling the disk.

## Background (current state, verified)

- `backend/app/perception/pipeline.py` `PerceptionPipeline._run` (the per-tick loop, ~line
  217) is the single point where a frame (`frame_bgr`), its `detections`, the SLAM
  `current_pose`, and the clock `now` are all in scope together. This is the capture hook.
- Detections are normalized boxes (`DetectionBox`: `label`, `confidence`, `cx`, `cy`, `w`,
  `h` in 0..1) — see `backend/app/contracts.py`.
- `captures/` and `models/` exist but hold only READMEs — nothing is persisted today.
- The phone (`mobile/Sources/FollowCoordinator.swift`) already has an operator
  confirm/reject decision on the follow target (`.confirming` → `confirmed`). This is a
  free label signal currently discarded.
- Wire contracts: `backend/app/contracts.py` is the source of truth, mirrored in
  `shared/contracts.ts` and `mobile/Sources/Contracts.swift`. `ClientMessage` union +
  `parse_client_message` handle inbound client messages.

## Scope

**In scope (this spec):**
1. **Collect** — capture recorder + `LabelEvent` wire message + pipeline hook.
2. **Clean** — pure cleaning module + CLI.
3. **Package** — pure packaging module + CLI → YOLO dataset + Gemma example JSONL +
   Foundry-ready `manifest.json`.

**Deferred (documented, NOT built):** `scripts/train_yolo.py` (model training),
`scripts/export_to_foundry.py` (online upload of the packaged dataset+manifest to Foundry).

## On-disk layout

```
captures/<mission_id>/
  frames/<seq>.jpg              # sampled frames (JPEG)              [collect]
  observations.jsonl           # one Observation per saved frame    [collect]
  events.jsonl                 # one Event per operator label action[collect]
  cleaned/
    observations.jsonl         # cleaned Observation list            [clean]
    cleaning_report.json       # counts in/out per rule              [clean]

datasets/<dataset_name>/                                            # [package]
  yolo/
    images/{train,val}/*.jpg
    labels/{train,val}/*.txt    # ultralytics format: "class_id cx cy w h" (normalized)
    data.yaml                   # names + train/val paths
  gemma/examples.jsonl          # one reasoning example per line
  cleaning_report.json          # copied from captures/<id>/cleaned/ for provenance
  manifest.json                 # Foundry-ready summary (the seam)
```

`<mission_id>` is supplied by the operator (env `CAPTURE_MISSION_ID`) or defaults to a
timestamp passed in at startup (no `Date.now()` inside testable code — the id is injected).

## Record schemas (`backend/app/capture/schema.py`)

Plain dataclasses/pydantic models with explicit versions so packaging stays stable.

```python
class Detection(BaseModel):
    label: str
    conf: float = Field(ge=0.0, le=1.0)
    box: list[float]            # [cx, cy, w, h], normalized 0..1

class Observation(BaseModel):
    v: int = 1
    t: float
    mission_id: str
    frame_path: str             # relative to mission dir, e.g. "frames/000123.jpg"
    source: str                 # "leader" (Mavic) | "follower" (Tello)
    image_w: int
    image_h: int
    pose: Optional[Vec3] = None # SLAM local-frame camera position if available
    detections: list[Detection]
    sampled_reason: Literal["low_conf", "novel_class", "cadence"]

class Event(BaseModel):
    v: int = 1
    t: float
    mission_id: str
    kind: Literal["confirm", "reject", "correct"]
    source: str
    label: Optional[str] = None
    corrected_label: Optional[str] = None
    box: Optional[list[float]] = None    # [cx,cy,w,h] normalized
    note: Optional[str] = None
```

## Component 1 — Collect

### `LabelEvent` wire message (`contracts.py` + TS + Swift mirror)
```python
class LabelEvent(BaseModel):
    type: Literal["label_event"] = "label_event"
    kind: Literal["confirm", "reject", "correct"]
    source: str
    label: Optional[str] = None
    corrected_label: Optional[str] = None
    box: Optional[list[float]] = None
    note: Optional[str] = None
    t: float
```
Added to `ClientMessage` union + handled in `parse_client_message`. Mirrored in
`shared/contracts.ts`. Mobile (`Contracts.swift`) gains an **encodable** `LabelEvent` (the
phone emits it). The phone sends a `confirm`/`reject` `LabelEvent` at the existing follow
confirm/reject decision point (small wiring in `FollowCoordinator`/`WorldClient`). The
server's WS handler routes `LabelEvent` → `recorder.record_event(...)`.

### `backend/app/capture/recorder.py`
`CaptureRecorder(root: Path, mission_id: str, *, max_mb: float, cadence_s: float,
low_conf: float, enabled: bool)`:
- `observe(frame_bgr, detections, pose, t, source, image_w, image_h) -> bool` — applies the
  **sampling policy**, and if sampled, writes the JPEG + appends an `Observation` line.
  Returns whether it saved.
- `record_event(event: Event) -> None` — appends to `events.jsonl`.
- **Sampling policy:** save the frame if ANY detection is below `low_conf` (active-learning
  value) OR a detection's class hasn't been seen this mission yet (`novel_class`) OR at
  least `cadence_s` has elapsed since the last save (`cadence`). Otherwise skip. The
  `sampled_reason` is recorded.
- **Bounded disk:** track bytes written; once `max_mb` is exceeded, stop saving frames
  (still allows events) and log once. No crash.
- **Best-effort:** all disk I/O wrapped so an exception is logged and swallowed — never
  propagates into the perception loop.
- Pure local disk; no network.

### Pipeline hook (`pipeline.py:_run`)
After detections + pose are computed for a tick, call
`self._recorder.observe(frame_bgr, detections, current_pose, now, source="leader",
image_w=..., image_h=...)` when a recorder is configured. The recorder is constructed in
`server.py` only when `CAPTURE_ENABLED=1`; otherwise `None` and the hook is skipped. Env
knobs: `CAPTURE_ENABLED`, `CAPTURE_MISSION_ID`, `CAPTURE_MAX_MB` (default 2000),
`CAPTURE_CADENCE_S` (default 2.0), `CAPTURE_LOW_CONF` (default 0.4).

## Component 2 — Clean (`backend/app/capture/cleaning.py` + `scripts/clean_captures.py`)

Pure functions over a mission's capture dir → a cleaned `Observation` list + a report.
Rules (confirmed):
1. **Drop corrupt/blank frames** — unreadable/zero-byte/decode-failure, or near-uniform
   (e.g. stdev of grayscale below a threshold → black/blank).
2. **Near-duplicate dedup** — perceptual hash (aHash/dHash) on consecutive saved frames;
   drop a frame within Hamming-distance threshold of the previously kept frame.
3. **Degenerate-box filter** — drop detections with non-positive area, out-of-[0,1]
   bounds, or `conf` below a floor.
4. **Schema validation** — records that don't parse are quarantined (counted, skipped),
   never crash the run.
5. **Cleaning report** — `{frames_in, dropped_corrupt, dropped_duplicate, frames_out,
   boxes_in, boxes_dropped, records_invalid}` written to `cleaning_report.json`.

`scripts/clean_captures.py --mission <id> [--root captures]` is a thin CLI that calls the
module and writes `captures/<id>/cleaned/observations.jsonl` + `cleaning_report.json`.

## Component 3 — Package (`backend/app/capture/packaging.py` + `scripts/package_dataset.py`)

Pure functions over cleaned observations (+ events) → dataset artifacts:
- **YOLO dataset:** copy/symlink sampled frames into `yolo/images/{train,val}`; write
  ultralytics `labels/*.txt` (`class_id cx cy w h`, normalized) using the class list
  derived from all observed labels; write `data.yaml` (names + paths). Train/val split is a
  deterministic hash of `frame_path` (no RNG — reproducible). Where an operator `correct`
  event matches a detection, the corrected label is used; `reject` events drop that box.
- **Gemma examples** (`gemma/examples.jsonl`): one line per observation —
  `{frame_path, context:{labels_seen, pose, t}, prompt, gold_answer}` where `gold_answer`
  comes from a matching `correct`/`confirm` event (else null; null-answer examples are kept
  for context but flagged `"labeled": false`).
- **`manifest.json` (Foundry seam):** stable, versioned summary —
  `{v, mission_ids, source_counts, yolo:{path,classes,train,val,format:"ultralytics"},
  gemma:{path,count,labeled_count}, cleaning_report, label_events:{confirm,reject,correct}}`.
  Timestamp is injected by the CLI (not generated inside the pure module).

`scripts/package_dataset.py --mission <id> --out datasets/<name> [--val-frac 0.2]` reads
`captures/<id>/cleaned/observations.jsonl` + `captures/<id>/events.jsonl`, writes the
dataset artifacts, and copies `cleaning_report.json` into the dataset dir for provenance.
(Run `clean_captures.py` first; packaging errors clearly if the cleaned dir is absent.)

## Error handling

| Condition | Behavior |
|---|---|
| Capture disabled | Recorder is `None`; hook is a no-op; zero overhead |
| Disk I/O error during capture | Logged once, swallowed; perception loop continues |
| `max_mb` exceeded | Stop saving frames (events still recorded); log once |
| Corrupt frame during cleaning | Counted as `dropped_corrupt`; skipped |
| Unparseable JSONL record | Counted as `records_invalid`; quarantined; never crash |
| No frames after cleaning | Packaging writes an empty dataset + manifest with zero counts; exits 0 with a warning |
| Malformed `LabelEvent` | Rejected by `parse_client_message` (pydantic), never recorded |

## Testing

**Backend (pytest):**
- Recorder: sampling policy (saves on low-conf / novel-class / cadence; skips redundant);
  JSONL append shape; `max_mb` stop; flag-gated no-op; best-effort swallow on a forced I/O
  error; offline (no network). Uses small synthetic numpy frames written via cv2.
- Schema: `Observation`/`Event`/`Detection` round-trip + validation bounds.
- `LabelEvent`: `parse_client_message` accepts a valid event and rejects a malformed one;
  serialization shape matches the wire format.
- Cleaning: synthetic mission (a few generated jpgs incl. a blank + a near-duplicate + a
  degenerate box + an unparseable line) → exact report counts and the right survivors.
- Packaging: cleaned synthetic input → correct YOLO layout (`data.yaml`, label txt format,
  deterministic split), Gemma JSONL shape, manifest schema + counts; `correct`/`reject`
  events applied.

**Frontend (vitest):** `shared/contracts.ts` gains `LabelEvent`; a type-level/no-op check
that the union compiles (no runtime UI in this spec).

**Mobile (XCTest):** `LabelEvent` encodes to the exact wire shape the backend validates
(`ContractsTests`).

## Known limitation (operator-label loop is not fully closed in-app)

The live in-app label producer is the phone's follow-target confirm
(`FollowCoordinator.confirmTarget` → `LabelEvent{kind:"confirm", source:"follower",
label:nil}`). Two things make it telemetry-only today rather than a closed
training loop: (1) it carries no class label, and (2) capture records the
**leader** (Mavic) feed, while the confirm is **follower** (Tello) sourced — so
there is no captured frame for it to attach to. It is recorded (and counted in
`manifest.label_events.confirm`) but does not relabel any YOLO box.

The `correct`/`reject` → dataset path IS fully implemented and tested; it is just
driven by `LabelEvent`s carrying a class label (e.g. a future dashboard
detection-review UI on the leader feed, or a hand-authored `events.jsonl`). For
the demo, the correct/reject flywheel is shown via supplied events; closing the
in-app loop (a leader-feed detection-label affordance, or capturing the follower
feed too) is the recommended next step and is intentionally out of this scope.

## Non-goals

- No model training (`train_yolo.py`) — deferred.
- No Foundry upload (`export_to_foundry.py`) — deferred; only the Foundry-ready manifest is
  produced.
- No Gemma fine-tuning — only its example data is packaged.
- No live dashboard detection-review UI — operator labels come via `LabelEvent` (phone
  confirm/reject) now; richer labeling happens in the deferred curation step.
- No change to runtime perception behavior when capture is disabled.
