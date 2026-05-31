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

## 3. Actions — create 4

`create-capture-mission`, `edit-capture-mission`, `create-detection-class`,
`edit-detection-class`.

**Two gotchas (verified on this tenant during the Mendacity build):**
- **Add the PK as a manual parameter** (`missionId` on the CaptureMission actions,
  `classKey` on the DetectionClass actions) to **both** create *and* edit, and bind
  it to the PK property. Foundry's auto-generated Create action omits the PK, but the
  exporter sends it.
- **All parameter API names must be camelCase**, exactly as the property names above
  (`missionId`, `framesOut`, `classKey`, …). Auto-generated params are already
  camelCased; the manually-added PK params you must type in camelCase.
- The exporter sends the **same full parameter set** to create and edit, so the edit
  action must accept all the same properties (auto-generated edit actions do — just
  add the PK param).

If your action API names differ from the defaults, override them with the env vars
in step 5.

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
