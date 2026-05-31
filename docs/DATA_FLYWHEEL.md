# Data Flywheel — Capture → Clean → Package → Foundry

How a flown mission becomes curated training/analysis data in Palantir Foundry.
Four stages; only the first runs during a live mission (on the laptop brain), the
rest are **back-at-base, online** steps.

```
 LIVE (offline, on the brain)        BACK AT BASE (online)
┌───────────────┐   ┌─────────┐   ┌──────────┐   ┌──────────────────┐
│   capture     │ → │  clean  │ → │ package  │ → │ export to Foundry│
│ CaptureRecorder│   │ filter  │   │ YOLO +   │   │ objects + files  │
│ (opt-in)      │   │ + dedup │   │ Gemma    │   │ (Actions/Datasets)│
└───────────────┘   └─────────┘   └──────────┘   └──────────────────┘
 captures/<id>/      cleaned/       datasets/<id>/   CaptureMission +
                                                     DetectionClass objs
```

The live runtime never imports the exporter (enforced by
`backend/tests/test_foundry_isolation.py`), so enabling the flywheel adds **no**
network dependency to an offline mission.

---

## Stage 1 — Capture (live, opt-in)

Off by default. Enable it when launching the brain:

```bash
CAPTURE_ENABLED=1 CAPTURE_MISSION_ID=alpha-2026-05-30 backend/run.sh
```

`CaptureRecorder` (`backend/app/capture/recorder.py`) is wired into the perception
loop (`backend/app/perception/pipeline.py`) and records to
`captures/<CAPTURE_MISSION_ID>/`:

- **`frames/NNNNNN.jpg` + `observations.jsonl`** — sampled Mavic (`"leader"`) frames
  with their YOLO detections + SLAM pose. Sampling policy: a frame is kept on
  `low_conf` (any box below `CAPTURE_LOW_CONF`), `novel_class` (a label not seen
  before this run), or `cadence` (≥ `CAPTURE_CADENCE_S` since the last save).
- **`events.jsonl`** — operator label decisions (`confirm` / `reject` / `correct`)
  arriving over the WebSocket. These are the supervision signal: corrections rename
  classes and rejections drop boxes downstream.

**Best-effort by design:** every disk write is wrapped — a capture failure is logged
and swallowed, never crashing or stalling the live perception/WS loop. The JPEG
encode + disk write runs off-thread.

Knobs (env): `CAPTURE_MISSION_ID` (default `mission`), `CAPTURE_CADENCE_S`
(`2.0`), `CAPTURE_LOW_CONF` (`0.4`), `CAPTURE_MAX_MB` (`2000`; frame writes pause
when the budget is hit, observations continue).

### Two operating rules (verified by reading the wiring)

1. **Use a unique `CAPTURE_MISSION_ID` per mission.** `observations.jsonl` and
   `events.jsonl` are opened in append mode, so reusing an id merges two missions'
   data into one directory.
2. **Don't restart the brain mid-mission with the same id.** The frame counter and
   byte budget live in memory and reset to 0 on restart, so frames would overwrite
   (`frames/000000.jpg` again) while observations keep appending. If you must
   restart, bump `CAPTURE_MISSION_ID` (e.g. `alpha-2026-05-30-b`). Cleaning's
   perceptual-hash dedup mitigates accidental overlap but is not a substitute.

Only Mavic (`leader`) frames are captured — the recon sensor. The Tello follower
feed is not recorded (it is a companion sensor, not a data source).

---

## Stage 2 — Clean

```bash
backend/.venv/bin/python scripts/clean_captures.py --mission alpha-2026-05-30
```

`clean_mission` (`backend/app/capture/cleaning.py`) reads
`captures/<id>/observations.jsonl`, drops corrupt/blank and near-duplicate frames
(8×8 average-hash, Hamming threshold `--dup-threshold`), drops degenerate /
low-confidence boxes (`--conf-floor`), and quarantines unparseable records (never
crashes). Writes `captures/<id>/cleaned/observations.jsonl` + an auditable
`cleaning_report.json`.

---

## Stage 3 — Package

```bash
backend/.venv/bin/python scripts/package_dataset.py \
  --mission alpha-2026-05-30 --out datasets/alpha-2026-05-30 \
  --val-frac 0.25 --created-t "$(date +%s)"
```

`package_dataset` (`backend/app/capture/packaging.py`) turns cleaned observations +
events into:

- **`yolo/`** — Ultralytics layout (`images/{train,val}`, `labels/{train,val}`,
  `data.yaml`). Train/val split is a deterministic hash of the frame path (no RNG).
  Operator `correct` events rename classes; `reject` events drop those boxes.
- **`gemma/examples.jsonl`** — one prompt/answer example per frame; a gold answer is
  written only for frames an operator `confirm`/`correct` vouched for.
- **`manifest.json`** — the summary the Foundry exporter reads (class counts, split
  sizes, label-event tallies, cleaning report). Plus `cleaning_report.json`.

---

## Stage 4 — Export to Foundry

Validate payloads first (zero network calls), then push:

```bash
# load FOUNDRY_HOST / FOUNDRY_TOKEN / FOUNDRY_ONTOLOGY_RID / FOUNDRY_DATASET_RID first
backend/.venv/bin/python scripts/export_to_foundry.py --dataset datasets/alpha-2026-05-30 --dry-run
backend/.venv/bin/python scripts/export_to_foundry.py --dataset datasets/alpha-2026-05-30
```

Pushes a `CaptureMission` summary object + one `DetectionClass` per class (idempotent
create→edit upsert) and uploads `manifest.json` + `dataset.zip` into a backing
Foundry Dataset. Setup, env vars, and the action/primary-key specifics are in
[`FOUNDRY_SETUP.md`](FOUNDRY_SETUP.md). Re-running the same mission updates the
existing objects rather than duplicating them; an `export_report.json` records the
outcome (and `partial_failure` if the file upload fails after objects were upserted).

---

## End-to-end smoke test (no hardware)

Synthesize a raw mission, then run the whole pipeline — useful to validate the chain
without a drone (this is exactly how the integration was verified):

```bash
# 1. write captures/demo1/{frames,observations.jsonl,events.jsonl} by hand
#    (matching backend/app/capture/schema.py)
backend/.venv/bin/python scripts/clean_captures.py --mission demo1
backend/.venv/bin/python scripts/package_dataset.py --mission demo1 --out datasets/demo1 --created-t "$(date +%s)"
backend/.venv/bin/python scripts/export_to_foundry.py --dataset datasets/demo1 --dry-run
```

`captures/<id>/` and `datasets/` are git-ignored (local generated artifacts).
