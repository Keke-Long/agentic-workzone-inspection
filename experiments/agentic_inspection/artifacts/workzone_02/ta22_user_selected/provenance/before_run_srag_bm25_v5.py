#!/usr/bin/env python3
"""Execute the single authorized S-RAG-BM25 v5 development test."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from api_client import credentials, image_data_url, output_text, post_json
from inspection_registry_v5 import COVERAGE_DOMAINS
from project_common import ROOT, sha256
from srag_bm25_tools_v5 import (
    ToolGatewayV5, retrieval_tool_definitions,
    scene_tool_definitions,
)


STAGE1_DOMAIN_FRAMEWORK = {
    "lane_closure_layout": {
        "purpose": "overall lane-closure configuration and traffic-path redirection",
        "review_dimensions": ["Typical Application context", "transition mechanism",
                              "closed-lane-side channelization placement"],
    },
    "advance_warning_sign_system": {
        "purpose": "the advance-warning system shown or implied by the selected layout",
        "review_dimensions": ["sign use/presence", "legend and closure-direction consistency",
                              "placement relative to the work/closure", "encounter sequence",
                              "spacing applicability"],
    },
    "channelization_system": {
        "purpose": "the channelizing-device system that defines the transition and closed lane",
        "review_dimensions": ["spacing in each alignment type", "condition and maintenance",
                              "response to no-longer-serviceable devices"],
    },
    "transition_and_taper_geometry": {
        "purpose": "the operational function and geometry of the merging transition",
        "review_dimensions": ["driver warning/merge adequacy", "length criteria and formula applicability"],
    },
    "conditional_active_devices": {
        "purpose": "active devices only when their presence is established by scene facts",
        "review_dimensions": ["device applicability", "permitted operating mode/direction",
                              "placement and integration with other TTC devices"],
    },
    "conditional_termination_area": {
        "purpose": "termination controls only when their physical predicate is established",
        "review_dimensions": ["downstream taper", "termination signing"],
    },
}


CONFIG_PATH = ROOT / "config/workzone_01/stage1_kg_bm25.json"
MUTCD_TYPICAL_APPLICATION_CODES = tuple(f"TA-{number}" for number in range(1, 55))
MUTCD_TYPICAL_APPLICATION_CODE_SET = frozenset(MUTCD_TYPICAL_APPLICATION_CODES)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stage0_schema() -> dict:
    return {
        "type": "object", "additionalProperties": False,
        "required": ["scene_id", "layout_selection_status", "selected_layouts", "missing_scene_fields", "selection_reason"],
        "properties": {
            "scene_id": {"type": "string"},
            "layout_selection_status": {"enum": ["determined", "indeterminate"]},
            "selected_layouts": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["layout_code", "layout_role", "source_locator", "matched_scene_facts", "conflicting_scene_facts"],
                "properties": {
                    "layout_code": {"type": "string", "enum": list(MUTCD_TYPICAL_APPLICATION_CODES)},
                    "layout_role": {"enum": ["primary_applicable", "cross_reference_only"]},
                    "source_locator": {"type": "string"},
                    "matched_scene_facts": {"type": "array", "items": {"type": "string"}},
                    "conflicting_scene_facts": {"type": "array", "items": {"type": "string"}},
                },
            }},
            "missing_scene_fields": {"type": "array", "items": {"type": "string"}},
            "selection_reason": {"type": "string"},
        },
    }


def validate_stage0_selection(record: dict, indexed_source_codes: set[str] | None = None) -> None:
    """Reject invalid or internally inconsistent Stage 0 layout selections."""
    if not isinstance(record, dict):
        raise ValueError("Stage 0 selection must be an object")
    status = record.get("layout_selection_status")
    if status not in {"determined", "indeterminate"}:
        raise ValueError("Stage 0 layout_selection_status must be determined or indeterminate")
    layouts = record.get("selected_layouts")
    if not isinstance(layouts, list):
        raise ValueError("Stage 0 selected_layouts must be an array")
    codes = [row.get("layout_code") for row in layouts if isinstance(row, dict)]
    if len(codes) != len(layouts):
        raise ValueError("Every Stage 0 selected layout must be an object with layout_code")
    invalid = sorted({code for code in codes if code not in MUTCD_TYPICAL_APPLICATION_CODE_SET})
    if invalid:
        raise ValueError(f"Stage 0 selected layout codes must be TA-1 through TA-54: {invalid}")
    duplicates = sorted(code for code, count in Counter(codes).items() if count > 1)
    if duplicates:
        raise ValueError(f"Stage 0 selected layout codes must be unique: {duplicates}")
    if indexed_source_codes is not None:
        absent = sorted(set(codes) - set(indexed_source_codes))
        if absent:
            raise ValueError(f"Stage 0 selected layout codes are absent from the manual index: {absent}")
    primary = [row for row in layouts if row.get("layout_role") == "primary_applicable"]
    if status == "determined" and len(primary) != 1:
        raise ValueError("A determined Stage 0 selection must contain exactly one primary_applicable layout")
    if status == "indeterminate" and primary:
        raise ValueError("An indeterminate Stage 0 selection cannot contain a primary_applicable layout")


def public_scene_input(scene: dict, data_manifest: dict) -> dict:
    scene_facts = dict(scene["scene_facts"])
    for key, value in data_manifest.get("derived_scene_facts", {}).items():
        if not key.endswith("_provenance") and value is not None:
            scene_facts[key] = value
    return {
        "scene_id": scene["scene_id"], "scene_facts": scene_facts,
        "scene_data_manifest": data_manifest,
        "accepted_bbox_count": data_manifest["counts"]["accepted_bbox_observations"],
        "perception_evidence_policy": scene["perception_evidence_policy"],
    }


def stage0_prompt(scene_view: dict) -> str:
    return (
        "Stage 0 — autonomous scene understanding and primary MUTCD Typical Application selection. No correct "
        "Typical Application, manual page, "
        "region, internal requirement ID, or inspection target is supplied. Search the complete manual using the "
        "structured BM25 tools. Generate natural-language queries from the frozen scene facts, inspect additional "
        "sections/Typical Applications with continuation when needed, and distinguish a directly applicable primary "
        "Typical Application from a cross-reference. Put the selected manual-native TA code in layout_code "
        "for schema compatibility. A missing fact is layout-blocking only when it prevents choosing among mutually exclusive "
        "primary Typical Applications. If the best-matching TA itself states a conditional augmentation for a higher, lower, "
        "or otherwise unknown condition, keep that TA as primary and preserve the unresolved condition for later requirement "
        "applicability instead of demoting the whole TA. Return indeterminate only when the primary TA itself cannot be selected; "
        "list missing fields and do not guess. "
        "You must call search_manual at least once before returning JSON.\nScene input:\n" +
        json.dumps(scene_view, ensure_ascii=False, sort_keys=True)
    )


def workflow_prompt(scene_view: dict, selected_layouts: list[dict]) -> str:
    facts = scene_view.get("scene_facts", {})
    posted_speed = facts.get("posted_speed_mph")
    speed_instruction = (
        f"The frozen scene fact posted_speed_mph={posted_speed} may be cited as scene-fact evidence for "
        "speed-dependent conclusions; never substitute vehicle speed for posted speed. "
        if posted_speed is not None else
        "Posted speed is unknown; use the authorized acquisition tools when a speed-dependent predicate requires it, "
        "and never substitute vehicle speed for posted speed. "
    )
    direction_instruction = (
        "Opposite-direction image coverage is unavailable, so omit opposite-direction-only inspection items rather than guessing. "
        if facts.get("opposite_direction_image_coverage") is False else ""
    )
    return (
        "Stages 1–6 — strict staged autonomous inspection. Human handoff is forbidden and "
        "requires_human_review must always be false. The registry exposes only tools legal in the current phase. "
        "Stage 1: retrieve the manual and discover structured requirements. Stage 2: call "
        "begin_requirement_registration, register requirements supported by already retrieved nodes, close all regions, "
        "then seal registration. Each accepted requirement receives a run-local discovered_requirement_key generated by "
        "the registry. Stage 3: record required-input availability for every registered key together with planned_tools, "
        "a concrete planned_evidence_strategy, and a planned_decision_rule, then seal availability. "
        "Stage 4: acquire visual evidence and call any normative measurement only with that returned key; thresholds, "
        "conditions, and source provenance come exclusively from the registered requirement. Then seal measurements. "
        "Stage 5: form conclusions, then begin result submission. Stage 6: submit one result per registered key and "
        "finalize. You cannot return to an earlier phase. There is no normal retrieval-call, tool-call, or retrieved-character "
        "budget; use pagination during Stage 1 and follow only explicit cross-reference edges.\n\n"
        "For Stage 1, first expand the selected Typical Application without a region filter so the complete notes and figure "
        "OCR and frozen source-page image are visible. Follow every explicit table, section, and Typical Application reference needed to interpret its "
        "symbols. Search the full manual for governing provisions for the control-device classes present in the accepted "
        "observation inventory. Stage 1 is complete when the selected TA has been fully paged, the needed explicit references "
        "have been expanded, and each observed device class has a governing clause or one documented no-candidate search. "
        "Do not issue paraphrased variants of a completed information need. Do not treat an empty region-filtered expansion "
        "as proof that the diagram lacks that region. "
        "Screen every registry region for the model-selected primary Typical Application and applicable MUTCD sections, but "
        "retain concise atomic requirements that have a concrete, later-evaluable compliance predicate and are valuable and "
        "plausibly inspectable rather than trying to exhaust every proposition. Do not register background classification, "
        "an inapplicable alternative, or a purely optional device as its own inspection item. Never replace atomic "
        "items with an overall setup conclusion. Submit required_inputs with each requirement. For every retained item, "
        "plan data acquisition before abstaining. A null value in scene_facts is unknown, not necessarily unavailable. "
        "Use temporal-image, accepted-bbox, sensor-sync, lidar, calibration, pose, trajectory, geometry, and posted-speed "
        "tools as appropriate after availability is sealed. `unavailable_after_attempt` is allowed only after the corresponding tool was actually called; "
        "otherwise use `not_attempted`, which is an acquisition failure. Keep normative applicability separate from data "
        "availability and image assessability.\n\n"
        "A satisfied/deficient item must cite valid accepted observation evidence. For distance, spacing, taper, buffer, or "
        "placement checks, apply the operational clear-violation-only policy: if the relevant devices are observable and no "
        "clear material error is evident, mark satisfied; mark deficient only when reliable visual or measured evidence "
        "establishes a clear material violation. Encode extracted thresholds in measurement_spec during registration; never "
        "pass a threshold directly to a measurement tool. "
        "A distance or width deficiency is permitted only when semantic endpoint roles are correct, the tool validates the "
        "longitudinal or road-normal direction, and the complete confidence interval lies beyond the violation threshold. "
        "Otherwise treat the result as no obvious error, not as a deficiency. Measurement uncertainty by itself is not a "
        "reason to abstain. Save and cite measurements when useful, but a satisfied distance item does not require survey-grade measurement. "
        "For a discovered channelizer-spacing requirement, first register its structured conditions and formula, then call the "
        "generic full-line spacing measurement with the returned key. Do not manually choose pairs or calculate distances. "
        "Activate a device-specific requirement family only when the current scene establishes that device's deployment. "
        "Do not infer a PCMS from an Arrow Board, an invalidated observation, or a superseded classification. A null deployment "
        "fact is unknown rather than present. Inspect the current accepted observation and nearby temporal frames for any "
        "device whose deployment is established. "
        + speed_instruction
        + direction_instruction
        + "After checking coverage, retrieve or acquire more data if another high-value item appears checkable. Finalize only "
        "when regions are closed and the completion record truthfully describes unresolved work.\n\n"
        f"Model-selected MUTCD Typical Applications from Stage 0: {json.dumps(selected_layouts, ensure_ascii=False)}\n"
        f"Scene input: {json.dumps(scene_view, ensure_ascii=False, sort_keys=True)}"
    )


def stage1_stage2_scoped_prompt(scene_view: dict, selected_layouts: list[dict]) -> str:
    """Prompt for the isolated discovery test without perception/inventory leakage."""
    scoped_scene = {
        "scene_id": scene_view.get("scene_id"),
        "scene_facts": scene_view.get("scene_facts", {}),
    }
    return (
        "Isolated Stage 1–2 MUTCD requirement-discovery test. The only inspection scope is the six coverage "
        f"domains listed below: {json.dumps(list(COVERAGE_DOMAINS), ensure_ascii=False)}. "
        "Use only the supplied scene facts, the supplied primary Typical Application, and manual evidence returned "
        "by the structured retrieval tools. No observation inventory, bounding boxes, images, hidden checklist, target "
        "requirement IDs, target counts, or expected citations are supplied. Unknown scene facts remain unknown. "
        "Do not infer device presence merely because a device could be used.\n\n"
        "The domain framework below is a search-coverage reference, not a list of answers. It tells you which classes of "
        "questions to investigate, but it does not establish that a requirement exists, applies, or has any particular "
        "modality. Discover those details only from retrieved MUTCD nodes.\n"
        f"Stage 1 domain framework: {json.dumps(STAGE1_DOMAIN_FRAMEWORK, ensure_ascii=False)}\n\n"
        "Stage 1 uses three layers. Stage 1A: call load_ta_core_graph once to deterministically traverse the selected TA's "
        "diagram components, explicit references, inbound governing sections, and reachable Standard/Guidance provisions. "
        "Stage 1B: call load_scene_condition_graph once to activate requirement families from true scene facts, accepted "
        "component classes, and device use required by TA-core provisions. Unknown and false facts do not trigger a family. "
        "Stage 1C: call audit_graph_gaps for every one of the six domains. This BM25 layer searches only normative nodes not "
        "already reached by Stage 1A/1B and is a completeness audit, not the main requirement generator. The program removes "
        "zero-score and low-relative-relevance tail nodes without imposing a candidate-count cap. Review every returned page "
        "until has_more is false; do not attempt to enumerate the excluded corpus tail. A non-optional component in a "
        "selected Typical Application can be Guidance when its returned node carries the manual-derived normative_basis; "
        "optional figure content remains context rather than a required predicate. "
        "Option/may and Support statements may be used only to interpret applicability and must not be registered as "
        "requirements. The following domains are excluded: pavement markings; buffer and activity area; positive "
        "protection and attenuators; nighttime visibility and illumination; pedestrian, bicycle, and accessibility; "
        "opposing-direction-only layout; material certification and full crashworthiness certification; and sign "
        "mounting height without reliable height evidence. After reviewing each domain, call record_domain_discovery "
        "with its layer-by-layer summary and every graph or gap candidate that remains plausibly applicable and field-inspectable after the stated "
        "project-scope exclusions. Stage 1 is recall-oriented: when applicability is uncertain, retain the candidate for explicit Stage-2 disposition rather than dropping it. "
        "There is no per-domain candidate-count ceiling. Registration cannot begin until all six ledger entries "
        "are closed. Candidate sources must have been returned for that same domain by Stage 1A, 1B, or 1C.\n\n"
        "Stage 2: register every activated in-scope provision with submit_atomic_requirement_batch. Supply one retrieved "
        "source_node_id from a governing section and an atomic compliance predicate; the program binds the canonical modality, locator, and source "
        "span. Supply an activation_basis: unconditional for provisions activated by the basic scene configuration; "
        "scene_fact with non-null fact keys for conditional devices actually present; selected_ta with retrieved TA "
        "activation evidence; or combined when both non-null scene facts and selected-TA evidence establish applicability. "
        "For scene_fact, evidence_source_node_ids may be empty or contain retrieved governing-section nodes, but not TA nodes. "
        "For selected_ta, fact_keys must be empty. Unknown or false facts do not activate a condition. Register requirements supported by source nodes "
        "retrieved in this run. Preserve conditional provisions when their predicate can be evaluated from the supplied "
        "facts or the primary TA; do not activate a condition that cannot be established. Distinguish an activation trigger "
        "from the later compliance observation. Device presence activates provisions whose antecedent is simply that the "
        "device is used; it does not establish a narrower antecedent requiring a particular display mode, operating state, "
        "roadway condition, or configuration. Once the actual antecedent is established, unknown compliance observations "
        "are missing Stage-3/4 data and must not cause the provision to be dropped. Use only literal non-null keys present "
        "in scene_facts; describe logical implications in "
        "the explanation instead of inventing synthetic fact keys. A non-optional selected-TA figure_component with a "
        "returned normative_basis may be submitted as a Guidance source; a figure component without that basis may only "
        "serve as activation evidence. Do not turn an optional depicted sign, work vehicle, or device into a standalone "
        "requirement. Do not register a conditional 'if used' provision when the condition remains unknown. Each record must express one "
        "independently testable normative predicate; the program-assigned modality must resolve to shall or should. Apply one general atomicity test without a predeclared target count: "
        "split a source paragraph only when its subjects, conditions, relations, or thresholds can be inspected and decided independently; otherwise keep it as one predicate. "
        "Never split or merge merely to match an expected checklist shape. For any conditional device, distinguish the fact that activates a provision from later observations of operation, condition, or placement. "
        "A partial-success "
        "batch has already committed its accepted records: repair only the explicitly rejected records. Do not add "
        "device construction, certification, or display-capability specifications unless this field-arrangement inspection can "
        "evaluate them. Do not infer missing classification or geometric inputs solely from a TA title. A conditional quantitative rule "
        "whose activation input is absent differs from an activated arrangement rule whose compliance observation is merely pending. Every source_node_id placed in "
        "a domain discovery ledger must receive an explicit Stage-2 disposition: either support at least one registered "
        "requirement or be submitted to exclude_discovery_candidate_batch with a permitted reason. Unknown later inspection "
        "evidence is not a permitted reason to exclude an otherwise activated provision. Avoid semantic duplicates. Close all six domains "
        "and seal requirement registration. Stop immediately after Stage 2 is sealed.\n\n"
        "Stage 1 graph contract: deterministic TA core first, deterministic scene-condition activation second, then one or more uncovered-node gap-audit pages per domain.\n"
        f"Primary MUTCD Typical Application: {json.dumps(selected_layouts, ensure_ascii=False)}\n"
        f"Scene facts: {json.dumps(scoped_scene, ensure_ascii=False, sort_keys=True)}"
    )


def simplified_stage1_stage2_prompt(scene_view: dict, selected_layouts: list[dict],
                                    gap_retrieval: dict | None = None) -> str:
    """Prompt for a concise problem-discovery-oriented Stage 1–2 run."""
    gap_retrieval = gap_retrieval or {"method": "bm25"}
    gap_method = gap_retrieval.get("method", "bm25")
    architecture = gap_retrieval.get("architecture", "kg_plus_retrieval")
    gap_description = (
        "dense cosine retrieval over E5-embedded normative atomic provisions"
        if gap_method == "dense_e5" else
        "BM25 retrieval over normative atomic provisions"
    )
    scoped_scene = {
        "scene_id": scene_view.get("scene_id"),
        "scene_facts": scene_view.get("scene_facts", {}),
    }
    if architecture == "kg_only":
        stage1_instructions = (
            "Stage 1 is KG-only. Call load_ta_core_graph once and then "
            "load_scene_condition_graph once. Do not perform lexical or dense retrieval. "
            "After both graph layers are loaded, begin requirement registration."
        )
    elif architecture == "retrieval_only":
        stage1_instructions = (
            "Stage 1 is retrieval-only and does not expose Knowledge Graph traversal. "
            "Call load_domain_gap_candidates once for each of the six domains; the configured "
            f"retriever is {gap_description}. Each broad domain query is ranked against the same "
            "complete normative-provision corpus. The program performs ranking, candidate limiting, "
            "paging, and project-scope filtering internally. After all six domain calls, begin "
            "requirement registration."
        )
    else:
        stage1_instructions = (
            "Stage 1 has three transparent layers. Call load_ta_core_graph once. Then call "
            "load_scene_condition_graph once. Then call load_domain_gap_candidates once for each "
            f"of the six domains; the configured Stage 1C method is {gap_description}. The program "
            "performs ranking, candidate limiting, paging, and project-scope filtering internally. "
            "After all six domain calls, begin requirement registration."
        )
    stage2_audit_instructions = ""
    if architecture in {"kg_plus_retrieval", "kg_only"}:
        stage2_audit_instructions = (
            "After the initial compilation, call audit_stage2_candidate_coverage. Review every returned deterministic KG "
            "candidate with submit_stage2_candidate_decision_batch. For each candidate explicitly state whether its activation "
            "antecedent is established, whether it can be violated independently, whether it duplicates another predicate, "
            "and retain or exclude it with a reason. The program binds canonical predicate text and source provenance and "
            "directly registers retained decisions. Submit a decision for every pending candidate. Then call the audit again; "
            "seal only when new_candidate_count and pending_structured_decision_count are both zero. "
        )
    return (
        "Simplified Stage 1–2 MUTCD problem-discovery test. Work only within these six inspection domains: "
        f"{json.dumps(list(COVERAGE_DOMAINS), ensure_ascii=False)}. The goal is a small, clear set of executable field "
        "inspection checks that can reveal distinct work-zone problems; the goal is not to reproduce every applicable "
        "manual clause or any hidden checklist shape. No target IDs, target citations, or target count are supplied.\n\n"
        f"{stage1_instructions} Do not run "
        "free-form searches and do not build or close a candidate ledger. After all six domain calls, begin requirement "
        "registration. The six-domain framework is a coverage guide, not a list of answers: "
        f"{json.dumps(STAGE1_DOMAIN_FRAMEWORK, ensure_ascii=False)}\n\n"
        "Stage 2 compiles retrieved provisions into the complete set of distinct, currently applicable field inspection "
        "predicates. Use submit_inspection_check_batch. Do not optimize for a target count. Register every applicable "
        "predicate that can be violated independently; shared evidence, a shared measurement tool, or related subject "
        "matter is not by itself a reason to merge predicates. Combine branches only when they are inseparable conditions "
        "or thresholds of the same compliance decision. "
        "Preserve the canonical shall/should modality supplied by the program and keep a concrete MUTCD source. "
        "A true component-presence fact activates provisions whose antecedent is that the component is used, even when "
        "the later compliance observation is unknown. It does not establish a narrower antecedent requiring a particular "
        "mode, state, roadway condition, or configuration. Unknown or false presence facts do not activate a family. "
        "Exclude pavement markings; buffer and activity area; positive protection and attenuators; nighttime visibility; "
        "pedestrian, bicycle, and accessibility; opposing-direction-only layouts; material/crashworthiness certification; "
        "sign mounting height; and device product construction or capability specifications. Do not include a general "
        "manual statement unless it can produce a distinct field finding in this scene. Semantic duplicates expressing "
        "the same subject, condition, relation, threshold, and modality should be merged; requirements that differ on any "
        "of those dimensions remain separate. Non-optional components of the selected Typical Application may serve as "
        "Guidance sources when the returned node carries a normative_basis from the manual. "
        f"{stage2_audit_instructions}Mark all six regions screened, seal registration, "
        "and stop immediately after Stage 2.\n\n"
        f"Primary Typical Application: {json.dumps(selected_layouts, ensure_ascii=False)}\n"
        f"Scene facts: {json.dumps(scoped_scene, ensure_ascii=False, sort_keys=True)}"
    )


def _usage(responses: list[dict]) -> dict:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cached_tokens": 0}
    for response in responses:
        usage = response.get("usage") or {}
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            totals[key] += int(usage.get(key, 0) or 0)
        details = usage.get("input_tokens_details") or {}
        totals["cached_tokens"] += int(details.get("cached_tokens", 0) or 0)
    return totals


def _sanitize_result(result: dict, max_chars: int) -> tuple[dict, list[str]]:
    images = list(result.get("_image_paths", []))
    clean = {key: value for key, value in result.items() if key != "_image_paths"}
    serialized = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > max_chars:
        raise RuntimeError(f"single tool response exceeded technical ceiling: {len(serialized)} > {max_chars}")
    return clean, images


def _response_payload(cfg: dict, instructions: str, input_items: list[dict], tools: list[dict],
                      schema: dict | None, tool_choice: str = "auto") -> dict:
    payload: dict[str, Any] = {
        "model": cfg["model"], "instructions": instructions, "input": input_items,
        "tools": tools, "tool_choice": tool_choice, "parallel_tool_calls": False,
        "reasoning": {"effort": cfg["reasoning_effort"]},
        "max_output_tokens": cfg["max_output_tokens_per_turn"], "store": False,
    }
    if schema:
        payload["text"] = {"format": {"type": "json_schema", "name": "stage0_layout_selection",
                                       "strict": True, "schema": schema}}
    return payload


def _run_stage0(cfg: dict, scene_view: dict, key: str, base_url: str, out: Path) -> tuple[dict, ToolGatewayV5, list[dict], float]:
    gateway = ToolGatewayV5([], scene_manifest=cfg["scene_manifest"])
    input_items = [{"role": "user", "content": [{"type": "input_text", "text": stage0_prompt(scene_view)}]}]
    responses: list[dict] = []
    latency = 0.0
    for turn in range(1, cfg["emergency_stage0_turn_ceiling"] + 1):
        payload = _response_payload(
            cfg,
            "Select MUTCD Typical Applications only from manual evidence retrieved from the full index. Never emit benchmark IDs.",
            input_items, retrieval_tool_definitions(), stage0_schema(), "required" if turn == 1 else "auto",
        )
        payload_dir = out / "payloads"
        payload_dir.mkdir(parents=True, exist_ok=True)
        (payload_dir / f"stage_0_{turn:04d}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )
        response, elapsed = post_json(f"{base_url}/v1/responses", key, payload)
        responses.append(response); latency += elapsed
        (out / "stage_0_raw_responses_in_progress.json").write_text(
            json.dumps(responses, ensure_ascii=False, indent=2) + "\n"
        )
        calls = [item for item in response.get("output", []) if item.get("type") == "function_call"]
        if not calls:
            record = json.loads(output_text(response))
            validate_stage0_selection(record, set(gateway.retrieval.unit_by_code))
            (out / "stage_0_layout_selection.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            return record, gateway, responses, latency
        input_items.extend(response.get("output", []))
        for call in calls:
            args = json.loads(call.get("arguments", "{}"))
            result = gateway.call(call["name"], args)
            (out / "stage_0_tool_trace_in_progress.json").write_text(
                json.dumps(gateway.trace, ensure_ascii=False, indent=2) + "\n"
            )
            clean, _ = _sanitize_result(result, cfg["single_tool_response_max_chars"])
            input_items.append({"type": "function_call_output", "call_id": call["call_id"],
                                "output": json.dumps(clean, ensure_ascii=False)})
    raise RuntimeError("budget_exhausted/method_failure: emergency Stage 0 ceiling triggered")


def _write_checkpoint(out: Path, gateway: ToolGatewayV5) -> None:
    checkpoint = out / "state_checkpoints" / f"checkpoint_{len(gateway.trace):04d}.json"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(json.dumps(gateway.registry.snapshot(), ensure_ascii=False, indent=2) + "\n")


def _workflow_state_packet(scene_view: dict, layouts: list[dict], gateway: ToolGatewayV5,
                           scoped_stage1_stage2: bool = False) -> str:
    snapshot = gateway.registry.snapshot()
    availability = snapshot.get("data_availability", {})
    compact_requirements = [{key: row.get(key) for key in (
        "discovered_requirement_key", "candidate_label", "region", "subject", "modality", "relation",
        "threshold", "applicability_conditions", "required_inputs", "measurement_spec", "source_locator",
    )} for row in snapshot["requirements"]]
    pending_availability = [row for row in compact_requirements
        if row["discovered_requirement_key"] not in availability]
    unresolved = [row for row in snapshot["requirements"] if row.get("inspection_status") == "not_assessed" and
                  row.get("final_data_availability") in {None, "not_evaluated"}]
    completed = [{"discovered_requirement_key": row["discovered_requirement_key"],
                  "inspection_status": row.get("inspection_status"),
                  "final_data_availability": row.get("final_data_availability")}
                 for row in snapshot["requirements"] if row.get("discovered_requirement_key") not in
                 {value.get("discovered_requirement_key") for value in unresolved}]
    retrieval_progress, nodes, layout_hits, edges, seen_requests = [], {}, {}, {}, set()
    retrieval_tools = {"search_manual", "search_manual_for_need", "expand_source_unit",
                       "follow_cross_reference", "read_source_node", "load_ta_core_graph",
                       "load_scene_condition_graph", "audit_graph_gaps",
                       "load_domain_gap_candidates"}
    for trace_row in gateway.trace:
        if trace_row["tool"] not in retrieval_tools:
            continue
        request_key = json.dumps([trace_row["tool"], trace_row["arguments"]], sort_keys=True)
        if request_key not in seen_requests:
            seen_requests.add(request_key)
            result = trace_row["result"]
            retrieval_progress.append({
                "tool": trace_row["tool"], "arguments": trace_row["arguments"],
                "returned_count": len(result.get("items", [])), "has_more": result.get("has_more"),
                "atomic_item_count": len(result.get("atomic_items", [])),
                "graph_candidate_count": len(result.get("candidates", [])),
                "next_continuation_token": result.get("continuation_token"),
            })
        for item in (trace_row["result"].get("items", []) +
                     trace_row["result"].get("atomic_items", []) +
                     trace_row["result"].get("candidates", [])):
            if item.get("source_node_id"):
                nodes[item["source_node_id"]] = item
            elif item.get("edge_id"):
                edges[item["edge_id"]] = item
            elif item.get("source_unit_code"):
                layout_hits[item["source_unit_code"]] = {key: item.get(key) for key in (
                    "source_unit_code", "unit_type", "title", "chapter", "figure_code", "source_pages", "printed_pages"
                )}
    compact_measurements = [{key: row.get(key) for key in (
        "status", "measurement_id", "measurement_type", "value", "unit", "uncertainty",
        "confidence_interval", "associated_image_ids", "associated_bbox_ids", "quality_flags", "failure_reason",
        "deficiency_supported", "threshold_assessment", "thresholds_applied",
    )} for row in gateway.scene.measurements.values()]
    inspected_visual_source_ids: set[str] = set()
    stage4_observation_inventory: dict[str, dict] = {}
    stage4_temporal_indices: dict[str, set[int]] = {}
    for trace_row in gateway.trace:
        result = trace_row.get("result", {})
        if result.get("status") == "failure":
            continue
        if trace_row.get("tool") == "get_reviewed_observations":
            arguments = trace_row.get("arguments", {})
            inventory_key = (
                f"{arguments.get('reviewed_class') or 'all'}|"
                f"representative={bool(arguments.get('representative_per_entity'))}"
            )
            stage4_observation_inventory[inventory_key] = {
                "total": result.get("total"),
                "next_cursor": result.get("next_cursor"),
                "observations": [{key: row.get(key) for key in (
                    "observation_id", "frame", "camera", "reviewed_class",
                    "refined_element_id", "raw_device_id",
                )} for row in result.get("observations", [])],
            }
        if trace_row.get("tool") == "inspect_observation_images":
            for observation in result.get("observations", []):
                if observation.get("observation_id"):
                    inspected_visual_source_ids.add(observation["observation_id"])
                if observation.get("source_image"):
                    inspected_visual_source_ids.add(Path(observation["source_image"]).stem)
        elif trace_row.get("tool") == "inspect_temporal_images":
            inspected_visual_source_ids.update(
                image.get("image_id") for image in result.get("images", []) if image.get("image_id")
            )
            arguments = trace_row.get("arguments", {})
            channel = arguments.get("channel")
            start = int(arguments.get("start_cursor", 0))
            count = int(arguments.get("count", 0))
            stride = int(arguments.get("stride", 1))
            stage4_temporal_indices.setdefault(channel, set()).update(
                range(start, start + count * stride, stride)
            )
    observation_class_counts = Counter(
        row.get("reviewed_class", "unknown") for row in gateway.scene.observations.values()
    )
    visible_scene = ({"scene_id": scene_view.get("scene_id"),
                      "scene_facts": scene_view.get("scene_facts", {})}
                     if scoped_stage1_stage2 else scene_view)
    state = {
        "current_phase": snapshot["phase"], "scene": visible_scene, "selected_layouts": layouts,
        "region_coverage": snapshot["region_coverage"],
        "registered_requirement_count": len(snapshot["requirements"]),
        "registered_requirement_records": compact_requirements,
        "pending_data_availability_requirements": pending_availability,
        "data_availability_records": availability,
        "uninspected_requirement_records": unresolved,
        "completed_inspection_summary": completed,
        "retrieval_progress_do_not_repeat_identical_calls": retrieval_progress,
        "retrieved_manual_nodes": list(nodes.values()),
        "retrieved_layout_hits": list(layout_hits.values()),
        "followed_cross_reference_edges": list(edges.values()),
        "six_domain_discovery_ledger": gateway.discovery_coverage,
        "discovery_candidate_exclusions": gateway.discovery_candidate_exclusions,
        "actual_tools_called": [row["tool"] for row in gateway.registry.tool_calls],
        "tool_failures_so_far": gateway.tool_failures,
    }
    if snapshot["phase"] in {"measurement", "inspection_conclusion", "result_submission", "finalized"}:
        bundle_rows = list(snapshot.get("inspection_bundles", {}).values())
        inspected_visual_source_ids.update(
            source_id for bundle in bundle_rows for source_id in bundle.get("source_ids", [])
        )
        state.update({
            "stage4_evidence_records": list(snapshot.get("evidence_records", {}).values()),
            "stage4_inspected_visual_source_ids": sorted(inspected_visual_source_ids),
            "stage4_observation_inventory": stage4_observation_inventory,
            "stage4_temporal_frame_indices": {
                channel: sorted(indices) for channel, indices in stage4_temporal_indices.items()
            },
            "saved_measurements": compact_measurements,
            "stage4_acquisition_plan": snapshot.get("stage4_plan"),
            "stage4_inspection_bundles": [{key: row.get(key) for key in (
                "inspection_bundle_id", "visual_job_id", "role", "job_type", "source_ids",
                "reviewed_classes", "relevant_requirement_keys", "underlying_tool", "item_count",
                "model_observation",
            )} for row in bundle_rows],
            "stage4_acquisition_attempts": list(
                snapshot.get("acquisition_attempts", {}).values()
            ),
            "stage5_conclusion_plan": snapshot.get("stage5_plan"),
            "stage5_conclusion_drafts": list(
                snapshot.get("conclusion_drafts", {}).values()
            ),
            "stage5_readiness": snapshot.get("stage5_readiness"),
        })
    if not scoped_stage1_stage2:
        state.update({
            "information_need_search_ledger": gateway.information_need_searches,
            "information_need_expansion_ledger": gateway.information_need_expansions,
            "accepted_observation_class_counts": dict(sorted(observation_class_counts.items())),
            "accepted_bbox_observations": list(gateway.scene.observations.values()),
            "saved_speed_evidence": list(gateway.scene.speed_evidence.values()),
        })
    else:
        state.update({
            "knowledge_graph_manifest": gateway.knowledge_graph.manifest(),
            "stage1a_ta_core_loaded": gateway.graph_stage1a_result is not None,
            "stage1b_scene_conditions_loaded": gateway.graph_stage1b_result is not None,
            "stage1b_activated_components": (
                gateway.graph_stage1b_result.get("activated_component_ids", [])
                if gateway.graph_stage1b_result else []
            ),
            "stage1c_graph_gap_audit_ledger": {
                domain: [{
                    "query": page.get("query"),
                    "returned_count": len(page.get("items", [])),
                    "has_more": page.get("has_more"),
                    "continuation_token": page.get("continuation_token"),
                } for page in pages]
                for domain, pages in gateway.graph_gap_audits.items()
            },
            "graph_candidate_counts_by_domain": {
                domain: len(node_ids)
                for domain, node_ids in gateway.graph_candidate_node_ids.items()
            },
        })
    return (
        "Persistent local state after the last tool call is below. Continue Stages 1–6 from this state. "
        "Do not recreate accepted requirements or inspections and do not repeat an identical retrieval/list call already "
        "shown in retrieval progress; correct a rejected batch and continue. "
        "Follow the current phase exactly.\n" +
        json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    )


def phase_contract(phase: str, stop_before_measurement: bool,
                   stop_after_requirement_registration: bool = False,
                   scoped_stage1_stage2: bool = False,
                   simplified_inspection_checks: bool = False,
                   stop_after_measurements: bool = False,
                   orchestrated_stage4: bool = False,
                   orchestrated_stage5: bool = False,
                   stop_after_conclusions: bool = False,
                   stage1_architecture: str = "kg_plus_retrieval") -> str:
    contracts = {
        "requirement_discovery": (
            "STAGE 1 CONTRACT — INPUT: frozen scene facts, selected primary TA, full-manual retrieval tools, and prior "
            "retrieval state. OUTPUT: enough retrieved source nodes to support each retained atomic requirement, followed "
            "by begin_requirement_registration. First expand the selected TA without a region filter so its complete notes "
            "and figure OCR are visible. Then follow its explicit table/section/application cross-references and search the "
            "full manual for governing provisions for each device or control type visible in the TA figure or listed in the "
            "accepted-observation class inventory. An empty region-filtered TA expansion means the index has no node tagged "
            "with that region; it does not prove the figure contains no such element. Use only natural-language/manual-native "
            "queries. COMPLETION: begin registration once (a) the selected TA has been fully paged, (b) its explicit "
            "cross-references needed to interpret the diagram have been expanded, and (c) each observed control-device "
            "class has either a retrieved governing clause or one documented no-candidate search. Do not reformulate and "
            "repeat the same information need after its ranked results have already been returned. A continuation_token is "
            "bound to the exact query or expansion arguments that produced it; reuse it only with those arguments. Do not register until "
            "discovery is complete; do not measure or inspect scene evidence."
        ),
        "requirement_registration": (
            "STAGE 2 CONTRACT — INPUT: only source nodes already returned in Stage 1 and current accepted requirement "
            "keys. OUTPUT: atomic submit_requirement_batch records, terminal coverage for every region, then "
            "seal_requirement_registration. source_node_ids must be retrieved hashes; source_locator must exactly equal "
            "the selected node locator; source_span must be a non-empty contiguous excerpt copied from that node. Never "
            "resubmit an accepted requirement. Retain only a concrete compliance predicate that the later inspection could "
            "evaluate; do not register background support, classification prose, an inapplicable alternative, or a purely "
            "optional device as a standalone inspection item. A figure-depicted sign, placement, sequence, taper, or device "
            "line can be retained when its retrieved source node exposes the supporting figure text. For every measured rule, "
            "measurement_spec.tool and every threshold/formula must be explicit. No scene or measurement tool is allowed."
        ),
        "data_availability": (
            "STAGE 3 CONTRACT — INPUT: frozen registered requirements, scene manifest/facts, and already accepted "
            "availability records. OUTPUT: exactly one assessment for each unassessed requirement, then "
            "seal_data_availability. REQUIRED INVARIANT for every row: set(available_inputs) union set(missing_inputs) "
            "must exactly equal that requirement's required_inputs and the two sets must be disjoint. Copy required_inputs "
            "before classifying them. condition_data_complete refers only to whether every applicability condition can be "
            "resolved from frozen facts and the selected TA; it does not mean that visual or measurement inputs have already "
            "been acquired. It may be true while data_availability is partial or not_attempted. available_direct means no "
            "required input is missing; partial requires both available and missing inputs; not_attempted means all required "
            "inputs remain missing but can be pursued in Stage 4. unavailable_after_attempt is forbidden in Stage 3 because "
            "evidence acquisition has not begun. "
            "The manifest's derivable_local list establishes feasibility only, not an acquired semantic input. Raw images, "
            "bbox records, lidar, trajectory, or calibration do not make an Observed..., Measured..., sign-legend, display-mode, "
            "device-condition, device-position, work-space-location, taper-location, or similar interpretation available. "
            "Keep such a required input in missing_inputs until the corresponding Stage 4 inspection or measurement tool "
            "actually returns the semantic result. A required input may be available_direct only when a non-null frozen scene "
            "fact or inventory field directly states that same value; cite that exact fact or inventory field. "
            "planned_tools must include measurement_spec.tool when data is usable; give a concrete evidence strategy and "
            "decision rule. Use get_scene_data_manifest and other inventory tools to distinguish direct, locally derivable, "
            "and absent data, but do not treat an inventory lookup as visual evidence. Never resubmit an accepted availability "
            "key. Do not call visual or geometry measurement tools."
        ),
        "measurement": (
            "STAGE 4 CONTRACT — INPUT: frozen requirements, Stage 3 plans, scene inventory, and the persistent evidence "
            "ledger. OUTPUT: factual evidence records accounting for every required input, all registered normative "
            "measurement attempts, then seal_measurements. Use filtered representative observation inventory to select "
            "relevant signs, channelizers, and active devices. An accepted bbox establishes only class and candidate "
            "location; inspect its image before recording a visual finding. Immediately call record_evidence_batch after "
            "each useful image group so findings survive later turns. Evidence findings must describe observed facts and "
            "limitations, not satisfied/deficient conclusions. "
            "Do not reacquire a required input already listed as available in its accepted Stage 3 record. "
            "Use inventory pagination conservatively and never request more candidates than are needed for the next image inspection. "
            "Before declaring sign evidence unresolved, inspect every representative traffic-sign entity returned by the filtered "
            "inventory. Inspect every accepted Arrow Board candidate and at least one representative from each present channelizer "
            "class. Also inspect at least 8 CAM_FRONT frames spanning at least 70 percent of the traversal so absence claims are not "
            "based only on the beginning of the route. Cite the relevant accepted observation IDs in sign and Arrow Board evidence. "
            "Measurement tools may be called only with the registered "
            "requirement key and only when that requirement's measurement_spec names that exact tool. If acquisition fails "
            "or a planned tool is not authorized by the frozen measurement_spec, record the input as unresolved with an "
            "acquisition_failure evidence record. Before sealing, the union of acquired_inputs and unresolved_inputs across "
            "each requirement's evidence records must exactly cover its required_inputs."
        ),
        "inspection_conclusion": "STAGE 5 CONTRACT — form conclusions from registered requirements and bound evidence.",
        "result_submission": "STAGE 6 CONTRACT — submit exactly one autonomous result per registered key and finalize.",
        "finalized": "The registry is finalized; call no further tools.",
    }
    contract = contracts[phase]
    if orchestrated_stage4 and phase == "measurement":
        contract = (
            "ORCHESTRATED STAGE 4 — The program owns coverage, tool authorization, source binding, and input accounting. "
            "Call the only currently exposed tool. First freeze the plan. After each inspect_stage4_visual_job call, "
            "record its factual observation with record_visual_job_note before another image job becomes available. "
            "After all visual jobs, record_visual_finding_batch asks only which routed inputs were actually acquired; "
            "the program automatically binds every relevant bundle and marks the other routed visual inputs unresolved. "
            "Do not describe compliance. Run every registered measurement job exactly once through "
            "run_registered_measurement, using inspected endpoint observations only when the job requires endpoints, then "
            "persist all completed measurement outcomes with record_measurement_finding_batch. Direct Stage 3 inputs and "
            "inputs blocked by the frozen measurement spec are materialized automatically. Call get_stage4_readiness; "
            "if ready is false, complete only the listed gaps and call readiness again. Call seal_measurements only after "
            "ready is true. Never invent source IDs, evidence kinds, tools_used, measurement tools, or acquisition attempts."
        )
    if orchestrated_stage5 and phase == "inspection_conclusion":
        contract = (
            "ORCHESTRATED STAGE 5 — Form conclusions only from the frozen requirements and bound Stage 4 evidence. "
            "Call the only currently exposed tool. First load the conclusion plan. Then submit exactly one conclusion "
            "for every pending requirement in the single required batch. The registered modality determines Mandatory "
            "versus Guidance and cannot be changed. If any required input is unresolved, or normative applicability is "
            "false or indeterminate, inspection_status must be not_assessed. Do not treat an unreadable or unresolved "
            "observation as proof of deficiency. If applicability is true and the structured evidence ledger has no "
            "unresolved required input, make a definitive satisfied/deficient decision: use satisfied when the relevant "
            "setup is observable and no clear material error is established, and deficient only when reliable evidence "
            "establishes a clear material violation. Do not create a hidden evidence gap in free-text limitations after "
            "Stage 4 marked the corresponding input acquired. Conversely, an explicit user/domain-reviewer-confirmed deficiency "
            "in the bound direct evidence is binding and must be reported as deficient when applicability is true. "
            "The program binds evidence IDs, measurement IDs, tools, acquisition "
            "attempts, and final data availability. Check readiness and seal only when ready is true."
        )
    if orchestrated_stage5 and phase == "result_submission":
        contract = (
            "ORCHESTRATED STAGE 6 — Call the only currently exposed tool. The program copies "
            "sealed Stage 5 drafts in registry-sized batches and then deterministically finalizes. "
            "Do not rewrite conclusions, evidence bindings, availability, or completion metadata."
        )
    if simplified_inspection_checks and phase == "requirement_discovery":
        if stage1_architecture == "kg_only":
            contract = (
                "SIMPLIFIED STAGE 1 — Call load_ta_core_graph, then load_scene_condition_graph. "
                "No retrieval supplement is available. Begin registration after both graph layers load."
            )
        elif stage1_architecture == "retrieval_only":
            contract = (
                "SIMPLIFIED STAGE 1 — Call load_domain_gap_candidates exactly once for each of "
                "the six domains. No Knowledge Graph traversal is available. Begin registration "
                "after all six domain retrievals load."
            )
        else:
            contract = (
                "SIMPLIFIED STAGE 1 — Call load_ta_core_graph, then load_scene_condition_graph, then "
                "load_domain_gap_candidates exactly once for each of the six domains. The program handles relevance "
                "filtering and paging. Do not create a discovery ledger. Begin registration after all six domains load."
            )
    elif simplified_inspection_checks and phase == "requirement_registration":
        contract = (
            "SIMPLIFIED STAGE 2 — Use submit_inspection_check_batch to register a concise set of distinct, executable "
            "field checks, not a clause inventory. Keep predicates separate whenever one can fail while another passes; "
            "shared evidence or a shared inspection tool does not make them duplicates. Project-excluded scope and "
            "canonical provenance are program-enforced. "
        )
        if stage1_architecture in {"kg_plus_retrieval", "kg_only"}:
            contract += (
                "After the initial compilation, call audit_stage2_candidate_coverage and review every returned predicate "
                "with submit_stage2_candidate_decision_batch. Supply exactly one structured activation, independent-violation, "
                "duplicate, action, and reason decision for every pending source node. The program binds canonical text and "
                "registers retained decisions. After the final decision batch, call the audit again. Seal only when both "
                "new_candidate_count and pending_structured_decision_count are zero. The audit is a completeness check, not "
                "an answer list or required output count. "
            )
        contract += "Complete all six regions and seal registration."
    elif scoped_stage1_stage2 and phase == "requirement_discovery":
        contract = (
            "STAGE 1 CONTRACT — First call load_ta_core_graph, then load_scene_condition_graph. These deterministic "
            "Knowledge Graph layers provide the main candidate set and provenance paths. Then call audit_graph_gaps for "
            "each of the six domains to inspect normative provisions not reached by the graph. Use continuation tokens "
            "until has_more is false; the tool itself excludes the low-relevance corpus tail. RAG is only a completeness checker. There is no per-domain "
            "candidate-count ceiling; retain uncertain plausible candidates for Stage 2. Standard/shall and Guidance/should "
            "are in scope; Option/may and Support are context only. No image, bbox, or measurement tool is available. "
            "Close each domain with record_domain_discovery after all three layers have been reviewed. Begin registration "
            "only after all six ledger entries are closed."
        )
    elif scoped_stage1_stage2 and phase == "requirement_registration":
        contract = (
            "STAGE 2 CONTRACT — Register the complete activated set with submit_atomic_requirement_batch using already "
            "retrieved governing-section source_node_id values. Typical-Application figure components may establish "
            "activation but are forbidden as normative requirement sources. Do not activate an unresolved conditional "
            "provision. A true device-presence or layout trigger activates its rule even when mode, direction, condition, "
            "or placement remains unknown; those unknowns are later inspection inputs, not reasons to omit the rule. Use "
            "only literal non-null scene-fact keys and never invent derived keys. Each record must contain exactly one "
            "independently testable predicate. Use a general atomicity test based on independently decidable subjects, conditions, relations, or thresholds; no information need has a predeclared number of output atoms. "
            "A partial-success batch durably commits accepted records, so retry only "
            "the rejected records. Before sealing, explicitly disposition every source node placed in each domain discovery "
            "ledger: register activated predicates or call exclude_discovery_candidate_batch for genuinely inactive, "
            "out-of-scope, non-normative, duplicate, or non-field-inspectable candidates. Missing later observation data is "
            "not an exclusion reason. "
            "canonical modality, locator, and source span are program-bound. Reject semantic duplicates, close all six domains, and seal "
            "registration. No retrieval, scene, image, bbox, or measurement tool is available."
        )
    if stop_before_measurement:
        contract += " THIS REVIEW RUN MUST STOP IMMEDIATELY AFTER Stage 3 is sealed; no Stage 4 call is permitted."
    if stop_after_requirement_registration:
        contract += " THIS TEST MUST STOP IMMEDIATELY AFTER Stage 2 is sealed; no Stage 3 call is permitted."
    if stop_after_measurements:
        contract += " THIS TEST MUST STOP IMMEDIATELY AFTER Stage 4 is sealed; no Stage 5 call is permitted."
    if stop_after_conclusions:
        contract += " THIS TEST MUST STOP IMMEDIATELY AFTER Stage 5 is sealed; no Stage 6 call is permitted."
    return contract


def _run_workflow(cfg: dict, scene_view: dict, layouts: list[dict], key: str, base_url: str,
                  out: Path) -> tuple[dict, ToolGatewayV5, list[dict], float, bool, bool]:
    execution = cfg.get("execution", {})
    gap_retrieval = cfg.get("stage1c_gap_retrieval", {"method": "bm25"})
    stage1_architecture = gap_retrieval.get("architecture", "kg_plus_retrieval")
    scoped_stage1_stage2 = execution.get("scoped_stage1_stage2_test") is True
    simplified_inspection_checks = execution.get("simplified_inspection_checks") is True
    orchestrated_stage4 = execution.get("orchestrated_stage4") is True
    orchestrated_stage5 = execution.get("orchestrated_stage5") is True
    stop_after_registration = execution.get("stop_after_requirement_registration") is True
    stop_after_measurements = execution.get("stop_after_measurements") is True
    stop_after_conclusions = execution.get("stop_after_conclusions") is True
    resume_checkpoint = cfg.get("execution", {}).get("resume_registry_checkpoint")
    resume_trace = cfg.get("execution", {}).get("resume_tool_trace")
    if resume_checkpoint and resume_trace:
        gateway = ToolGatewayV5.from_checkpoint(
            layouts, scene_view, load_json(Path(resume_checkpoint)), load_json(Path(resume_trace)),
            scoped_stage1_stage2, simplified_inspection_checks, orchestrated_stage4,
            orchestrated_stage5, gap_retrieval, cfg["scene_manifest"],
        )
    else:
        gateway = ToolGatewayV5(layouts, scene_view, scoped_stage1_stage2,
                                simplified_inspection_checks, orchestrated_stage4,
                                orchestrated_stage5, gap_retrieval,
                                scene_manifest=cfg["scene_manifest"])
    prompt = (simplified_stage1_stage2_prompt(scene_view, layouts, gap_retrieval)
              if simplified_inspection_checks else
              stage1_stage2_scoped_prompt(scene_view, layouts) if scoped_stage1_stage2
              else workflow_prompt(scene_view, layouts))
    if resume_checkpoint:
        prompt += "\n\nResume from the validated persistent checkpoint below. Do not repeat completed discovery or accepted registrations.\n"
        prompt += _workflow_state_packet(scene_view, layouts, gateway, scoped_stage1_stage2)
    input_items = [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}]
    responses: list[dict] = []
    latency = 0.0
    image_count = 0
    for turn in range(1, cfg["emergency_controller_turn_ceiling"] + 1):
        controller_instruction = phase_contract(
            gateway.registry.phase, execution.get("stop_before_measurement") is True,
            stop_after_registration, scoped_stage1_stage2,
            simplified_inspection_checks, stop_after_measurements,
            orchestrated_stage4, orchestrated_stage5, stop_after_conclusions,
            stage1_architecture,
        )
        payload = _response_payload(
            cfg,
            controller_instruction,
            input_items, gateway.available_definitions(), None,
        )
        payload_dir = out / "payloads"
        payload_dir.mkdir(parents=True, exist_ok=True)
        (payload_dir / f"stage_1_to_6_{turn:04d}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )
        try:
            response, elapsed = post_json(f"{base_url}/v1/responses", key, payload)
        except Exception as exc:
            (out / "workflow_api_failure.json").write_text(json.dumps({
                "stage": gateway.registry.phase, "turn": turn, "error": str(exc),
                "responses_received": len(responses), "api_retries": 0,
            }, ensure_ascii=False, indent=2) + "\n")
            (out / "stage_1_to_6_registry_in_progress.json").write_text(
                json.dumps(gateway.registry.snapshot(), ensure_ascii=False, indent=2) + "\n"
            )
            (out / "tool_trace.json").write_text(
                json.dumps(gateway.trace, ensure_ascii=False, indent=2) + "\n"
            )
            (out / "raw_responses.json").write_text(
                json.dumps(responses, ensure_ascii=False, indent=2) + "\n"
            )
            raise
        responses.append(response); latency += elapsed
        (out / "stage_1_to_6_raw_responses_in_progress.json").write_text(
            json.dumps(responses, ensure_ascii=False, indent=2) + "\n"
        )
        calls = [item for item in response.get("output", []) if item.get("type") == "function_call"]
        if not calls:
            # A prose stop is invalid because it bypasses the persistent scored registry.
            raise RuntimeError("method_failure: controller stopped without a successful finalize_registry call")
        next_input = [item for item in response.get("output", []) if item.get("type") == "function_call"]
        for call in calls:
            args = json.loads(call.get("arguments", "{}"))
            result = gateway.call(call["name"], args)
            (out / "stage_1_to_6_tool_trace_in_progress.json").write_text(
                json.dumps(gateway.trace, ensure_ascii=False, indent=2) + "\n"
            )
            if result.get("finalized") is True:
                _write_checkpoint(out, gateway)
                result["image_count_sent"] = image_count
                return result, gateway, responses, latency, False, False
            if (stop_after_registration and call["name"] == "seal_requirement_registration" and
                    result.get("phase") == "data_availability"):
                _write_checkpoint(out, gateway)
                checkpoint = gateway.registry.snapshot()
                checkpoint["review_checkpoint"] = {
                    "status": "awaiting_stage1_stage2_evaluation",
                    "stopped_after_requirement_registration": True,
                    "scene_or_measurement_tool_calls": 0,
                }
                return checkpoint, gateway, responses, latency, False, True
            if (cfg.get("execution", {}).get("stop_before_measurement") is True and
                    call["name"] == "seal_data_availability" and
                    result.get("phase") == "measurement"):
                _write_checkpoint(out, gateway)
                checkpoint = gateway.registry.snapshot()
                checkpoint["review_checkpoint"] = {
                    "status": "awaiting_user_requirement_review",
                    "stopped_before_measurement": True,
                    "measurement_tool_calls": 0,
                }
                return checkpoint, gateway, responses, latency, False, True
            if (stop_after_measurements and call["name"] == "seal_measurements" and
                    result.get("phase") == "inspection_conclusion"):
                _write_checkpoint(out, gateway)
                checkpoint = gateway.registry.snapshot()
                checkpoint["review_checkpoint"] = {
                    "status": "awaiting_stage4_evaluation",
                    "stopped_after_measurements": True,
                    "inspection_conclusion_calls": 0,
                }
                return checkpoint, gateway, responses, latency, False, True
            if (stop_after_conclusions and call["name"] == "seal_conclusions" and
                    result.get("phase") == "result_submission"):
                _write_checkpoint(out, gateway)
                checkpoint = gateway.registry.snapshot()
                checkpoint["review_checkpoint"] = {
                    "status": "awaiting_stage5_evaluation",
                    "stopped_after_conclusions": True,
                    "result_submission_calls": 0,
                }
                return checkpoint, gateway, responses, latency, False, True
            clean, image_paths = _sanitize_result(result, cfg["single_tool_response_max_chars"])
            next_input.append({"type": "function_call_output", "call_id": call["call_id"],
                               "output": json.dumps(clean, ensure_ascii=False)})
            if image_paths:
                image_count += len(image_paths)
                next_input.append({"role": "user", "content": [
                    {"type": "input_text", "text": "Tool-selected scene image(s), in the returned order."},
                    *[{"type": "input_image", "image_url": image_data_url(Path(path)), "detail": "high"}
                      for path in image_paths],
                ]})
            _write_checkpoint(out, gateway)
        next_input.append({"role": "user", "content": [{"type": "input_text",
                           "text": _workflow_state_packet(scene_view, layouts, gateway,
                                                          scoped_stage1_stage2)}]})
        # Deliberately retain only the immediately preceding function call/output
        # plus the authoritative persistent state. This avoids replaying every
        # obsolete tool log while preserving an auditable local registry.
        input_items = next_input
    return gateway.registry.snapshot(), gateway, responses, latency, True, False


def requirement_review_plan(record: dict) -> dict:
    rows = []
    inspectable = 0
    measurement_planned = 0
    for requirement in record.get("requirements", []):
        availability = requirement.get("data_availability_record") or {}
        data_ready = (
            availability.get("data_availability") in {
                "available_direct", "acquired", "partial", "not_attempted"
            } and bool(availability.get("planned_tools"))
        )
        inspectable += int(data_ready)
        measurement_planned += int(
            data_ready and requirement.get("measurement_spec", {}).get("required") is True
        )
        rows.append({
            "discovered_requirement_key": requirement.get("discovered_requirement_key"),
            "candidate_label": requirement.get("candidate_label"),
            "subject": requirement.get("subject"), "modality": requirement.get("modality"),
            "relation": requirement.get("relation"), "threshold": requirement.get("threshold"),
            "applicability_conditions": requirement.get("applicability_conditions"),
            "required_inputs": requirement.get("required_inputs"),
            "source_locator": requirement.get("source_locator"),
            "source_span": requirement.get("source_span"),
            "measurement_spec": requirement.get("measurement_spec"),
            "condition_data_complete": availability.get("condition_data_complete"),
            "data_availability": availability.get("data_availability"),
            "available_inputs": availability.get("available_inputs"),
            "missing_inputs": availability.get("missing_inputs"),
            "planned_tools": availability.get("planned_tools"),
            "planned_evidence_strategy": availability.get("planned_evidence_strategy"),
            "planned_decision_rule": availability.get("planned_decision_rule"),
            "planned_for_inspection_after_review": data_ready,
        })
    stopped_after_registration = record.get("review_checkpoint", {}).get(
        "stopped_after_requirement_registration") is True
    return {
        "status": ("awaiting_stage1_stage2_evaluation" if stopped_after_registration
                   else "awaiting_user_requirement_review"),
        "stopped_after_requirement_registration": stopped_after_registration,
        "stopped_before_measurement": True,
        "registered_requirement_count": len(rows), "planned_inspection_count": inspectable,
        "planned_normative_measurement_count": measurement_planned, "requirements": rows,
    }


def _sum_resources(cfg: dict, stage0: ToolGatewayV5, workflow: ToolGatewayV5,
                   responses: list[dict], latency: float, emergency: bool) -> dict:
    left, right = stage0.resources(), workflow.resources()
    usage = _usage(responses)
    resources = {**right, **usage}
    for key in ("regulation_retrieval_calls", "retrieved_chunks_nodes", "retrieved_characters",
                "tool_calls_total", "tool_failures", "tool_retries"):
        resources[key] = int(left.get(key, 0)) + int(right.get(key, 0))
    resources["retrieval_queries"] = left.get("retrieval_queries", []) + right.get("retrieval_queries", [])
    pricing = cfg.get("model_pricing_usd_per_million") or {}
    uncached = max(0, usage["input_tokens"] - usage["cached_tokens"])
    actual_cost = (
        uncached * float(pricing.get("input", 0)) +
        usage["cached_tokens"] * float(pricing.get("cached_input", 0)) +
        usage["output_tokens"] * float(pricing.get("output", 0))
    ) / 1_000_000
    resources.update({
        "controller_turns": len(responses), "model_api_calls": len(responses),
        "wall_clock_seconds": latency, "gpu_seconds": None,
        "image_tokens_or_processed_pixels": None,
        "actual_model_api_cost_usd": round(actual_cost, 8),
        "model_pricing_usd_per_million": pricing,
        "model_api_retries": 0,
        "estimated_external_api_cost_usd": 0.0,
        "emergency_ceiling_triggered": emergency,
    })
    return resources


def assert_execution_allowed(cfg: dict, execute: bool, run: int) -> None:
    if not execute:
        return
    if not cfg["execution"]["model_calls_enabled"] or run not in cfg["execution"]["authorized_runs"]:
        raise SystemExit("EXECUTION LOCKED: only explicitly authorized run_01 may execute")
    preflight_path = ROOT / cfg["execution"]["preflight_report"]
    if not preflight_path.exists():
        raise SystemExit("EXECUTION LOCKED: machine-readable v5 preflight is missing")
    report = load_json(preflight_path)
    if not report.get("passed"):
        raise SystemExit("EXECUTION LOCKED: critical v5 preflight failed")
    for label, path_text in report["frozen_inputs"].items():
        if sha256(Path(path_text["path"])) != path_text["sha256"]:
            raise SystemExit(f"EXECUTION LOCKED: frozen input changed after preflight: {label}")
    for path_text, expected in report["implementation_sha256"].items():
        if sha256(Path(path_text)) != expected:
            raise SystemExit(f"EXECUTION LOCKED: validated implementation changed after preflight: {path_text}")


def save_api_failure(out: Path, cfg: dict, stage: str, exc: Exception, elapsed: float) -> None:
    message = str(exc)
    failure = {
        "stage": stage, "model": cfg["model"], "reasoning_effort": cfg["reasoning_effort"],
        "api_attempts": 1, "api_retries": 0, "responses_received": 0,
        "error": message, "token_usage": {"input_tokens": 0, "cached_tokens": 0,
                                           "output_tokens": 0, "total_tokens": 0},
        "actual_model_api_cost_usd": 0.0, "wall_clock_seconds": elapsed,
    }
    (out / "api_failure.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n")
    (out / "raw_responses.json").write_text("[]\n")
    (out / "resource_usage.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n")
    (out / "result.json").write_text(json.dumps({
        "method_id": cfg["method_id"], "run": 1, "status": "method_failure",
        "failure_reason": message, "completed_stage": None, "resources": failure,
        "reference_notice": cfg["reporting"]["reference_status"],
    }, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    config_path = args.config.resolve()
    cfg = load_json(config_path)
    if args.run != 1:
        raise SystemExit("run_02 and run_03 are intentionally locked")
    assert_execution_allowed(cfg, args.execute, args.run)
    scene = load_json(ROOT / cfg["scene_manifest"])
    data_gateway = ToolGatewayV5([], scene_manifest=cfg["scene_manifest"])
    scene_view = public_scene_input(scene, data_gateway.scene.manifest())
    scoped_stage1_stage2 = cfg.get("execution", {}).get("scoped_stage1_stage2_test") is True
    simplified_inspection_checks = cfg.get("execution", {}).get(
        "simplified_inspection_checks"
    ) is True
    workflow_scene_view = ({"scene_id": scene["scene_id"],
                            "scene_facts": dict(scene["scene_facts"])}
                           if scoped_stage1_stage2 else scene_view)
    out = ROOT / cfg["output_directory"]
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "experiment_id": cfg["experiment_id"], "method_id": cfg["method_id"], "run": args.run,
        "method_role": cfg.get("method_role"),
        "method_definition_version": cfg.get("method_definition_version"),
        "stage2_policy": cfg.get("stage2_policy"),
        "single_method_development_test": True, "cross_method_comparison_valid": False,
        "correct_layout_page_region_or_target_supplied": False,
        "hidden_requirement_id_supplied": False, "scene_view": scene_view,
        "config_path": str(config_path), "config_sha256": sha256(config_path),
        "model": cfg["model"], "reasoning_effort": cfg["reasoning_effort"],
        "resume_stage0_record": cfg.get("execution", {}).get("resume_stage0_record"),
        "resume_registry_checkpoint": cfg.get("execution", {}).get("resume_registry_checkpoint"),
        "stage0_prompt_sha256": hashlib.sha256(stage0_prompt(scene_view).encode()).hexdigest(),
        "workflow_prompt_template_sha256": hashlib.sha256(
            (simplified_stage1_stage2_prompt(
                workflow_scene_view, [], cfg.get("stage1c_gap_retrieval", {"method": "bm25"})
             )
             if simplified_inspection_checks else
             stage1_stage2_scoped_prompt(workflow_scene_view, []) if scoped_stage1_stage2
             else workflow_prompt(scene_view, [])).encode()).hexdigest(),
        "scoped_stage1_stage2_test": scoped_stage1_stage2,
        "simplified_inspection_checks": simplified_inspection_checks,
        "stage1c_gap_retrieval": cfg.get("stage1c_gap_retrieval", {"method": "bm25"}),
        "stage1_architecture": cfg.get("stage1c_gap_retrieval", {}).get(
            "architecture", "kg_plus_retrieval"
        ),
        "executed": args.execute,
    }
    (out / "request_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2)); return
    key, base_url = credentials(cfg)
    started = time.monotonic()
    resume_stage0 = cfg.get("execution", {}).get("resume_stage0_record")
    if resume_stage0:
        stage0 = load_json(Path(resume_stage0))
        validate_stage0_selection(stage0, set(data_gateway.retrieval.unit_by_code))
        stage0_gateway, stage0_responses, stage0_latency = (
            ToolGatewayV5([], scene_manifest=cfg["scene_manifest"]), [], 0.0
        )
        (out / "stage_0_layout_selection.json").write_text(
            json.dumps(stage0, ensure_ascii=False, indent=2) + "\n"
        )
    else:
        try:
            stage0, stage0_gateway, stage0_responses, stage0_latency = _run_stage0(
                cfg, scene_view, key, base_url, out
            )
        except Exception as exc:
            save_api_failure(out, cfg, "stage_0", exc, time.monotonic() - started)
            print(f"FAILED {cfg['method_display_name']} stage_0: {exc}")
            return
    primary = [row for row in stage0["selected_layouts"] if row["layout_role"] == "primary_applicable"]
    if stage0["layout_selection_status"] != "determined" or not primary:
        usage = _usage(stage0_responses)
        pricing = cfg.get("model_pricing_usd_per_million") or {}
        uncached = max(0, usage["input_tokens"] - usage["cached_tokens"])
        cost = (uncached * float(pricing.get("input", 0)) +
                usage["cached_tokens"] * float(pricing.get("cached_input", 0)) +
                usage["output_tokens"] * float(pricing.get("output", 0))) / 1_000_000
        resources = {**stage0_gateway.resources(), **usage,
                     "model_api_calls": len(stage0_responses), "model_api_retries": 0,
                     "actual_model_api_cost_usd": round(cost, 8),
                     "model_pricing_usd_per_million": pricing}
        result = {"method_id": cfg["method_id"], "run": 1, "status": "method_failure",
                  "failure_reason": "Stage 0 did not determine a primary MUTCD Typical Application",
                  "stage0": stage0, "resources": resources}
        (out / "raw_responses.json").write_text(
            json.dumps(stage0_responses, ensure_ascii=False, indent=2) + "\n"
        )
        (out / "tool_trace.json").write_text(
            json.dumps(stage0_gateway.trace, ensure_ascii=False, indent=2) + "\n"
        )
        (out / "resource_usage.json").write_text(
            json.dumps(resources, ensure_ascii=False, indent=2) + "\n"
        )
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return
    try:
        record, workflow_gateway, workflow_responses, workflow_latency, emergency, review_pause = _run_workflow(
            cfg, workflow_scene_view, stage0["selected_layouts"], key, base_url, out
        )
    except Exception as exc:
        (out / "result.json").write_text(json.dumps({
            "method_id": cfg["method_id"], "run": 1, "status": "method_failure",
            "failure_reason": str(exc), "failure_stage": "stage_1_to_3_requirement_review",
            "reference_notice": cfg["reporting"]["reference_status"],
        }, ensure_ascii=False, indent=2) + "\n")
        print(f"FAILED {cfg['method_display_name']} workflow: {exc}")
        return
    responses = stage0_responses + workflow_responses
    resources = _sum_resources(cfg, stage0_gateway, workflow_gateway, responses,
                               time.monotonic() - started, emergency)
    if review_pause:
        review_checkpoint = record.get("review_checkpoint", {})
        if review_checkpoint.get("stopped_after_requirement_registration"):
            status = "awaiting_stage1_stage2_evaluation"
        elif review_checkpoint.get("stopped_after_measurements"):
            status = "awaiting_stage4_evaluation"
        elif review_checkpoint.get("stopped_after_conclusions"):
            status = "awaiting_stage5_evaluation"
        else:
            status = "awaiting_user_requirement_review"
        failure = None
    elif emergency:
        status, failure = "method_failure", "budget_exhausted: emergency controller ceiling triggered"
    else:
        status, failure = "completed", None
    (out / "stage_1_to_6_registry.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    if review_pause:
        (out / "requirement_review_plan.json").write_text(
            json.dumps(requirement_review_plan(record), ensure_ascii=False, indent=2) + "\n"
        )
    (out / "tool_trace.json").write_text(json.dumps(stage0_gateway.trace + workflow_gateway.trace,
                                                       ensure_ascii=False, indent=2) + "\n")
    (out / "raw_responses.json").write_text(json.dumps(responses, ensure_ascii=False, indent=2) + "\n")
    (out / "resource_usage.json").write_text(json.dumps(resources, ensure_ascii=False, indent=2) + "\n")
    (out / "external_query_cache.json").write_text(json.dumps(workflow_gateway.scene.external_queries,
                                                               ensure_ascii=False, indent=2) + "\n")
    (out / "measurements.json").write_text(json.dumps(list(workflow_gateway.scene.measurements.values()),
                                                       ensure_ascii=False, indent=2) + "\n")
    (out / "result.json").write_text(json.dumps({
        "method_id": cfg["method_id"], "run": 1, "status": status, "failure_reason": failure,
        "method_role": cfg.get("method_role"),
        "method_definition_version": cfg.get("method_definition_version"),
        "stage2_policy": cfg.get("stage2_policy"),
        "stage0": stage0, "record": record, "resources": resources,
        "stopped_before_measurement": record.get("review_checkpoint", {}).get(
            "stopped_before_measurement", False),
        "stopped_after_measurements": record.get("review_checkpoint", {}).get(
            "stopped_after_measurements", False),
        "stopped_after_requirement_registration": record.get("review_checkpoint", {}).get(
            "stopped_after_requirement_registration", False),
        "stopped_after_conclusions": record.get("review_checkpoint", {}).get(
            "stopped_after_conclusions", False),
        "reference_notice": cfg["reporting"]["reference_status"],
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"DONE {cfg['method_display_name']} status={status}")


if __name__ == "__main__":
    main()
