# SkyGuardian × Palantir Foundry — Implementation Overview

A briefing for the presentation team. Covers what we built on Palantir, why it
matters, and how it works. The appendix has exact names, RIDs, and sample
outputs you can screenshot or quote.

---

## The one-sentence story

**SkyGuardian runs fully offline at the edge (no cloud, no internet, no GPS), and
Palantir Foundry is the back-at-base "institutional brain" that turns every
mission's raw recon captures into governed, queryable, AI-augmented intelligence.**

That split is the whole point:

```
   EDGE (offline, in the field)            BACK AT BASE (online, Foundry)
 +------------------------------+        +----------------------------------+
 | Mavic recon + Tello companion |       |  Foundry: the data flywheel +    |
 | YOLO detect · SLAM map        |  -->  |  institutional knowledge layer   |
 | on-device voice + follow      |       |  (Dataset->Pipeline->Ontology->AIP)|
 | NO cloud · NO internet · NO GPS|      |  Workshop app + our dashboard    |
 +------------------------------+        +----------------------------------+
```

The mission runtime **never** calls Foundry. A test (`test_foundry_isolation.py`)
enforces that the exporter is never imported by the live server, so enabling
Foundry cannot add a network dependency to the offline runtime. Foundry only
touches data *after* a mission, online, at base. This is a deliberate, defensible
architecture decision.

---

## Why it matters (the "so what")

A drone that flies once and forgets everything is a toy. The value compounds when
field data becomes a **flywheel**:

1. Each mission captures imagery + detections.
2. That data is cleaned, labeled, and packaged into **training data** (to make the
   next mission's YOLO/Gemma models better) **and** into **institutional memory**
   (what was seen, where, by which mission).
3. Foundry governs all of it: one ontology as the single source of truth,
   versioned pipelines, and an AI layer commanders can question in plain English.

The pitch is not "we used Palantir." It is: **"The edge stays dark and offline for
operational security; Foundry is where dismounted-unit recon becomes a force-wide,
AI-queryable knowledge base."**

---

## The data flywheel (4 stages)

```
 capture        ->  clean          ->  package              ->  export to Foundry
 (CaptureRecorder)  (dedup/filter)     (YOLO+Gemma+manifest)    (Ontology objects + Dataset files)
```

- **Capture** (live, on the laptop "brain"): samples Mavic frames + detections.
- **Clean**: drops corrupt/duplicate frames and low-confidence boxes.
- **Package**: builds an Ultralytics YOLO training set + Gemma examples + a
  `manifest.json` summary.
- **Export**: pushes everything into Foundry, idempotently (re-running a mission
  updates the existing objects, never duplicates).

Full runbook: [`DATA_FLYWHEEL.md`](DATA_FLYWHEEL.md). Setup: [`FOUNDRY_SETUP.md`](FOUNDRY_SETUP.md).

---

## The Palantir stack we built (one slide each)

**1. Foundry Dataset** — the backing store. Each mission's `manifest.json` +
`dataset.zip` (the packaged training data) land here as atomic snapshot
transactions.

**2. Ontology** — the single source of truth. Two object types:
- `CaptureMission` (one per mission: frame counts, train/val split, vouched-frame
  counts)
- `DetectionClass` (one per class per mission: person, vehicle, gun_truck, etc.)
- Built with auto-generated create/edit/delete **Actions**; the exporter upserts
  via the Actions API. **4 missions + 12 detection-class objects** are live now.

**3. Pipeline Builder** — `mission-intelligence` turns raw stats into *intelligence*:
- Input `missions-raw` -> **Add numbers** (`total_detections` = sum of all
  detection columns) + **Case** (`threat_level`: HIGH / MEDIUM / LOW from the
  vehicle + gun_truck + technical counts) -> output `missions-enriched`.
- Talking point: *"Foundry doesn't just store the data, it refines it. Derived
  threat scoring no human had to compute."*

**4. AIP Logic** — `askMissionData`, a live LLM function (GPT-5.4 inside Foundry).
Commanders ask natural-language questions ("which mission had the most vehicles?")
and get grounded, cited answers.
- **The clever bit** (good technical-depth slide): Foundry's RAG template relies on
  vector embeddings, but our ontology objects were configured *without a
  datasource*, so they have no embeddings and semantic search returned nothing. We
  solved it with **server-side grounding**: our app pulls the live ontology
  objects, builds a compact data context, and passes it into the AIP function
  alongside the question. Real Palantir AIP, grounded on real ontology data, no
  broken semantic search.

**5. Workshop** — `SkyGuardian Command`, a no-code Foundry operational app over the
same ontology (a Palantir-native front-end).

**6. Our branded dashboard** — a custom Next.js operator view (`/operator` ->
**Data** tab) reading the same Foundry ontology, with an "Ask the Data" box wired
to the AIP function. The Foundry token stays **server-side only** and never reaches
the browser.

---

## Demo flow (what to show, in order)

1. **Edge** -> drone detects entities offline, plots them on the local map (no GPS).
2. **Flywheel** -> "back at base, that mission flows into Foundry." Show the Dataset
   and the Ontology objects.
3. **Pipeline** -> show `missions-enriched` with the derived `threat_level` /
   `total_detections`.
4. **AIP** -> in our dashboard's Data tab, type "which mission has the most
   vehicles?" and get a live grounded answer with the AIP badge.
5. **Two front-ends** -> Workshop (Palantir-native) + our branded dashboard, both on
   the same ontology.

## Three talking points to memorize

- *"Offline at the edge for opsec; Foundry is the institutional brain at base."*
- *"It's a flywheel: every mission makes the next model smarter and the knowledge
  base richer."*
- *"Full Palantir stack: Dataset -> Pipeline -> Ontology -> AIP -> Workshop, plus a
  custom operational view, all on local, governed data."*

---

## Appendix — exact references

**Tenant / resources** (RIDs are safe to share; the token is not, keep it secret):
- Host: `https://nicolasdossantos.usw-18.palantirfoundry.com`
- Ontology RID: `ri.ontology.main.ontology.43f6be3a-769c-4187-b1c5-3b9e1d08e52c`
- Backing dataset RID: `ri.foundry.main.dataset.eada3999-b901-41d2-abf8-6c917b49b7d8`
- AIP function apiName: `askMissionData` (inputs: `question`, `context`; output: String; model: GPT-5.4)
- Pipeline: `mission-intelligence` -> output dataset `missions-enriched`

**Live ontology contents (current):**
- Missions (4): `demo1`, `overwatch-charlie`, `patrol-bravo`, `ridge-delta`
- Detection totals across all missions:
  `person=12, vehicle=11, gun_truck=5, rucksack=3, structure=3, antenna=2, technical=2, backpack=2`

**Object schemas:**
- `CaptureMission`: `missionId` (PK), `classes`, `datasetRid`, `createdT`,
  `framesOut`, `trainCount`, `valCount`, `gemmaCount`, `gemmaLabeledCount`,
  `confirmCount`, `correctCount`, `rejectCount`, plus drop/invalid counters.
- `DetectionClass`: `classKey` (PK, `"<missionId>:<label>"`), `missionId`, `label`,
  `count`, `train`, `val`.

**Sample AIP answers (verified live against the tenant):**
- Q: "Which mission has the most vehicles?"
  A: "overwatch-charlie has the most vehicles: 9 vehicle detections, plus 5
  gun_truck detections if counting armed vehicles separately."
- Q: "Summarize patrol-bravo."
  A: "patrol-bravo: 8 frames out, 6 train / 2 val, 7 vouched frames. Detections: 6
  persons, 3 rucksacks, 2 vehicles."
- Q: "Total person detections across all missions?"
  A: "12 (demo1 3 + overwatch-charlie 1 + patrol-bravo 6 + ridge-delta 2)."

**Pipeline derived fields:**
- `total_detections` = sum of the per-class detection columns.
- `threat_level` = HIGH if (vehicle + gun_truck + technical) >= 5, MEDIUM if >= 1,
  else LOW. Example: overwatch-charlie -> HIGH, ridge-delta -> LOW.

**Code touchpoints (for the engineering slide):**
- `frontend/src/lib/foundryServer.ts` — shared object fetch + context builder.
- `frontend/src/app/api/foundry/route.ts` — reads ontology objects (token server-side).
- `frontend/src/app/api/foundry/ask/route.ts` — grounds + calls the AIP function.
- `backend/app/capture/foundry_export.py` — the idempotent exporter (Actions + Dataset).
