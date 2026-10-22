# Project handoff

## Current milestone

Work Zone 01 is the completed reference case.

- Scene: `scene-CATS-01`.
- Selected MUTCD Typical Application: TA-30.
- Physical interpretation: left single-lane closure with a merging taper; no
  lane shift and no opposing-direction crossover.
- Registered requirements: 19.
- Final statuses: 16 `satisfied`, 2 `deficient`, 1 `not_assessed`.
- Deficiencies: MUTCD 6K.01 paragraphs 14 and 15, both supported by the same
  comprehensive channelizing-device review.
- Confirmed damaged devices: I4844 in `F0622_CAM_BACK_LEFT_000` and I5502 in
  `F0616_CAM_FRONT_LEFT_000`.

The remaining `not_assessed` item is the highway-conditions warning-sign
provision retained by the frozen Stage 2 output. It is visible as a method
limitation; it was not silently removed during final reporting.

## Stage boundaries

| Stage | Output | Rule |
|---|---|---|
| 0 | Applicable TA selection | Choose only TA-1 through TA-54 from retrieved evidence. |
| 1 | Candidate normative provisions | KG supplies deterministic candidates; BM25 or Dense only fills gaps. |
| 2 | Atomic applicable requirements | Every KG candidate receives a structured retain/exclude decision. |
| 3 | Data-availability and acquisition plan | No compliance conclusion. |
| 4 | Evidence and measurements | Evidence is bound to requirement keys. |
| 5 | `satisfied`, `deficient`, or `not_assessed` | One conclusion per registered requirement. |
| 6 | Final records and report | Presentation only; no new applicability reasoning. |

Stage outputs are immutable inputs to the next stage. If a defect originates
upstream, rerun from that stage instead of editing Stage 6.

## Canonical artifacts

The retained artifact tree is intentionally small:

```text
artifacts/workzone_01/
├── benchmark/stage1_stage2/
│   ├── kg_plus_bm25/
│   ├── kg_plus_dense/
│   ├── kg_only/
│   ├── bm25_only/
│   └── dense_only/
└── pipeline/
    ├── stage3/
    ├── stage4/
    ├── stage5/
    ├── stage6/
    └── final_evaluated/
```

For every model run, retain `result.json`, `stage_1_to_6_registry.json`,
`tool_trace.json`, `raw_responses.json`, `request_manifest.json`,
`resource_usage.json`, measurements, and the Stage 0 record. Do not retain
per-turn payload copies, `_in_progress` duplicates, or every checkpoint after
a run has sealed successfully.

## Adding a new case

1. Produce a `current_scene_v1` manifest. Scene facts must use `null` for
   unknown—not `false`. Accepted observations must include provenance, image
   path, class, bbox, and geometry fields when geometry is usable.
2. Put scene-specific paths in `data_sources`, especially
   `device_inventory`. Optional `dataset_root` and `metadata_root` override
   automatic path inference.
3. Run `scaffold_workzone.py`; never copy and hand-edit Work Zone 01 artifacts.
4. Independently audit MUTCD applicability and replace the generated pending
   reference. Keep this reference evaluator-only.
5. Run the selected Stage 1 method, followed by Stages 3–6 in order. Run
   preflight before every API execution.
6. Run the same five Stage 1–2 methods if the case will be included in the
   paper comparison.

## What is shared and what is case-specific

Shared across cases:

- six inspection domains and project exclusions;
- MUTCD 11th Edition structure index and Knowledge Graph;
- Stage 2 structured-decision schema;
- tool schemas, status vocabulary, and evaluation code;
- five-method comparison boundary.

Case-specific:

- scene facts, sensor metadata, images, observations, and device inventory;
- Stage 0 TA selection;
- activated requirements and evidence plan;
- independent evaluator reference and final report.

Do not add clause-specific prompt keywords to make a missed requirement pass.
Method improvements must be structural and must be rerun across all available
cases.

## Known limitations

- Only one completed scene exists today, so claims about generalization remain
  provisional until Work Zones 02 and 03 are complete.
- The geometry adapter expects nuScenes-style metadata. Other datasets require
  an adapter, not case-specific edits inside the inspection logic.
- Work Zone 01's materializer reads its existing review/adjudication sources;
  the scaffold expects later cases to provide an already materialized scene.
- The active-requirement reference is an independent project reference, not a
  formally certified expert Ground Truth. Reports must preserve that wording.

## Cleanup boundary

Removed development assets included Stage 1 v1–v21, Stage 3/4/5 repair runs,
obsolete preflight outputs, duplicate `current_*` reports, payload folders,
and checkpoint folders. These deletions are not recoverable from this
workspace because it is not a Git worktree. The canonical results and paper
comparison outputs listed above were retained.
