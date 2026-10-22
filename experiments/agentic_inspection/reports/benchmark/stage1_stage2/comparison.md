# Stage 1–2 five-method comparison after common-pipeline correction

> Historical five-method baseline. The KG + BM25 and KG + Dense rows were
> subsequently retested with the general Stage 2 coverage audit; use
> `stage2_coverage_audit_retest.md` for their current results.

## Controlled changes

All five methods use the same independently re-audited 15-item evaluator-only
reference, scene facts, six-domain framework, model, and Stage 2 contract.
No expected requirement ID, target citation, target count, or target wording is
present in the model prompt or retrieval query.

The common pipeline was changed in query-independent ways:

- table nodes use row-bounded normalized transcriptions instead of whole-page OCR;
- clause modality recovery uses the first direct operative verb when PDF columns
  separate a clause from its heading;
- scope filtering uses builder-produced predicate-level `scope_tags` and never
  scans arbitrary source spans for exclusion words;
- non-optional selected-TA figure components can carry the general 6P.01
  Guidance basis;
- KG expansion follows explicit references, manual identifiers, and generic
  manual category titles;
- Stage 2 asks for independently violable predicates rather than a smallest set;
- exclusion batches commit valid items independently;
- high-priority KG candidate dispositions are audited and reported. They are not
  blocking because the blocking experiment repeatedly exhausted the controller
  budget instead of improving requirement compilation.

## Corrected v2 result

| Method | Stage 1 candidate recall | Stage 2 recall among surfaced | End-to-end recall | Matched / gold | Registered | Activation precision | Invalid activations | Unresolved high-priority dispositions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| KG only | 100.0% | 53.3% | 53.3% | 8 / 15 | 10 | 80.0% | 1 | 7 |
| BM25 only | 13.3% | 100.0% | 13.3% | 2 / 15 | 3 | 66.7% | 0 | 0 |
| Dense only | 26.7% | 25.0% | 6.7% | 1 / 15 | 2 | 50.0% | 0 | 0 |
| KG + BM25 | 100.0% | 46.7% | 46.7% | 7 / 15 | 8 | 87.5% | 0 | 7 |
| KG + Dense | 100.0% | 53.3% | 53.3% | 8 / 15 | 10 | 80.0% | 1 | 7 |

## Resource result

| Method | Tokens | Wall time | Recorded cost |
|---|---:|---:|---:|
| KG only | 149,179 | 61.1 s | $0.03564 |
| BM25 only | 118,608 | 56.6 s | $0.02770 |
| Dense only | 214,725 | 111.6 s | $0.05151 |
| KG + BM25 | 342,411 | 74.6 s | $0.07037 |
| KG + Dense | 372,112 | 75.8 s | $0.08073 |

## Interpretation

The common Stage 1 corrections worked: all three KG methods surface all 15 gold
requirements. In this scene, KG-only already has 100% candidate recall, so neither
BM25 nor Dense adds gold recall. The retrieval-only methods perform poorly because
one broad domain query plus a bounded candidate set cannot reconstruct the selected
TA's structural relationships.

The remaining bottleneck is Stage 2, not retrieval. The model compiles only 7–8 of
15 already-visible requirements. It continues to collapse independently violable
predicates that share a device or evidence source, especially sign placement versus
sequence, maintenance versus replacement, formula versus functional taper adequacy,
and active-device placement versus system integration.

Dense does not outperform BM25 in the combined architecture here. Both combined
methods have 100% Stage 1 recall; KG + Dense costs more, while its final recall merely
matches KG-only. This single scene therefore supports KG as the main retrieval
structure and RAG as an audit layer, but does not justify choosing Dense over BM25.

The next improvement should be a general Stage 2 compiler/verifier evaluated across
multiple scenes. Continuing to tune retrieval against this scene would optimize the
wrong stage.
