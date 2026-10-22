# Frozen Stage 1–2 method definitions

Status: **frozen for the current study**  
Decision date: 2026-09-24  
Scene currently available: `scene-CATS-01`  
Normative reference: MUTCD 11th Edition (December 2023)

## Shared evaluation boundary

All methods receive the same selected TA record, frozen scene facts, six project inspection domains, model, reasoning effort, source index, candidate limits, and evaluator-only 15-item Case 1 reference. The reference is never supplied to a prompt, retriever, Knowledge Graph, or Stage 2 tool.

The six domains are:

1. lane-closure layout;
2. advance-warning sign system;
3. channelization system;
4. transition and taper geometry;
5. conditional active devices; and
6. conditional termination area.

Project-excluded scope remains pavement markings; buffer and activity area; positive protection and attenuators; nighttime visibility; pedestrian, bicycle, and accessibility; opposing-direction-only layouts; material/crashworthiness certification; sign mounting height; and product construction/capability specifications.

## Canonical Stage 2 for KG-based methods

Policy ID: `structured_candidate_decision_v1`

Stage 2 has two parts:

1. The agent may perform an initial compilation from the complete Stage 1 pool.
2. Every unresolved deterministic KG candidate is then presented once and must receive a structured decision containing:
   - activation status: `established`, `false`, or `unknown`;
   - independently violable: Boolean;
   - duplicate source node or null;
   - action: `retain` or `exclude`;
   - controlled decision basis and reason; and
   - measurement specification.

For retained candidates, the program binds canonical subject, relation, threshold, modality, applicability conditions, required inputs, source locator/span, and KG-derived activation evidence. A stale audit or an undecided presented candidate blocks Stage 2 sealing. The schema contains no benchmark IDs, answer wording, expected citations, or target count.

This policy is fixed despite its known precision tradeoff: on Case 1 both combined methods improved from 10/15 to 13/15 recall, while activation precision fell to 68.4% for KG + BM25 and 61.9% for KG + Dense. Both metrics must be reported.

## Fixed method matrix

| ID | Role | Stage 1A/1B | Stage 1C | Stage 2 | Primary comparison |
|---|---|---|---|---|---|
| `kg_plus_bm25` | Primary proposed method | Deterministic TA-core KG + scene-condition KG | BM25 gap retrieval, top 18/domain | `structured_candidate_decision_v1` | End-to-end |
| `agentic_kg_dense` | Proposed retrieval variant | Same KG layers | E5-large-v2 dense gap retrieval, top 18/domain | `structured_candidate_decision_v1` | End-to-end and retriever variant |
| `kg_only` | KG ablation baseline | Same KG layers | None | `structured_candidate_decision_v1` | KG contribution |
| `bm25_only` | Retrieval-only baseline | None | BM25, top 18/domain | Native free-form atomic registration | Stage 1 retrieval only |
| `dense_only` | Retrieval-only baseline | None | E5-large-v2 dense retrieval, top 18/domain | Native free-form atomic registration | Stage 1 retrieval only |

The retrieval-only baselines do not have deterministic KG candidates, so their Stage 2 output is not treated as a controlled end-to-end comparison with the KG-based structured compiler. Across all five methods, Stage 1 candidate recall is the fair retrieval metric. End-to-end Stage 2 comparisons are primary only among the three KG-based methods.

## Fixed configurations

- `config/workzone_01/stage1_kg_bm25.json`
- `config/workzone_01/stage1_kg_dense.json`
- `config/workzone_01/stage1_kg_only.json`
- `config/workzone_01/stage1_bm25_only.json`
- `config/workzone_01/stage1_dense_only.json`

Machine-readable hashes and roles are stored in `config/stage1_stage2_method_manifest.json`.

## Change-control rule

Future changes to retrieval, KG construction, candidate scope, Stage 2 schema, prompt contract, model, scene facts, MUTCD edition, candidate limit, or evaluation policy require a new method-definition version. Case 1 misses or false positives must not be converted into clause-specific prompt hints or hard-coded keywords under v1.
