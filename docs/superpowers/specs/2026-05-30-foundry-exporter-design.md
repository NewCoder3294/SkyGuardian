# SkyGuardian → Foundry Exporter — Design

**Date:** 2026-05-30 · **Track:** Post-mission data integration (Palantir Foundry)

## Goal

Push a packaged SkyGuardian dataset into the operator's Palantir Foundry tenant:
the manifest/summary as **Ontology objects** (via the Actions API) and the dataset
files into a **backing Foundry Dataset** (Datasets API). This is a post-mission,
back-at-base, online step — explicitly outside the offline mission runtime. Model
training on the data is out of scope (the manifest/dataset are seam-ready for it).

## Context

- The data flywheel (already on `main`) produces, per mission,
  `datasets/<name>/{yolo/, gemma/examples.jsonl, manifest.json, cleaning_report.json}`.
  `packaging.py` writes `manifest.json` as the stable "Foundry seam".
- Current manifest shape (`backend/app/capture/packaging.py`):
  `{v, created_t, mission_ids[], source_counts{leader,follower},
  yolo{path,classes[],train,val,format}, gemma{path,count,labeled_count},
  cleaning_report{frames_in,dropped_corrupt,dropped_duplicate,frames_out,
  boxes_in,boxes_dropped,records_invalid}, label_events{confirm,reject,correct}}`.
- The operator has a live Foundry tenant and SDK experience (the Mendacity build):
  Foundry auto-generates `create-<name>` / `edit-<name>` (kebab-case) actions and
  **camelCases** action parameters (`missionId`, not `mission_id`); PKs must be
  added as manual parameters. The exporter follows these conventions.
- `httpx` is already a backend dependency (used by the intel reasoner).

## Boundary (online is fine here)

The offline-first constraint governs the in-field mission runtime only. This
exporter is a post-mission tool: online, requires internet + Foundry credentials.
The only hard rule retained: the exporter module/script is **standalone and never
imported by the live server** (`app.server`), so turning it on cannot add a
runtime network dependency. Enforced by a test.

## Object types (operator creates these in Foundry; this spec defines them)

Created in the Foundry UI (object type + its `create-`/`edit-` actions). Parameter
API names are camelCase; the PK is added as a manual parameter.

**`CaptureMission`** — PK `missionId` (string).
| Property | Type | Source (manifest) |
|---|---|---|
| `missionId` | string | `mission_ids[0]` |
| `createdT` | double | `created_t` |
| `framesOut` | integer | `cleaning_report.frames_out` |
| `trainCount` | integer | `yolo.train` |
| `valCount` | integer | `yolo.val` |
| `classes` | string | `",".join(yolo.classes)` |
| `droppedCorrupt` | integer | `cleaning_report.dropped_corrupt` |
| `droppedDuplicate` | integer | `cleaning_report.dropped_duplicate` |
| `recordsInvalid` | integer | `cleaning_report.records_invalid` |
| `gemmaCount` | integer | `gemma.count` |
| `gemmaLabeledCount` | integer | `gemma.labeled_count` |
| `confirmCount` | integer | `label_events.confirm` |
| `rejectCount` | integer | `label_events.reject` |
| `correctCount` | integer | `label_events.correct` |
| `datasetRid` | string | `config.dataset_rid` (the backing dataset the files went to) |

Action: `create-capture-mission` (+ optional `edit-capture-mission` for upsert).

**`DetectionClass`** — PK `classKey` (= `"<missionId>:<label>"`).
| Property | Type | Source |
|---|---|---|
| `classKey` | string | `f"{missionId}:{label}"` |
| `missionId` | string | mission id (also enables a link to `CaptureMission`) |
| `label` | string | class name |
| `count` | integer | per-class detection count |
| `train` | integer | per-class train-split count |
| `val` | integer | per-class val-split count |

Actions: `create-detection-class` + `edit-detection-class` (the edit action enables
the idempotent re-run upsert). Optional link `DetectionClass → CaptureMission` on
`missionId`.

## Manifest enrichment (prerequisite, small change to packaging.py)

`DetectionClass` needs per-class counts, which the manifest doesn't carry today.
`packaging.py` already resolves every detection's effective label and assigns each
frame to train/val — so it can tally per class with no new pass. Add to the
manifest:

```json
"yolo": {
  "...": "...",
  "class_counts": {
    "<label>": {"count": <int>, "train": <int>, "val": <int>}
  }
}
```

`count` = total detections of that class across kept frames; `train`/`val` = count
of that class restricted to frames in each split. This is additive (existing keys
unchanged); existing packaging tests stay green, plus a new test asserting
`class_counts` totals match `yolo.train`/`yolo.val` per class.

## Components

### `backend/app/capture/foundry_export.py`
- `FoundryConfig` — built from env, validated (missing required field → error):
  `host` (`FOUNDRY_HOST`), `token` (`FOUNDRY_TOKEN`), `ontology_rid`
  (`FOUNDRY_ONTOLOGY_RID`), `dataset_rid` (`FOUNDRY_DATASET_RID`); action-name
  overrides `mission_action` (`FOUNDRY_ACTION_MISSION`, default
  `create-capture-mission`), `class_action` (`FOUNDRY_ACTION_CLASS`, default
  `create-detection-class`), `mission_edit_action`
  (`FOUNDRY_ACTION_MISSION_EDIT`, default `edit-capture-mission`),
  `class_edit_action` (`FOUNDRY_ACTION_CLASS_EDIT`, default `edit-detection-class`)
  for idempotent upsert; and tuning `timeout_s` (`FOUNDRY_TIMEOUT_S`, default 30)
  and `max_retries` (`FOUNDRY_MAX_RETRIES`, default 3).
- `build_mission_params(manifest, dataset_rid) -> dict` — manifest → camelCase
  params for `CaptureMission` (pure).
- `build_class_params(manifest) -> list[dict]` — one camelCase param dict per
  class from `yolo.class_counts` (pure).
- `FoundryClient` — thin `httpx` wrapper, **injectable** (constructed from
  `FoundryConfig`; tests pass a mock or an httpx `MockTransport`). Sets an explicit
  `timeout_s` on every request and retries transient failures (connect/read
  timeouts, 429, 5xx) up to `max_retries` with exponential backoff; never retries
  non-transient 4xx (auth/validation). Backoff sleep is injected (a no-op in tests)
  so retry tests stay fast and deterministic.
  - `preflight() -> None` — one cheap authenticated GET (e.g. the ontology metadata
    endpoint) to fail fast on a bad host/token before any mutation.
  - `apply_action(action_api_name, params) -> dict` →
    `POST {host}/api/v2/ontologies/{ontology_rid}/actions/{action_api_name}/apply`
    body `{"parameters": params}`, `Authorization: Bearer {token}`.
  - `upload_dataset_file(dataset_rid, logical_path, data: bytes) -> None` → Foundry
    v2 Datasets upload. Exact endpoint pinned against Foundry's OpenAPI during
    implementation; all HTTP lives here so the rest is transport-agnostic.
- `upsert_action(client, create_name, edit_name, params) -> str` — idempotent helper:
  apply `create_name`; on a PK/already-exists conflict (Foundry validation error),
  apply `edit_name` instead. Returns `"created"` or `"edited"`. Re-running the whole
  export is therefore safe (no duplicates, no hard-fail).
- `validate_manifest(manifest) -> None` — fail fast with a clear message if the
  manifest is missing required keys (`mission_ids`, `yolo.class_counts`,
  `cleaning_report`, `label_events`, …) before any network call.
- `export_dataset(dataset_dir, client, config, *, dry_run=False, report_t=0.0) -> dict` — orchestration (`report_t` is injected by the CLI so the module has no clock dependency, mirroring the manifest's `created_t`):
  1. Read + `validate_manifest`.
  2. `client.preflight()` (skipped in dry_run).
  3. For each class: `upsert_action(client, config.class_action, config.class_edit_action, build_class_params(...)[i])`.
  4. `upsert_action(client, config.mission_action, config.mission_edit_action, build_mission_params(...))`.
  5. Upload `manifest.json` and a zip of the dataset (`yolo/` + `gemma/`).
  6. Write `export_report.json` into `dataset_dir` (objects upserted with
     created/edited status + any returned RIDs, files uploaded, timestamp).
  7. Return the report dict.
  In **dry_run**, steps 1 and the payload builds run normally but every network
  call (preflight/apply/upload) is skipped; the report records what *would* be sent
  (action names + params + file list) and is written with `"dry_run": true`. This
  lets the operator validate config + payloads against a live tenant's expectations
  without mutating anything.

### `scripts/export_to_foundry.py`
Thin CLI: `--dataset datasets/<name>` and `--dry-run`. Loads `FoundryConfig` from
env, builds the real `FoundryClient`, stamps `report_t` (current time), calls
`export_dataset(..., dry_run=args.dry_run, report_t=...)`, prints the report.
Missing env → clear error + non-zero exit. Documents required env vars in `--help`.

## Error handling

| Condition | Behavior |
|---|---|
| Missing/empty required env var | `FoundryConfig` raises a clear error; CLI exits non-zero before any network call |
| Bad host/token | `preflight()` fails fast (~1 request) before any mutation |
| Malformed manifest | `validate_manifest` raises a clear error before any network call |
| `apply_action` PK conflict (object exists) | `upsert_action` applies the edit-action instead (idempotent re-run) |
| Transient failure (timeout, 429, 5xx) | retried up to `max_retries` with exponential backoff |
| `apply_action` non-transient 4xx (auth/validation) | not retried; raised with status + Foundry error body (token redacted) |
| Dataset upload failure | report which file failed; objects already upserted are recorded in `export_report.json` |
| `--dry-run` | builds + validates payloads, skips all network calls, writes a `"dry_run": true` report |

Token is never logged; error bodies are emitted but the `Authorization` header is
never included in any log/exception.

## Testing

**Backend (pytest, all offline — mock the client/HTTP):**
- `build_mission_params` / `build_class_params`: a sample manifest → expected
  camelCase param dicts (incl. PK params `missionId`, `classKey`).
- `FoundryConfig`: env present → populated; each missing required var → error.
- `export_dataset` against a **mock `FoundryClient`** recording calls: asserts
  preflight ran, one class upsert per class with correct params, one mission upsert
  with correct params, `manifest.json` + dataset zip uploaded, and an
  `export_report.json` written with the upsert statuses/files.
- `upsert_action`: create succeeds → `"created"`; create raises a PK-conflict →
  edit applied → `"edited"`.
- `validate_manifest`: a manifest missing a required key raises before any client call.
- **Retries:** `FoundryClient` over an httpx `MockTransport` that returns 503 twice
  then 200 → succeeds after retries (injected no-op sleep); a 401 → raises
  immediately (no retry).
- **Dry-run:** `export_dataset(dry_run=True)` against a mock client makes ZERO
  network calls (no preflight/apply/upload) yet writes a `"dry_run": true` report
  listing intended actions + params + files.
- `FoundryClient.apply_action`/`preflight` URL/headers/body via httpx
  `MockTransport`: correct path, Bearer header, `{"parameters": ...}` body.
- Manifest enrichment: `class_counts` present and totals consistent with
  `yolo.train`/`yolo.val`.
- **Import-isolation:** `import app.server` does not import
  `app.capture.foundry_export` (runtime stays Foundry-free / offline-safe).
- **Honest gap:** no live-tenant test from CI/here — a documented manual step the
  operator runs with real creds + the created object types.

## Non-goals

- Model training (out of scope).
- Creating the object types/actions in Foundry (operator does this in the UI; this
  spec provides the exact schema).
- AIP / agent / Workshop wiring.
- Uploading individual image files (the dataset goes up as one zip + the manifest);
  exploding the zip into a Foundry table is a later step.
