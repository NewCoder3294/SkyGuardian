# Foundry Setup — Exporting SkyGuardian Datasets

One-time setup to make `scripts/export_to_foundry.py` push a packaged dataset into
Palantir Foundry. This is a **post-mission, online, back-at-base** step — the live
mission runtime never touches Foundry.

The exporter pushes two things:
- **Ontology objects:** a `CaptureMission` summary + one `DetectionClass` per class
  (via the Actions API, idempotent create→edit upsert).
- **Dataset files:** `manifest.json` + `dataset.zip` (yolo/ + gemma/) into a backing
  Foundry Dataset (atomic SNAPSHOT transaction).

Everything is env-driven — nothing about the tenant is hardcoded.

---

## 1. Backing Dataset

Create (or choose) an empty Foundry Dataset to receive the files. Copy its RID →
this is `FOUNDRY_DATASET_RID`.

## 2. Ontology — create two object types

Use "Configure without datasource" / Edits-Enabled. Note the ontology RID →
`FOUNDRY_ONTOLOGY_RID`.

### `CaptureMission` — primary key `missionId`
| Property | Type |
|---|---|
| `missionId` (PK) | String |
| `classes` | String (comma-joined class list — **not** an array) |
| `datasetRid` | String |
| `createdT` | Double |
| `framesOut`, `trainCount`, `valCount`, `droppedCorrupt`, `droppedDuplicate`, `recordsInvalid`, `gemmaCount`, `gemmaLabeledCount`, `confirmCount`, `rejectCount`, `correctCount` | Integer |

### `DetectionClass` — primary key `classKey`
| Property | Type |
|---|---|
| `classKey` (PK, = `"<missionId>:<label>"`) | String |
| `missionId` | String |
| `label` | String |
| `count`, `train`, `val` | Integer |

## 3. Actions — let Foundry auto-generate them

Saving each object type auto-generates `create-`, `edit-`, and `delete-` actions.
Keep them. The exporter targets `create-capture-mission`, `edit-capture-mission`,
`create-detection-class`, `edit-detection-class` (override via env in step 5 if
yours differ).

**The primary key is the one thing to get right** (verified end-to-end against the
live tenant on 2026-05-30). A "configure without datasource" object exposes its PK
through *two differently-named inputs*, and Foundry does **not** name either after
your PK property — so the exporter remaps the PK onto the real input ids:

- **Create action — PK is a string parameter.** When you add it, Foundry defaults its
  input **id** to `new_parameter` even if you set the display name to `missionId` /
  `classKey`. You must (a) add this parameter and (b) in the create **Rule** set the
  PK property's `MAP TO` to this parameter — otherwise the PK gets a random UUID
  instead of your value. The exporter sends the PK under this id (default
  `new_parameter`; override with `FOUNDRY_MISSION_PK_PARAM` / `FOUNDRY_CLASS_PK_PARAM`).
- **Edit action — object located by an object-reference parameter.** Its input id is
  the **object type's API name** (`CaptureMission` / `DetectionClass`), not your PK.
  Leave it as auto-generated — **do not rename its id**, because the edit form's
  prefills reference it by id and renaming orphans them (5 "parameter used in prefill
  is missing" errors). The exporter locates the object under this id on re-runs
  (override with `FOUNDRY_MISSION_EDIT_LOCATOR` / `FOUNDRY_CLASS_EDIT_LOCATOR`).

All other parameters are auto-named camelCase matching the property names and need no
changes. Confirm the real input ids any time with:
`GET /api/v2/ontologies/{rid}/actionTypes/{action-api-name}` → the `parameters` map.

## 4. Token

Create a Foundry token (service account or personal) with **ontology write** +
**`api:datasets-write`** scopes → `FOUNDRY_TOKEN`. **Never commit it.**

## 5. Environment + run

```bash
export FOUNDRY_HOST=https://nicolasdossantos.usw-18.palantirfoundry.com
export FOUNDRY_TOKEN=...                          # from step 4 — keep secret
export FOUNDRY_ONTOLOGY_RID=ri.ontology.main.ontology....
export FOUNDRY_DATASET_RID=ri.foundry.main.dataset....

# Optional action-name / tuning overrides (defaults shown):
# export FOUNDRY_ACTION_MISSION=create-capture-mission
# export FOUNDRY_ACTION_CLASS=create-detection-class
# export FOUNDRY_ACTION_MISSION_EDIT=edit-capture-mission
# export FOUNDRY_ACTION_CLASS_EDIT=edit-detection-class
# PK input ids (see step 3 — defaults match a "configure without datasource" object):
# export FOUNDRY_MISSION_PK_PARAM=new_parameter        # create-capture-mission PK string input
# export FOUNDRY_CLASS_PK_PARAM=new_parameter          # create-detection-class PK string input
# export FOUNDRY_MISSION_EDIT_LOCATOR=CaptureMission   # edit-capture-mission object-ref input
# export FOUNDRY_CLASS_EDIT_LOCATOR=DetectionClass     # edit-detection-class object-ref input
# export FOUNDRY_TIMEOUT_S=30
# export FOUNDRY_MAX_RETRIES=3

# Validate config + payloads with ZERO mutations (writes export_report.json):
python3 scripts/export_to_foundry.py --dataset datasets/<name> --dry-run

# Real run:
python3 scripts/export_to_foundry.py --dataset datasets/<name>
```

A `datasets/<name>` is produced by the collect → clean → package pipeline:
`CAPTURE_ENABLED=1` during a mission → `scripts/clean_captures.py --mission <id>`
→ `scripts/package_dataset.py --mission <id> --out datasets/<name>`.

## 6. First-run check

The exporter is built against Foundry's documented v2 API and tested against mocks,
but the first real run is the first time it hits a live tenant. So:
1. Run `--dry-run` first and review `datasets/<name>/export_report.json`.
2. Do a real run on one small dataset.
3. Confirm in Foundry: the `CaptureMission` + `DetectionClass` objects appear, and
   `manifest.json` + `dataset.zip` land in the backing dataset.
4. If a call fails after objects were upserted, `export_report.json` records
   `partial_failure` so you know to reconcile.

## Boundary note

This exporter and `scripts/export_to_foundry.py` are **never imported by the live
server** (enforced by `backend/tests/test_foundry_isolation.py`), so enabling Foundry
export cannot add a network dependency to the offline mission runtime.
