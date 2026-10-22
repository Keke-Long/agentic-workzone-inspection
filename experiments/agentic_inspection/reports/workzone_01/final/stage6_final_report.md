# Work Zone 01 — Stage 6 Final Inspection Report

- Method: `kg_plus_bm25` (KG + BM25, structured Stage 2)
- Selected MUTCD layout: `TA-30`
- Finalized requirements: 19
- Normative classes: Mandatory 6; Guidance 13
- Outcomes: satisfied 16; deficient 2; not_assessed 1
- Unique observed issues: 1

The `req_...` values are run-local traceability keys, not MUTCD identifiers. The authoritative citation for each row is the MUTCD source locator.

| # | Class | Outcome | Requirement | MUTCD source | Issue |
|---:|---|---|---|---|---|
| 1 | Mandatory | `satisfied` | Left-lane closure channelizing alignment (`req_8909b3bebda2c320`) | SEC-6N.11 paragraph 10; PDF page 888 |  |
| 2 | Mandatory | `satisfied` | Required merging transition (`req_b8a3cfc4703bff69`) | SEC-6N.11 paragraph 03; PDF page 887 |  |
| 3 | Guidance | `satisfied` | TA-30 figure:sign:W4-2L: W4-2L sign in TA-30 (`req_5081859b24526a1e`) | Figure 6P-30 (TA-30); PDF page 959; component sign:W4-2L; Guidance basis SEC-6P.01 paragraph 02 |  |
| 4 | Guidance | `satisfied` | TABLE-6B-1 table: advance warning sign dimensions A, B, and C (`req_38c3702227f46f58`) | TABLE-6B-1; PDF page 813 |  |
| 5 | Guidance | `satisfied` | SEC-6K.01 04: spacing between cones, tubular markers, vertical panels, drums, and barricades (`req_b93cf081b51794cc`) | SEC-6K.01 paragraph 04; PDF page 855 |  |
| 6 | Guidance | `deficient` | SEC-6K.01 14: Particular attention (`req_9684dd549b406cb8`) | SEC-6K.01 paragraph 14; PDF page 855 | [Issue 1](#issue-1--channelizing-device-condition) |
| 7 | Mandatory | `deficient` | SEC-6K.01 15: Channelizing devices that are no longer serviceable (see definition in Section 1C.02) (`req_f5310b80856ddc62`) | SEC-6K.01 paragraph 15; PDF page 855 | [Issue 1](#issue-1--channelizing-device-condition) |
| 8 | Guidance | `satisfied` | TABLE-6B-4 table: taper length L (`req_cafd11ed818bb74c`) | TABLE-6B-4; PDF page 815 |  |
| 9 | Guidance | `satisfied` | SEC-6L.06 03: If used, an arrow board (`req_a8c93c0420630ba5`) | SEC-6L.06 paragraph 03; PDF page 873 |  |
| 10 | Guidance | `satisfied` | SEC-6L.06 04: An arrow board (`req_23c001f1e68a3929`) | SEC-6L.06 paragraph 04; PDF page 873 |  |
| 11 | Mandatory | `satisfied` | SEC-6L.06 17: An arrow board in the arrow or chevron mode (`req_5f4e38b58f191dd6`) | SEC-6L.06 paragraph 17; PDF page 873 |  |
| 12 | Guidance | `satisfied` | SEC-6L.06 19: For a stationary lane closure, the arrow board (`req_2d715deec0e3e838`) | SEC-6L.06 paragraph 19; PDF page 873 |  |
| 13 | Guidance | `satisfied` | SEC-6H.03 01: The ROAD (STREET) WORK (W20-1) sign (see Figure 6H-1), which serves as a general warning of obstructions or restrictions (`req_1f5b96171b9b31be`) | SEC-6H.03 paragraph 01; PDF page 842 |  |
| 14 | Mandatory | `satisfied` | SEC-6H.07 02: For a single lane closure, the Lane Closed (W20-5) sign (see Figure 6H-1) (`req_1064e96c372ac190`) | SEC-6H.07 paragraph 02; PDF page 845 |  |
| 15 | Guidance | `satisfied` | TA-30 figure:sign:W20-5L: W20-5L sign in TA-30 (`req_37a99d2885c5d190`) | Figure 6P-30 (TA-30); PDF page 959; component sign:W20-5L; Guidance basis SEC-6P.01 paragraph 02 |  |
| 16 | Mandatory | `satisfied` | SEC-6L.06 25: Arrow boards (`req_b9abfc9121b3344e`) | SEC-6L.06 paragraph 25; PDF page 875 |  |
| 17 | Guidance | `not_assessed` | SEC-6H.02 01: Where highway conditions permit, warning signs (`req_3ff5962a4759ea94`) | SEC-6H.02 paragraph 01; PDF page 838 |  |
| 18 | Guidance | `satisfied` | TA-30 figure:sign:W20-1: W20-1 sign in TA-30 (`req_ac9833c628610286`) | Figure 6P-30 (TA-30); PDF page 959; component sign:W20-1; Guidance basis SEC-6P.01 paragraph 02 |  |
| 19 | Guidance | `satisfied` | SEC-6H.02 02: Where multiple advance warning signs are needed on the approach to a transition and activity area, the ROAD WORK AHEAD ( (`req_0d85e7ab52067b1a`) | SEC-6H.02 paragraph 02; PDF page 838 |  |

## Confirmed issues

### Issue 1 — Channelizing-device condition

I4844: large-area retroreflective-band loss; I5502: multiple retroreflective bands visibly damaged and peeling.

Normative requirements affected:

- **Guidance:** SEC-6K.01 paragraph 14; PDF page 855 — SEC-6K.01 14: Particular attention.
- **Mandatory:** SEC-6K.01 paragraph 15; PDF page 855 — SEC-6K.01 15: Channelizing devices that are no longer serviceable (see definition in Section 1C.02).

Evidence sources: `F0616_CAM_FRONT_LEFT_000`, `F0622_CAM_BACK_LEFT_000`.

#### Evidence images

##### I4844 — 反光带大面积脱落、缺失

Evidence frame `F0622_CAM_BACK_LEFT_000`; bounding box `[582.96, 731.69, 873.32, 1151.41]`.

![Evidence I4844 — 反光带大面积脱落、缺失](/home/data/workzone/work_zone_dataset/work_zone_data_nuScenes/scene-CATS-01/CAM_BACK_LEFT/cats001-2026-04-28-15-30-0500__CAM_BACK_LEFT__72266666.jpg)

##### I5502 — 多条反光带明显破损、剥离

Evidence frame `F0616_CAM_FRONT_LEFT_000`; bounding box `[747.66, 711.46, 1161.12, 1377.87]`.

![Evidence I5502 — 多条反光带明显破损、剥离](/home/data/workzone/work_zone_dataset/work_zone_data_nuScenes/scene-CATS-01/CAM_FRONT_LEFT/cats001-2026-04-28-15-30-0500__CAM_FRONT_LEFT__71633333.jpg)


## Assessment coverage gaps

These are evidence or measurement gaps, not observed deficiencies:

- 1: Numerical distance or geometry could not be validated.

## Completed geometric assessments

These measurements were completed in the evaluation stage; the Stage 2 requirement registry was not changed.

- **TABLE-6B-1; PDF page 813:** `satisfied` — A/B/C were approximately 270.8/249.8/219.4 ft; each exceeds the registered 100-ft urban low-speed recommendation.
- **TABLE-6B-4; PDF page 815:** `satisfied` — The fitted merging taper is approximately 158.7 ft long. With W=9.39 ft and S=30 mph, the registered formula gives L=140.9 ft.

## Interpretation

`not_assessed` means the registered requirement remained applicable but the bound evidence did not support a definitive satisfied/deficient decision. It is reported as a coverage gap, not as a work-zone problem and not as compliance.

## Completion

This report presents all 19 registered requirements. The Stage 2 normative registry is unchanged; documented evaluation-stage measurements replace the two earlier geometry coverage gaps.
