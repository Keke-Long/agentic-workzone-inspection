#!/usr/bin/env python3
"""Phase-gated tools for the S-RAG-BM25 v5 canary."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from inspection_registry_v5 import (
    COVERAGE_DOMAINS,
    NORMATIVE_MEASUREMENT_TOOLS,
    InspectionRegistry,
    RegistryError,
    acquisition_tools_for_input,
    registry_tool_definitions,
)
from mutcd_knowledge_graph_v2 import MutcdKnowledgeGraphV2
from scene_data_tools_v5 import SceneDataToolsV5
from scoring_common import similarity, subject_similarity
from srag_bm25_retrieval_v5 import StructuredBM25V5


RETRIEVAL_TOOLS = {"search_manual", "expand_source_unit", "follow_cross_reference", "read_source_node"}
SCOPED_INFORMATION_NEEDS = {
    "lane_closure_layout": (
        "typical_application_context", "stationary_multilane_transition_rule",
        "closed_lane_side_channelization_rule",
    ),
    "advance_warning_sign_system": (
        "lane_closed_sign_use_rule", "lane_closed_legend_direction_rule",
        "road_work_sign_placement_rule", "multiple_warning_sign_sequence_rule",
        "spacing_applicability_rule",
    ),
    "channelization_system": (
        "spacing_rules_all_alignments", "maintenance_condition_rules",
        "serviceability_replacement_rules",
    ),
    "transition_and_taper_geometry": ("merging_taper_operational_rule", "taper_length_formula_rule"),
    "conditional_active_devices": (
        "device_presence_and_applicability", "operation_and_direction",
        "stationary_taper_start_placement", "integration_with_other_ttc",
    ),
    "conditional_termination_area": ("downstream_taper", "termination_signing"),
}
INFORMATION_NEED_QUERIES = {
    # These are deliberately broad review concepts, not paraphrases of expected
    # provisions.  High recall comes from expanding more ranked units below,
    # rather than embedding a target clause's distinctive wording in the query.
    "stationary_multilane_transition_rule": "temporary traffic control lane closure transition area",
    "closed_lane_side_channelization_rule": "temporary traffic control closed lane channelization layout",
    "lane_closed_sign_use_rule": "temporary traffic control lane closure warning signs",
    "lane_closed_legend_direction_rule": "temporary traffic control warning sign messages and roadway conditions",
    "road_work_sign_placement_rule": "temporary traffic control advance warning sign placement",
    "multiple_warning_sign_sequence_rule": "temporary traffic control advance warning sign sequence",
    "spacing_applicability_rule": "temporary traffic control advance warning sign spacing",
    "spacing_rules_all_alignments": "temporary traffic control channelizing device spacing",
    "maintenance_condition_rules": "temporary traffic control channelizing device maintenance",
    "serviceability_replacement_rules": "temporary traffic control channelizing device condition",
    "merging_taper_operational_rule": "temporary traffic control transition area traffic movement",
    "taper_length_formula_rule": "temporary traffic control taper geometry and length",
    "device_presence_and_applicability": "temporary traffic control active warning device applicability",
    "operation_and_direction": "temporary traffic control active warning device operation",
    "stationary_taper_start_placement": "temporary traffic control active warning device placement",
    "integration_with_other_ttc": "temporary traffic control active warning device system integration",
    "downstream_taper": "temporary traffic control termination area channelization",
    "termination_signing": "temporary traffic control termination area signs",
}
SCOPED_INFORMATION_NEED_SET = {
    need for needs in SCOPED_INFORMATION_NEEDS.values() for need in needs
}
SCOPED_CANDIDATE_EXCLUSION_REASONS = (
    "activation_predicate_not_established",
    "duplicate_same_compliance_predicate",
    "excluded_project_scope",
    "non_normative_context",
    "not_a_field_inspection_predicate",
)
SCOPED_SEARCH_UNIT_LIMIT = 12
SCOPED_GOVERNING_UNIT_LIMIT = 30
SCOPED_AUTO_EXPAND_UNIT_LIMIT = 18
SCOPED_ATOMIC_ITEM_LIMIT = 48
SCOPED_ATOMS_PER_UNIT = 6
SCOPED_GLOBAL_ATOM_SEED = 24
SCOPED_DOMAIN_SOURCE_PREFIXES = {
    # Domain-level Part 6 routing is structural prior knowledge. It does not
    # name an expected section, paragraph, sign code, threshold, or citation.
    "lane_closure_layout": ("SEC-6N",),
    "advance_warning_sign_system": ("SEC-6H", "TABLE-6B"),
    "channelization_system": ("SEC-6K",),
    "transition_and_taper_geometry": ("SEC-6B", "TABLE-6B", "SEC-6N"),
    "conditional_active_devices": ("SEC-6L",),
    "conditional_termination_area": ("SEC-6B", "SEC-6H", "SEC-6N", "TABLE-6B"),
}
REGISTRY_TOOLS = {row["name"] for row in registry_tool_definitions()}
INVENTORY_TOOLS = {
    "get_scene_data_manifest", "list_scene_sensors", "get_reviewed_observations",
    "list_temporal_frames", "get_vehicle_trajectory", "get_sensor_calibration",
}


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "name": name, "description": description, "strict": True,
            "parameters": {"type": "object", "additionalProperties": False,
                           "properties": properties, "required": required}}


def retrieval_tool_definitions() -> list[dict]:
    nullable_token = {"type": ["string", "null"]}
    return [
        _fn("search_manual", "Search every prebuilt MUTCD section and Typical Application with structured BM25; page through results as needed.",
            {"query": {"type": "string"}, "page_size": {"type": "integer", "minimum": 1, "maximum": 12},
             "continuation_token": nullable_token}, ["query", "page_size", "continuation_token"]),
        _fn("expand_source_unit", "Read atomic source nodes for a retrieved section or Typical Application and optional region.",
            {"source_unit_code": {"type": "string"}, "region": {"type": ["string", "null"]},
             "page_size": {"type": "integer", "minimum": 1, "maximum": 12},
             "continuation_token": nullable_token}, ["source_unit_code", "region", "page_size", "continuation_token"]),
        _fn("follow_cross_reference", "Traverse only an explicit cross-reference edge found in the manual graph.",
            {"from_source_unit_code": {"type": "string"}, "to_source_unit_code": {"type": ["string", "null"]}},
            ["from_source_unit_code", "to_source_unit_code"]),
        _fn("read_source_node", "Read one source-hash node previously surfaced by the full-manual index.",
            {"source_node_id": {"type": "string"}}, ["source_node_id"]),
    ]


def scoped_discovery_registration_definitions() -> list[dict]:
    measurement_spec = {
        "type": "object", "additionalProperties": False,
        "required": ["required", "tool", "quantity", "thresholds"],
        "properties": {
            "required": {"type": "boolean"},
            "tool": {"enum": sorted(NORMATIVE_MEASUREMENT_TOOLS) + [None]},
            "quantity": {"type": ["string", "null"]},
            "thresholds": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["condition", "value", "unit", "violation_when",
                             "formula_parameter", "multiplier"],
                "properties": {
                    "condition": {"type": "string"},
                    "value": {"type": ["number", "null"]},
                    "unit": {"enum": ["m", "ft"]},
                    "violation_when": {"enum": ["below_minimum", "above_maximum"]},
                    "formula_parameter": {"type": ["string", "null"]},
                    "multiplier": {"type": ["number", "null"]},
                },
            }},
        },
    }
    atomic = {
        "type": "object", "additionalProperties": False,
        "required": ["candidate_label", "subject", "relation", "threshold",
                     "applicability_conditions", "required_inputs", "source_node_id",
                     "activation_basis", "measurement_spec"],
        "properties": {
            "candidate_label": {"type": "string"}, "subject": {"type": "string"},
            "relation": {"type": "string"}, "threshold": {"type": "string"},
            "applicability_conditions": {"type": "array", "items": {"type": "string"}},
            "required_inputs": {"type": "array", "items": {"type": "string"}},
            "source_node_id": {"type": "string"}, "measurement_spec": measurement_spec,
            "activation_basis": {
                "type": "object", "additionalProperties": False,
                "required": ["type", "fact_keys", "evidence_source_node_ids", "explanation"],
                "properties": {
                    "type": {"enum": ["unconditional", "scene_fact", "selected_ta", "combined"]},
                    "fact_keys": {"type": "array", "items": {"type": "string"}},
                    "evidence_source_node_ids": {"type": "array", "items": {"type": "string"}},
                    "explanation": {"type": "string"},
                },
            },
        },
    }
    return [
        _fn("load_ta_core_graph",
            "Stage 1A deterministic graph query: load the selected Typical Application's components, explicit references, governing source units, and reachable normative candidates.",
            {}, []),
        _fn("load_scene_condition_graph",
            "Stage 1B deterministic graph query: activate component requirement families from true scene facts, accepted component classes, and TA-core required-device implications.",
            {}, []),
        _fn("audit_graph_gaps",
            "Stage 1C supplement: use the configured retriever to rank only normative provisions not already reached by Stage 1A/1B for one inspection domain. Use continuation tokens when another page could contain plausible gaps.",
            {"domain": {"enum": list(COVERAGE_DOMAINS)},
             "page_size": {"type": "integer", "minimum": 1, "maximum": 12},
             "continuation_token": {"type": ["string", "null"]}},
            ["domain", "page_size", "continuation_token"]),
        _fn("load_domain_gap_candidates",
            "Simplified Stage 1C: in one call, return the configured retriever's bounded graph-gap candidates for one inspection domain; no model-controlled pagination.",
            {"domain": {"enum": list(COVERAGE_DOMAINS)}}, ["domain"]),
        _fn("search_manual_for_need",
            "Run one broad, program-defined review-concept query for a declared information need; the tool returns ranked source units and recall-oriented normative candidates.",
            {"domain": {"enum": list(COVERAGE_DOMAINS)},
             "information_need": {"enum": sorted(SCOPED_INFORMATION_NEED_SET)}},
            ["domain", "information_need"]),
        _fn("expand_source_unit_for_need",
            "Expand one source unit returned for an information need and return the highest-relevance Standard/Guidance atomic nodes across all regions and pages.",
            {"domain": {"enum": list(COVERAGE_DOMAINS)},
             "information_need": {"enum": sorted(SCOPED_INFORMATION_NEED_SET)},
             "source_unit_code": {"type": "string"}},
            ["domain", "information_need", "source_unit_code"]),
        _fn("record_domain_discovery",
            "Close one of the six discovery-ledger domains after its searches and relevant source nodes have been reviewed.",
            {"domain": {"enum": list(COVERAGE_DOMAINS)},
             "status": {"enum": ["covered_with_candidates", "covered_no_activated_candidate"]},
             "query_summary": {"type": "string"},
             "source_node_ids": {"type": "array", "items": {"type": "string"}}},
            ["domain", "status", "query_summary", "source_node_ids"]),
        _fn("submit_atomic_requirement_batch",
            "Register atomic requirements by retrieved source node. Canonical modality, locator, and source span are bound by the program.",
            {"domain": {"enum": list(COVERAGE_DOMAINS)},
             "requirements": {"type": "array", "minItems": 1, "maxItems": 12, "items": atomic}},
            ["domain", "requirements"]),
        _fn("submit_inspection_check_batch",
            "Register complete, source-grounded field inspection checks. Keep separately violable predicates separate even when they use the same observation or tool; combine only inseparable branches of one predicate.",
            {"domain": {"enum": list(COVERAGE_DOMAINS)},
             "requirements": {"type": "array", "minItems": 1, "maxItems": 12,
                              "items": atomic}},
            ["domain", "requirements"]),
        _fn("exclude_discovery_candidate_batch",
            "Explicitly disposition retrieved candidates that were placed in a domain discovery ledger but are not activated final requirements.",
            {"domain": {"enum": list(COVERAGE_DOMAINS)},
             "exclusions": {"type": "array", "minItems": 1, "maxItems": 12, "items": {
                 "type": "object", "additionalProperties": False,
                 "required": ["source_node_id", "reason_code", "reason"],
                 "properties": {
                     "source_node_id": {"type": "string"},
                     "reason_code": {"enum": list(SCOPED_CANDIDATE_EXCLUSION_REASONS)},
                     "reason": {"type": "string"},
                 },
             }}},
            ["domain", "exclusions"]),
        _fn("audit_stage2_candidate_coverage",
            "Independently re-check every still-unresolved deterministic Knowledge Graph candidate after the initial Stage-2 compilation. The audit exposes normative predicates and general verification questions; it contains no benchmark answer IDs, expected wording, or target count.",
            {}, []),
        _fn("submit_stage2_candidate_decision_batch",
            "Submit one structured applicability-and-atomicity decision for each candidate returned by the Stage-2 coverage audit. The program binds canonical predicate text and provenance and directly registers retained candidates.",
            {"decisions": {"type": "array", "minItems": 1, "maxItems": 12,
                           "items": {
                "type": "object", "additionalProperties": False,
                "required": ["source_node_id", "activation_status",
                             "independently_violable", "duplicate_of_source_node_id",
                             "action", "decision_basis", "reason", "measurement_spec"],
                "properties": {
                    "source_node_id": {"type": "string"},
                    "activation_status": {"enum": ["established", "false", "unknown"]},
                    "independently_violable": {"type": "boolean"},
                    "duplicate_of_source_node_id": {"type": ["string", "null"]},
                    "action": {"enum": ["retain", "exclude"]},
                    "decision_basis": {"enum": [
                        "activated_independent", "activation_false", "activation_unknown",
                        "duplicate", "not_independent", "not_field_inspectable",
                    ]},
                    "reason": {"type": "string"},
                    "measurement_spec": measurement_spec,
                },
            }}}, ["decisions"]),
    ]


def scene_tool_definitions() -> list[dict]:
    string_or_null = {"type": ["string", "null"]}
    number_or_null = {"type": ["number", "null"]}
    oid = {"type": "string"}
    requirement_key = {"discovered_requirement_key": {
        "type": "string", "description": "Run-local key returned by submit_requirement_batch."
    }}
    pair = {"start_observation_id": oid, "end_observation_id": oid}
    definitions = [
        _fn("get_scene_data_manifest", "List direct, locally derivable, and externally retrievable scene inputs.", {}, []),
        _fn("list_scene_sensors", "List camera and lidar channels and frame counts.", {}, []),
        _fn("get_reviewed_observations", "Page through accepted 2D bbox observations; these are evidence candidates, not compliance labels.",
            {"cursor": {"type": "integer", "minimum": 0},
             "limit": {"type": "integer", "minimum": 1, "maximum": 100},
             "reviewed_class": {"type": ["string", "null"]},
             "representative_per_entity": {"type": "boolean"}},
            ["cursor", "limit", "reviewed_class", "representative_per_entity"]),
        _fn("list_temporal_frames", "Page through the complete time-ordered frame manifest for one sensor.",
            {"channel": {"type": "string"}, "cursor": {"type": "integer", "minimum": 0},
             "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, ["channel", "cursor", "limit"]),
        _fn("inspect_temporal_images", "Open selected temporal images for visual inspection.",
            {"channel": {"type": "string"}, "start_cursor": {"type": "integer", "minimum": 0},
             "count": {"type": "integer", "minimum": 1, "maximum": 12}, "stride": {"type": "integer", "minimum": 1}},
            ["channel", "start_cursor", "count", "stride"]),
        _fn("inspect_observation_images", "Open source images for accepted bbox observations.",
            {"observation_ids": {"type": "array", "minItems": 1, "maxItems": 12, "items": oid}}, ["observation_ids"]),
        _fn("get_vehicle_trajectory", "Page through timestamped ego poses and cumulative road station.",
            {"cursor": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, ["cursor", "limit"]),
        _fn("get_ego_pose", "Read the closest ego pose to a timestamp.", {"timestamp_us": {"type": "integer"}}, ["timestamp_us"]),
        _fn("get_sensor_calibration", "Read intrinsic and extrinsic calibration for a sensor channel.", {"channel": {"type": "string"}}, ["channel"]),
        _fn("get_sensor_sync", "Get camera/lidar synchronization for an accepted bbox observation.", {"observation_id": oid}, ["observation_id"]),
        _fn("project_bbox_to_lidar", "Project retained synchronized lidar candidates in an accepted bbox onto the ego trajectory.", {"observation_id": oid}, ["observation_id"]),
        _fn("locate_device_in_scene", "Associate an accepted bbox with lidar and an independently projected road-station distribution.", {"observation_id": oid}, ["observation_id"]),
        _fn("measure_longitudinal_distance", "Measure station distance between semantically named endpoints using the registered requirement threshold.",
            {**requirement_key, **pair, "measurement_type": {"type": "string"},
             "start_role": {"type": "string"}, "end_role": {"type": "string"}},
            ["discovered_requirement_key", *pair, "measurement_type", "start_role", "end_role"]),
        _fn("measure_device_spacing", "Deduplicate selected physical entities, station-sort them, and measure consecutive spacing using the registered requirement threshold.",
            {**requirement_key, "observation_ids": {"type": "array", "minItems": 2, "maxItems": 10, "items": oid}},
            ["discovered_requirement_key", "observation_ids"]),
        _fn("audit_channelizer_spacing", "Measure every adjacent gap on the accepted channelizer line nearest the vehicle trajectory, classify geometric regions, and return confidence-bounded observations using only the registered requirement.",
            requirement_key, ["discovered_requirement_key"]),
    ]
    for name, description in (
        ("measure_taper_length", "Measure taper start to end using the registered requirement threshold."),
        ("measure_buffer_length", "Measure buffer start to end using the registered requirement threshold."),
        ("measure_sign_spacing", "Measure upstream-to-downstream sign spacing using the registered requirement threshold."),
        ("measure_downstream_taper", "Measure downstream-taper start to end using the registered requirement threshold."),
    ):
        definitions.append(_fn(name, description, {**requirement_key, **pair},
                               ["discovered_requirement_key", *pair]))
    definitions.extend([
        _fn("estimate_available_width", "Measure between semantic left and right boundaries along the local road normal using the registered requirement threshold.",
            {**requirement_key, "left_observation_id": oid, "right_observation_id": oid},
            ["discovered_requirement_key", "left_observation_id", "right_observation_id"]),
        _fn("search_speed_limit_signs", "Search accepted traffic-sign candidates across the traversal.",
            {"cursor": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["cursor", "limit"]),
        _fn("record_speed_sign_reading", "Save a visual reading from an inspected accepted sign bbox.",
            {"observation_id": oid, "speed_mph": {"type": "integer"},
             "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
            ["observation_id", "speed_mph", "confidence"]),
        _fn("locate_road_segment", "Attempt to identify an exact road segment from non-reference local metadata.", {}, []),
        _fn("lookup_posted_speed", "Query the frozen speed-source interface; exact road identity is required.",
            {"road_name": string_or_null, "latitude": number_or_null, "longitude": number_or_null},
            ["road_name", "latitude", "longitude"]),
        _fn("query_road_authority_source", "Query the frozen road-authority interface for an exact segment.",
            {"road_name": string_or_null, "latitude": number_or_null, "longitude": number_or_null},
            ["road_name", "latitude", "longitude"]),
        _fn("resolve_speed_evidence_conflict", "Resolve or preserve conflicts among acquired speed evidence.",
            {"speed_evidence_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}}}, ["speed_evidence_ids"]),
    ])
    return definitions


def orchestrated_stage4_tool_definitions() -> list[dict]:
    """Strongly typed Stage 4 tools; provenance fields are program-composed."""
    required_input_array = {"type": "array", "items": {"type": "string"}}
    return [
        _fn(
            "get_stage4_acquisition_plan",
            "Freeze and return the deterministic Stage 4 visual jobs, registered measurement jobs, direct evidence, and blocked inputs.",
            {}, [],
        ),
        _fn(
            "inspect_stage4_visual_job",
            "Inspect exactly one program-selected visual job. The program persists an inspection bundle and its source IDs.",
            {"visual_job_id": {"type": "string"}}, ["visual_job_id"],
        ),
        _fn(
            "record_visual_job_note",
            "Persist the factual observation and limitations from the most recently completed visual job before another image job is opened.",
            {
                "visual_job_id": {"type": "string"},
                "finding": {"type": "string"},
                "limitations": {"type": "string"},
            },
            ["visual_job_id", "finding", "limitations"],
        ),
        _fn(
            "run_registered_measurement",
            "Run the next frozen measurement job. Its task-specific arguments are constrained at runtime.",
            {"measurement_job_id": {"type": "string"}},
            ["measurement_job_id"],
        ),
        _fn(
            "record_visual_finding",
            "Persist a factual visual finding. Evidence type, tools, and source IDs are derived from inspection bundles.",
            {
                "discovered_requirement_key": {"type": "string"},
                "acquired_inputs": required_input_array,
                "finding": {"type": "string"},
                "limitations": {"type": "string"},
            },
            ["discovered_requirement_key", "acquired_inputs", "finding", "limitations"],
        ),
        _fn(
            "record_visual_finding_batch",
            "Persist factual visual findings for multiple requirements. Evidence type, tools, and source IDs are derived from inspection bundles.",
            {"findings": {"type": "array", "minItems": 1, "maxItems": 24, "items": {
                "type": "object", "additionalProperties": False,
                "required": ["discovered_requirement_key", "acquired_inputs",
                             "finding", "limitations"],
                "properties": {
                    "discovered_requirement_key": {"type": "string"},
                    "acquired_inputs": required_input_array,
                    "finding": {"type": "string"},
                    "limitations": {"type": "string"},
                },
            }}}, ["findings"],
        ),
        _fn(
            "record_measurement_finding",
            "Persist the quality-gated result of one registered measurement job. Input status and source IDs are derived by the program.",
            {
                "measurement_job_id": {"type": "string"},
                "finding": {"type": "string"},
                "limitations": {"type": "string"},
            },
            ["measurement_job_id", "finding", "limitations"],
        ),
        _fn(
            "record_measurement_finding_batch",
            "Persist quality-gated results for multiple completed registered measurement jobs.",
            {"findings": {"type": "array", "minItems": 1, "maxItems": 12, "items": {
                "type": "object", "additionalProperties": False,
                "required": ["measurement_job_id", "finding", "limitations"],
                "properties": {
                    "measurement_job_id": {"type": "string"},
                    "finding": {"type": "string"},
                    "limitations": {"type": "string"},
                },
            }}}, ["findings"],
        ),
        _fn(
            "record_acquisition_failure",
            "Persist unresolved inputs from a recorded failed or blocked acquisition attempt.",
            {
                "attempt_id": {"type": "string"},
                "reason": {"type": "string"},
                "limitations": {"type": "string"},
            },
            ["attempt_id", "reason", "limitations"],
        ),
        _fn(
            "get_stage4_readiness",
            "Return missing jobs, unaccounted inputs, measurement records, and provenance gaps without attempting to seal Stage 4.",
            {}, [],
        ),
    ]


def orchestrated_stage5_tool_definitions() -> list[dict]:
    """Stage 5 conclusion tools; evidence linkage is program-composed."""
    conclusion = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "discovered_requirement_key", "normative_applicability",
            "inspection_status", "inspection_reason",
        ],
        "properties": {
            "discovered_requirement_key": {"type": "string"},
            "normative_applicability": {
                "enum": ["true", "false", "indeterminate"]
            },
            "inspection_status": {
                "enum": ["satisfied", "deficient", "not_assessed"]
            },
            "inspection_reason": {"type": "string"},
        },
    }
    return [
        _fn(
            "get_stage5_conclusion_plan",
            "Freeze the evidence-bound conclusion jobs for every registered requirement.",
            {}, [],
        ),
        _fn(
            "record_stage5_conclusion_batch",
            "Record one evidence-grounded conclusion draft per pending requirement. Provenance and availability are program-bound.",
            {"conclusions": {
                "type": "array", "minItems": 1, "maxItems": 12,
                "items": conclusion,
            }},
            ["conclusions"],
        ),
        _fn(
            "get_stage5_readiness",
            "Check conclusion completeness, evidence linkage, status constraints, and modality preservation.",
            {}, [],
        ),
        _fn(
            "seal_conclusions",
            "Seal the complete Stage 5 conclusion ledger and enter Stage 6 result submission.",
            {}, [],
        ),
    ]


def orchestrated_stage6_tool_definitions() -> list[dict]:
    """Deterministic Stage 6 transfer from sealed conclusion drafts."""
    return [
        _fn(
            "submit_next_stage6_batch",
            "Copy the next program-selected batch of sealed Stage 5 drafts into final inspection records without model rewriting.",
            {}, [],
        ),
        _fn(
            "finalize_stage6",
            "Finalize the registry after every sealed Stage 5 draft has been copied exactly once.",
            {}, [],
        ),
    ]


def _definitions_by_name() -> dict[str, dict]:
    rows = (retrieval_tool_definitions() + scene_tool_definitions() +
            orchestrated_stage4_tool_definitions() + orchestrated_stage5_tool_definitions() +
            orchestrated_stage6_tool_definitions() +
            registry_tool_definitions() +
            scoped_discovery_registration_definitions())
    return {row["name"]: row for row in rows}


def _contains_hidden_id(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key == "requirement_id" or _contains_hidden_id(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_hidden_id(item) for item in value)
    return False


def _canonical_modality(value: Any) -> str | None:
    return {"shall": "shall", "standard": "shall",
            "should": "should", "guidance": "should"}.get(str(value).lower())


PROJECT_SCOPE_EXCLUSION_TAGS = {
    "pavement_markings", "buffer_or_activity_area",
    "positive_protection_or_attenuator", "pedestrian_bicycle_accessibility",
    "nighttime_or_illumination", "opposing_direction_only",
    "material_or_crashworthiness_specification", "mounting_height",
    "device_product_specification",
}


def _project_scope_exclusion(node: dict) -> str | None:
    """Return an explicit structured exclusion tag, never a prose keyword hit.

    Source spans and thresholds often mention neighboring TTC areas or referenced
    material.  Treating any such word as the provision's subject caused valid
    sign and taper rules to disappear.  The index builder now assigns conservative
    predicate-level tags; untagged ambiguity is retained for Stage-2 review.
    """
    tags = set(node.get("scope_tags") or [])
    matches = sorted(tags & PROJECT_SCOPE_EXCLUSION_TAGS)
    return matches[0] if matches else None


class ToolGatewayV5:
    def __init__(self, selected_layouts: list[dict], scene_view: dict | None = None,
                 scoped_stage1_stage2: bool = False,
                 simplified_inspection_checks: bool = False,
                 orchestrated_stage4: bool = False,
                 orchestrated_stage5: bool = False,
                 gap_retrieval: dict | None = None,
                 scene_manifest: str | Path | None = None) -> None:
        self.retrieval = StructuredBM25V5()
        self.gap_retrieval = deepcopy(gap_retrieval or {"method": "bm25"})
        self.stage1_architecture = self.gap_retrieval.get(
            "architecture", "kg_plus_retrieval"
        )
        if self.stage1_architecture not in {
            "kg_plus_retrieval", "kg_only", "retrieval_only"
        }:
            raise ValueError(
                f"unknown Stage 1 architecture: {self.stage1_architecture}"
            )
        self.knowledge_graph = MutcdKnowledgeGraphV2(
            self.retrieval, gap_retrieval=self.gap_retrieval
        )
        self.scene = SceneDataToolsV5(scene_manifest)
        self.registry = InspectionRegistry(self.scene.scene_id, selected_layouts)
        self.scene_view = deepcopy(scene_view or {})
        self.scoped_stage1_stage2 = scoped_stage1_stage2
        self.simplified_inspection_checks = simplified_inspection_checks
        self.orchestrated_stage4 = orchestrated_stage4
        self.orchestrated_stage5 = orchestrated_stage5
        self.discovery_coverage = {domain: {"status": "pending", "query_summary": "",
                                            "source_node_ids": []}
                                   for domain in COVERAGE_DOMAINS}
        self.information_need_searches = {
            domain: {need: [] for need in needs}
            for domain, needs in SCOPED_INFORMATION_NEEDS.items()
        }
        self.information_need_expansions = {
            domain: {need: [] for need in needs}
            for domain, needs in SCOPED_INFORMATION_NEEDS.items()
        }
        self.information_need_node_ids = {
            domain: {need: set() for need in needs}
            for domain, needs in SCOPED_INFORMATION_NEEDS.items()
        }
        self.information_need_primary_node_ids = {
            domain: {need: None for need in needs}
            for domain, needs in SCOPED_INFORMATION_NEEDS.items()
        }
        self.information_need_expansion_results: dict[tuple[str, str, str], dict] = {}
        self.discovery_candidate_exclusions = {domain: {} for domain in COVERAGE_DOMAINS}
        self.graph_stage1a_result: dict | None = None
        self.graph_stage1b_result: dict | None = None
        self.graph_gap_audits = {domain: [] for domain in COVERAGE_DOMAINS}
        self.graph_candidate_node_ids = {domain: set() for domain in COVERAGE_DOMAINS}
        self.graph_deterministic_node_ids = {domain: set() for domain in COVERAGE_DOMAINS}
        self.graph_high_confidence_node_ids = {domain: set() for domain in COVERAGE_DOMAINS}
        self.graph_candidate_provenance: dict[str, list[dict]] = {}
        self.high_confidence_disposition_gaps: list[dict] = []
        # Stage 2 is compiled once by the model and then independently checked
        # against the deterministic KG pool.  A successful registration or
        # exclusion makes the previous audit stale, so sealing can never rely
        # on an audit performed before the final decisions.
        self.stage2_decision_revision = 0
        self.stage2_audit_revision: int | None = None
        self.stage2_candidate_audit_calls = 0
        self.stage2_audited_node_ids: set[str] = set()
        self.stage2_candidate_decisions: dict[str, dict] = {}
        self.stage2_verification_unresolved: list[dict] = []
        self.trace: list[dict] = []
        self.resume_trace_length = 0
        self.resume_tool_failure_count = 0
        self.tool_failures = 0
        self.retries = 0
        self.cache: dict[str, dict] = {}
        self.retrieved_nodes: dict[str, dict] = {}

    @classmethod
    def from_checkpoint(cls, selected_layouts: list[dict], scene_view: dict,
                        registry_snapshot: dict, trace: list[dict],
                        scoped_stage1_stage2: bool = False,
                        simplified_inspection_checks: bool = False,
                        orchestrated_stage4: bool = False,
                        orchestrated_stage5: bool = False,
                        gap_retrieval: dict | None = None,
                        scene_manifest: str | Path | None = None) -> "ToolGatewayV5":
        gateway = cls(selected_layouts, scene_view, scoped_stage1_stage2,
                      simplified_inspection_checks, orchestrated_stage4,
                      orchestrated_stage5, gap_retrieval, scene_manifest)
        gateway.registry = InspectionRegistry.from_snapshot(registry_snapshot)
        gateway.scene.measurements.update(deepcopy(gateway.registry.measurement_records))
        gateway.trace = deepcopy(trace)
        gateway.resume_trace_length = len(trace)
        gateway.resume_tool_failure_count = sum(
            row.get("result", {}).get("status") == "failure" for row in trace
        )
        gateway.tool_failures = sum(
            row.get("result", {}).get("status") == "failure" for row in trace
        )
        for row in trace:
            if (row.get("tool") in NORMATIVE_MEASUREMENT_TOOLS and
                    row.get("result", {}).get("measurement_id")):
                measurement = deepcopy(row["result"])
                gateway.scene.measurements[measurement["measurement_id"]] = measurement
            if row.get("tool") in RETRIEVAL_TOOLS:
                gateway._remember_retrieved_nodes(row.get("result", {}))
            elif row.get("tool") == "search_manual_for_need":
                gateway._remember_retrieved_nodes(row.get("result", {}))
                if row.get("result", {}).get("status") != "failure":
                    arguments = row.get("arguments", {})
                    domain, need = arguments.get("domain"), arguments.get("information_need")
                    if domain in gateway.information_need_searches and need in gateway.information_need_searches[domain]:
                        gateway.information_need_searches[domain][need].append({
                            "query": row.get("result", {}).get("resolved_query"),
                            "returned_count": len(row.get("result", {}).get("items", [])),
                            "source_unit_codes": [item.get("source_unit_code")
                                                  for item in row.get("result", {}).get("items", [])],
                        })
                        gateway.information_need_expansions[domain][need].extend(
                            row.get("result", {}).get("automatically_expanded_source_unit_codes", [])
                        )
                        gateway.information_need_node_ids[domain][need].update(
                            item.get("source_node_id")
                            for item in row.get("result", {}).get("atomic_items", [])
                            if item.get("source_node_id")
                        )
                        atomic_items = row.get("result", {}).get("atomic_items", [])
                        if atomic_items:
                            gateway.information_need_primary_node_ids[domain][need] = atomic_items[0].get(
                                "source_node_id"
                            )
            elif row.get("tool") == "expand_source_unit_for_need":
                gateway._remember_retrieved_nodes(row.get("result", {}))
                arguments = row.get("arguments", {})
                domain, need = arguments.get("domain"), arguments.get("information_need")
                if domain in gateway.information_need_expansions and need in gateway.information_need_expansions[domain]:
                    gateway.information_need_expansions[domain][need].append(arguments.get("source_unit_code"))
                    if row.get("result", {}).get("status") != "failure":
                        gateway.information_need_expansion_results[(
                            domain, need, arguments.get("source_unit_code")
                        )] = deepcopy(row.get("result", {}))
                        gateway.information_need_node_ids[domain][need].update(
                            item.get("source_node_id")
                            for item in row.get("result", {}).get("items", [])
                            if item.get("source_node_id")
                        )
                        items = row.get("result", {}).get("items", [])
                        if items and gateway.information_need_primary_node_ids[domain][need] is None:
                            gateway.information_need_primary_node_ids[domain][need] = items[0].get("source_node_id")
            elif row.get("tool") == "record_domain_discovery" and row.get("result", {}).get("domain"):
                domain = row["result"]["domain"]
                gateway.discovery_coverage[domain] = deepcopy(row["result"])
            elif (row.get("tool") == "exclude_discovery_candidate_batch" and
                  row.get("result", {}).get("accepted_exclusions")):
                domain = row.get("arguments", {}).get("domain")
                if domain in gateway.discovery_candidate_exclusions:
                    for item in row["result"]["accepted_exclusions"]:
                        gateway.discovery_candidate_exclusions[domain][item["source_node_id"]] = deepcopy(item)
            if (row.get("tool") in {"submit_atomic_requirement_batch",
                                    "submit_inspection_check_batch"} and
                    row.get("result", {}).get("accepted_requirement_keys")):
                gateway.stage2_decision_revision += 1
            elif (row.get("tool") == "exclude_discovery_candidate_batch" and
                  row.get("result", {}).get("accepted_exclusions")):
                gateway.stage2_decision_revision += 1
            elif (row.get("tool") == "audit_stage2_candidate_coverage" and
                  row.get("result", {}).get("status") != "failure"):
                gateway.stage2_candidate_audit_calls += 1
                gateway.stage2_audit_revision = gateway.stage2_decision_revision
                gateway.stage2_audited_node_ids.update(
                    item.get("source_node_id")
                    for item in row.get("result", {}).get("unresolved_candidates", [])
                    if item.get("source_node_id")
                )
                gateway.stage2_verification_unresolved = deepcopy(
                    row.get("result", {}).get("all_unresolved_candidates", []) or
                    row.get("result", {}).get("unresolved_candidates", [])
                )
            elif (row.get("tool") == "submit_stage2_candidate_decision_batch" and
                  row.get("result", {}).get("accepted_decisions")):
                for item in row["result"]["accepted_decisions"]:
                    if item.get("source_node_id"):
                        gateway.stage2_candidate_decisions[item["source_node_id"]] = deepcopy(item)
                gateway.stage2_decision_revision += 1
        if scoped_stage1_stage2:
            successful_tools = [
                row for row in trace if row.get("result", {}).get("status") != "failure"
            ]
            if any(row.get("tool") == "load_ta_core_graph" for row in successful_tools):
                core = gateway.knowledge_graph.ta_core(gateway._primary_layout_code())
                gateway._ingest_graph_candidates(core["candidates"], deterministic=True)
                for node_id in core["ta_evidence_node_ids"]:
                    gateway.retrieved_nodes[node_id] = deepcopy(
                        gateway.knowledge_graph._node_view(node_id)
                    )
                gateway.graph_stage1a_result = core
            if (gateway.graph_stage1a_result is not None and
                    any(row.get("tool") == "load_scene_condition_graph"
                        for row in successful_tools)):
                conditional = gateway.knowledge_graph.scene_conditions(
                    gateway.scene_view,
                    gateway.graph_stage1a_result["inferred_required_component_ids"],
                )
                gateway._ingest_graph_candidates(conditional["candidates"], deterministic=True)
                gateway.graph_stage1b_result = conditional
            for row in successful_tools:
                if row.get("tool") not in {"audit_graph_gaps", "load_domain_gap_candidates"}:
                    continue
                domain = row.get("arguments", {}).get("domain")
                if domain not in gateway.graph_gap_audits:
                    continue
                result = deepcopy(row.get("result", {}))
                reconstructed = []
                for item in result.get("items", []):
                    node_id = item.get("source_node_id")
                    if node_id not in gateway.knowledge_graph.raw_node_by_id:
                        continue
                    reconstructed.append({
                        "source_node": gateway.knowledge_graph._node_view(node_id),
                        "domains": [domain],
                        "layers": ["stage1c_graph_gap_audit"],
                        "graph_paths": [[
                            f"uncovered {domain} provision found by completeness audit"
                        ]],
                        "activation_evidence": [{
                            "type": "graph_gap", "domain": domain,
                            "query": result.get("query"),
                        }],
                    })
                gateway._ingest_graph_candidates(reconstructed, deterministic=False)
                gateway.graph_gap_audits[domain].append(result)
        return gateway

    @staticmethod
    def definitions(include_registry: bool = True) -> list[dict]:
        tools = (retrieval_tool_definitions() + scene_tool_definitions() +
                 orchestrated_stage4_tool_definitions() +
                 orchestrated_stage5_tool_definitions() +
                 orchestrated_stage6_tool_definitions())
        return tools + (registry_tool_definitions() + scoped_discovery_registration_definitions()
                        if include_registry else [])

    def available_definitions(self) -> list[dict]:
        names_by_phase = {
            "requirement_discovery": RETRIEVAL_TOOLS | {"begin_requirement_registration"},
            "requirement_registration": {"submit_requirement_batch", "complete_region_batch", "seal_requirement_registration"},
            "data_availability": INVENTORY_TOOLS | {"submit_data_availability_batch", "seal_data_availability"},
            "measurement": {row["name"] for row in scene_tool_definitions()} |
                           {"record_evidence_batch", "seal_measurements"},
            "inspection_conclusion": {"begin_result_submission"},
            "result_submission": {"submit_inspection_batch", "finalize_registry"},
            "finalized": set(),
        }
        if self.orchestrated_stage4:
            if self.registry.stage4_plan is None:
                names_by_phase["measurement"] = {"get_stage4_acquisition_plan"}
            else:
                plan = self.registry.stage4_plan
                completed_visual = {
                    row.get("visual_job_id") for row in self.registry.inspection_bundles.values()
                }
                unnoted_visual = {
                    row.get("visual_job_id") for row in self.registry.inspection_bundles.values()
                    if row.get("model_observation") is None
                }
                pending_visual = {
                    row["visual_job_id"] for row in plan.get("visual_jobs", [])
                    if row["visual_job_id"] not in completed_visual
                }
                accounted_by_key: dict[str, set[str]] = {
                    key: set() for key in self.registry.requirements
                }
                for evidence in self.registry.evidence_records.values():
                    accounted_by_key[evidence["discovered_requirement_key"]].update(
                        evidence.get("acquired_inputs", []) + evidence.get("unresolved_inputs", [])
                    )
                visual_targets = {
                    key: {
                        value for job in plan.get("visual_jobs", [])
                        for value in job.get("target_inputs_by_requirement", {}).get(key, [])
                    }
                    for key in self.registry.requirements
                }
                remaining_visual = {
                    key: targets - accounted_by_key[key]
                    for key, targets in visual_targets.items()
                    if targets - accounted_by_key[key]
                }
                attempts_by_job = {
                    row.get("measurement_job_id"): row
                    for row in self.registry.acquisition_attempts.values()
                    if row.get("measurement_job_id")
                }
                pending_measurements = {
                    row["measurement_job_id"] for row in plan.get("measurement_jobs", [])
                    if row["measurement_job_id"] not in attempts_by_job
                }
                cited_attempts = {
                    row.get("acquisition_attempt_id")
                    for row in self.registry.evidence_records.values()
                    if row.get("acquisition_attempt_id")
                }
                unrecorded_measurements = {
                    job_id for job_id, attempt in attempts_by_job.items()
                    if attempt["attempt_id"] not in cited_attempts
                }
                if unnoted_visual:
                    names = {"record_visual_job_note"}
                elif pending_visual:
                    names = {"inspect_stage4_visual_job"}
                elif remaining_visual:
                    names = {"record_visual_finding_batch"}
                elif pending_measurements:
                    names = {"run_registered_measurement"}
                elif unrecorded_measurements:
                    names = {"record_measurement_finding_batch"}
                elif (self.registry.stage4_readiness or {}).get("ready") is True:
                    names = {"seal_measurements"}
                else:
                    names = {"get_stage4_readiness"}
                names_by_phase["measurement"] = names
        if self.orchestrated_stage5:
            if self.registry.stage5_plan is None:
                names_by_phase["inspection_conclusion"] = {"get_stage5_conclusion_plan"}
            else:
                pending_conclusions = set(self.registry.requirements) - set(
                    self.registry.conclusion_drafts
                )
                if pending_conclusions:
                    names_by_phase["inspection_conclusion"] = {
                        "record_stage5_conclusion_batch"
                    }
                elif (self.registry.stage5_readiness or {}).get("ready") is True:
                    names_by_phase["inspection_conclusion"] = {"seal_conclusions"}
                else:
                    names_by_phase["inspection_conclusion"] = {"get_stage5_readiness"}
        if self.scoped_stage1_stage2:
            names_by_phase["requirement_discovery"] = {
                "load_ta_core_graph", "load_scene_condition_graph", "audit_graph_gaps",
                "record_domain_discovery", "begin_requirement_registration",
            }
            names_by_phase["requirement_registration"] = {
                "submit_atomic_requirement_batch", "exclude_discovery_candidate_batch", "complete_region_batch",
                "seal_requirement_registration",
            }
        if self.simplified_inspection_checks:
            if self.stage1_architecture == "kg_only":
                discovery_names = {
                    "load_ta_core_graph", "load_scene_condition_graph",
                    "begin_requirement_registration",
                }
            elif self.stage1_architecture == "retrieval_only":
                discovery_names = {
                    "load_domain_gap_candidates", "begin_requirement_registration",
                }
            else:
                discovery_names = {
                    "load_ta_core_graph", "load_scene_condition_graph",
                    "load_domain_gap_candidates", "begin_requirement_registration",
                }
            names_by_phase["requirement_discovery"] = discovery_names
            names_by_phase["requirement_registration"] = {
                "submit_inspection_check_batch", "exclude_discovery_candidate_batch",
                "complete_region_batch",
                "seal_requirement_registration",
            }
            if self.stage1_architecture in {"kg_plus_retrieval", "kg_only"}:
                names_by_phase["requirement_registration"].update({
                    "audit_stage2_candidate_coverage",
                    "submit_stage2_candidate_decision_batch",
                })
        definitions = _definitions_by_name()
        if self.orchestrated_stage5 and self.registry.phase == "result_submission":
            pending_results = set(self.registry.requirements) - set(self.registry.inspections)
            names_by_phase["result_submission"] = (
                {"submit_next_stage6_batch"} if pending_results else {"finalize_stage6"}
            )
        rows = [deepcopy(definitions[name]) for name in sorted(names_by_phase[self.registry.phase])]
        if (self.orchestrated_stage4 and self.registry.phase == "measurement" and
                self.registry.stage4_plan is not None):
            plan = self.registry.stage4_plan
            completed_visual = {
                row.get("visual_job_id") for row in self.registry.inspection_bundles.values()
            }
            pending_visual = sorted(
                row["visual_job_id"] for row in plan.get("visual_jobs", [])
                if row["visual_job_id"] not in completed_visual
            )
            unnoted_visual = sorted(
                row.get("visual_job_id") for row in self.registry.inspection_bundles.values()
                if row.get("model_observation") is None
            )
            attempts_by_job = {
                row.get("measurement_job_id"): row
                for row in self.registry.acquisition_attempts.values()
                if row.get("measurement_job_id")
            }
            pending_measurements = sorted(
                row["measurement_job_id"] for row in plan.get("measurement_jobs", [])
                if row["measurement_job_id"] not in attempts_by_job
            )
            cited_attempts = {
                row.get("acquisition_attempt_id")
                for row in self.registry.evidence_records.values()
                if row.get("acquisition_attempt_id")
            }
            unrecorded_measurements = sorted(
                job_id for job_id, attempt in attempts_by_job.items()
                if attempt["attempt_id"] not in cited_attempts
            )
            accounted_by_key: dict[str, set[str]] = {
                key: set() for key in self.registry.requirements
            }
            for evidence in self.registry.evidence_records.values():
                accounted_by_key[evidence["discovered_requirement_key"]].update(
                    evidence.get("acquired_inputs", []) + evidence.get("unresolved_inputs", [])
                )
            remaining_visual = {
                key: sorted({
                    value for job in plan.get("visual_jobs", [])
                    for value in job.get("target_inputs_by_requirement", {}).get(key, [])
                } - accounted_by_key[key])
                for key in self.registry.requirements
            }
            remaining_visual = {key: values for key, values in remaining_visual.items() if values}
            for row in rows:
                name = row["name"]
                properties = row["parameters"]["properties"]
                if name == "inspect_stage4_visual_job":
                    properties["visual_job_id"] = {"enum": pending_visual}
                elif name == "record_visual_job_note":
                    properties["visual_job_id"] = {"enum": unnoted_visual}
                elif name == "run_registered_measurement":
                    # Expose exactly one deterministic job and only the arguments
                    # that its registered measurement actually consumes.  This
                    # prevents null placeholders, irrelevant arrays, and endpoint
                    # IDs copied from temporal frames rather than accepted
                    # observations.
                    next_job_id = pending_measurements[0] if pending_measurements else None
                    next_job = next((job for job in plan.get("measurement_jobs", [])
                                     if job["measurement_job_id"] == next_job_id), None)
                    runtime_properties = {
                        "measurement_job_id": {"enum": [next_job_id]} if next_job_id else {
                            "type": "string"
                        }
                    }
                    runtime_required = ["measurement_job_id"]
                    endpoint_tools = {
                        "measure_longitudinal_distance", "measure_taper_length",
                        "measure_buffer_length", "measure_sign_spacing",
                        "measure_downstream_taper",
                    }
                    inspected_observations = sorted({
                        source_id
                        for bundle in self.registry.inspection_bundles.values()
                        for source_id in bundle.get("source_ids", [])
                        if source_id in self.scene.observations
                    })
                    if next_job and next_job.get("tool") in endpoint_tools:
                        runtime_properties.update({
                            "start_observation_id": {"enum": inspected_observations},
                            "end_observation_id": {"enum": inspected_observations},
                        })
                        runtime_required.extend([
                            "start_observation_id", "end_observation_id"
                        ])
                    elif next_job and next_job.get("tool") in {
                        "measure_device_spacing", "estimate_available_width"
                    }:
                        runtime_properties["observation_ids"] = {
                            "type": "array",
                            "minItems": 2,
                            "items": {"enum": inspected_observations},
                        }
                        runtime_required.append("observation_ids")
                    row["parameters"]["properties"] = runtime_properties
                    row["parameters"]["required"] = runtime_required
                elif name == "record_visual_finding_batch":
                    properties["findings"]["maxItems"] = min(
                        self.registry.max_batch_size, max(1, len(remaining_visual))
                    )
                    finding_properties = properties["findings"]["items"]["properties"]
                    finding_properties["discovered_requirement_key"] = {
                        "enum": sorted(remaining_visual)
                    }
                    remaining_inputs = sorted({
                        value for values in remaining_visual.values() for value in values
                    })
                    finding_properties["acquired_inputs"]["items"] = {"enum": remaining_inputs}
                elif name == "record_measurement_finding_batch":
                    properties["findings"]["items"]["properties"]["measurement_job_id"] = {
                        "enum": unrecorded_measurements
                    }
        if (self.orchestrated_stage5 and self.registry.phase == "inspection_conclusion" and
                self.registry.stage5_plan is not None):
            pending = sorted(
                set(self.registry.requirements) - set(self.registry.conclusion_drafts)
            )
            for row in rows:
                if row["name"] != "record_stage5_conclusion_batch":
                    continue
                conclusions = row["parameters"]["properties"]["conclusions"]
                conclusions["minItems"] = 1
                conclusions["maxItems"] = min(
                    self.registry.max_batch_size, max(1, len(pending))
                )
                item_properties = conclusions["items"]["properties"]
                item_properties["discovered_requirement_key"] = {"enum": pending}
        return rows

    def _allowed(self, name: str) -> bool:
        return name in {row["name"] for row in self.available_definitions()}

    def _remember_retrieved_nodes(self, result: dict) -> None:
        for item in (result.get("items", []) + result.get("atomic_items", []) +
                     result.get("candidates", [])):
            node_id = item.get("source_node_id")
            if node_id:
                existing = self.retrieved_nodes.get(node_id)
                if existing is None or len(item) > len(existing):
                    self.retrieved_nodes[node_id] = deepcopy(item)

    def _validate_requirement_sources(self, args: dict) -> None:
        if _contains_hidden_id(args):
            raise RegistryError("internal requirement_id is forbidden")
        for requirement in args["requirements"]:
            nodes = []
            for node_id in requirement["source_node_ids"]:
                if node_id not in self.retrieved_nodes:
                    raise RegistryError(f"requirement source was not retrieved in this run: {node_id}")
                nodes.append(self.retrieved_nodes[node_id])
            matching_nodes = [node for node in nodes
                              if node.get("source_locator") == requirement["source_locator"]]
            if not matching_nodes:
                raise RegistryError("source_locator does not match a retrieved source node")
            source_modality = _canonical_modality(matching_nodes[0].get("modality"))
            if source_modality is None:
                raise RegistryError("selected source is not a Standard/shall or Guidance/should provision")
            if requirement.get("modality") != source_modality:
                raise RegistryError("registered modality does not match the selected retrieved source node")
            submitted_span = requirement["source_span"].strip()
            canonical_span = matching_nodes[0].get("source_span", "").strip()
            if not submitted_span or (submitted_span not in canonical_span and canonical_span not in submitted_span):
                raise RegistryError("source_span is not grounded in the selected retrieved source node")
            requirement["model_extracted_source_span"] = submitted_span
            requirement["source_span"] = canonical_span

    def _primary_layout_code(self) -> str:
        selected = self.registry.selected_layouts
        primary = next((row for row in selected
                        if row.get("layout_role") == "primary_applicable" or
                        row.get("role") == "primary"), selected[0] if selected else None)
        if not primary or not primary.get("layout_code"):
            raise RegistryError("Stage 1A requires one selected primary Typical Application")
        return str(primary["layout_code"])

    @staticmethod
    def _compact_graph_candidate(row: dict) -> dict:
        node = row["source_node"]
        return {
            "source_node_id": node["source_node_id"],
            "source_unit_code": node["source_unit_code"],
            "paragraph": node.get("paragraph"),
            "modality": node.get("modality"),
            "domains": row["domains"],
            "layers": row["layers"],
            "disposition_priority": row.get("disposition_priority", "review"),
            "source_excerpt": str(node.get("source_span", ""))[:420],
            "graph_paths": row["graph_paths"][:3],
            **({"gap_bm25_score": node["gap_bm25_score"]}
               if "gap_bm25_score" in node else {}),
            **({"gap_dense_score": node["gap_dense_score"]}
               if "gap_dense_score" in node else {}),
        }

    def _ingest_graph_candidates(self, rows: list[dict], deterministic: bool) -> None:
        for row in rows:
            node = row["source_node"]
            node_id = node["source_node_id"]
            self.retrieved_nodes[node_id] = deepcopy(node)
            self.graph_candidate_provenance.setdefault(node_id, []).extend(
                deepcopy(row.get("activation_evidence", []))
            )
            for domain in row["domains"]:
                self.graph_candidate_node_ids[domain].add(node_id)
                if deterministic:
                    self.graph_deterministic_node_ids[domain].add(node_id)
                    if row.get("disposition_priority") == "high":
                        self.graph_high_confidence_node_ids[domain].add(node_id)

    def _load_ta_core_graph(self) -> dict:
        if self.graph_stage1a_result is not None:
            raise RegistryError("Stage 1A TA-core graph query has already completed")
        result = self.knowledge_graph.ta_core(self._primary_layout_code())
        if self.simplified_inspection_checks:
            result["candidates"] = [
                row for row in result["candidates"]
                if _project_scope_exclusion(row["source_node"]) is None
            ]
        self._ingest_graph_candidates(result["candidates"], deterministic=True)
        for node_id in result["ta_evidence_node_ids"]:
            node = self.knowledge_graph._node_view(node_id)
            self.retrieved_nodes[node_id] = deepcopy(node)
        self.graph_stage1a_result = deepcopy(result)
        return {
            "layer": result["layer"], "layout_code": result["layout_code"],
            "ta": result["ta"], "components": result["components"],
            "source_units": result["source_units"],
            "ta_evidence_node_ids": result["ta_evidence_node_ids"],
            "inferred_required_component_ids": result["inferred_required_component_ids"],
            "candidate_count": len(result["candidates"]),
            "candidates": [self._compact_graph_candidate(row) for row in result["candidates"]],
        }

    def _load_scene_condition_graph(self) -> dict:
        if self.graph_stage1a_result is None:
            raise RegistryError("Stage 1B requires Stage 1A TA-core graph results")
        if self.graph_stage1b_result is not None:
            raise RegistryError("Stage 1B scene-condition graph query has already completed")
        result = self.knowledge_graph.scene_conditions(
            self.scene_view, self.graph_stage1a_result["inferred_required_component_ids"]
        )
        if self.simplified_inspection_checks:
            result["candidates"] = [
                row for row in result["candidates"]
                if _project_scope_exclusion(row["source_node"]) is None
            ]
        self._ingest_graph_candidates(result["candidates"], deterministic=True)
        self.graph_stage1b_result = deepcopy(result)
        return {
            "layer": result["layer"], "triggers": result["triggers"],
            "activated_component_ids": result["activated_component_ids"],
            "candidate_count": len(result["candidates"]),
            "candidates": [self._compact_graph_candidate(row) for row in result["candidates"]],
        }

    def _audit_graph_gaps(self, arguments: dict) -> dict:
        if self.graph_stage1a_result is None or self.graph_stage1b_result is None:
            raise RegistryError("Stage 1C requires completed Stage 1A and Stage 1B graph queries")
        domain = arguments["domain"]
        if self.graph_gap_audits[domain] and arguments["continuation_token"] is None:
            raise RegistryError(
                "graph-gap audit already started for this domain; continue with the returned token"
            )
        covered = self.graph_deterministic_node_ids[domain]
        result = self.knowledge_graph.gap_page(
            domain, covered, arguments["page_size"], arguments["continuation_token"]
        )
        rows = [{
            "source_node": node, "domains": [domain], "layers": [result["layer"]],
            "graph_paths": [[f"uncovered {domain} provision found by completeness audit"]],
            "activation_evidence": [{"type": "graph_gap", "domain": domain,
                                     "query": result["query"]}],
        } for node in result["items"]]
        self._ingest_graph_candidates(rows, deterministic=False)
        visible = {**result, "items": [self._compact_graph_candidate(row) for row in rows]}
        self.graph_gap_audits[domain].append(deepcopy(visible))
        return visible

    def _load_domain_gap_candidates(self, arguments: dict) -> dict:
        retrieval_only = self.stage1_architecture == "retrieval_only"
        if (not retrieval_only and
                (self.graph_stage1a_result is None or self.graph_stage1b_result is None)):
            raise RegistryError("simplified Stage 1C requires completed Stage 1A and Stage 1B")
        domain = arguments["domain"]
        if self.graph_gap_audits[domain]:
            raise RegistryError(f"simplified graph-gap audit already completed for {domain}")
        covered = (set() if retrieval_only else
                   self.graph_deterministic_node_ids[domain])
        token = None
        page_count = 0
        items: list[dict] = []
        first: dict | None = None
        while True:
            page = self.knowledge_graph.gap_page(
                domain, covered, 12, token,
                use_domain_filter=not retrieval_only,
            )
            first = first or page
            page_count += 1
            items.extend(page["items"])
            if not page["has_more"]:
                break
            token = page["continuation_token"]
        rows = [{
            "source_node": node, "domains": [domain],
            "layers": [first["layer"]],
            "graph_paths": [[
                (f"{domain} provision found by full-corpus retrieval"
                 if retrieval_only else
                 f"uncovered {domain} provision found by completeness audit")
            ]],
            "activation_evidence": [{"type": ("retrieval_only" if retrieval_only else "graph_gap"), "domain": domain,
                                     "query": first["query"]}],
        } for node in items]
        if self.simplified_inspection_checks:
            rows = [row for row in rows
                    if _project_scope_exclusion(row["source_node"]) is None]
        self._ingest_graph_candidates(rows, deterministic=False)
        visible = {
            "layer": first["layer"], "domain": domain,
            "query": first["query"], "covered_node_count": first["covered_node_count"],
            "uncovered_corpus_count": first["uncovered_corpus_count"],
            "uncovered_candidate_count": len(rows),
            "ranking_policy": first["ranking_policy"],
            "internal_page_count": page_count, "has_more": False,
            "continuation_token": None,
            "items": [self._compact_graph_candidate(row) for row in rows],
        }
        self.graph_gap_audits[domain].append(deepcopy(visible))
        return visible

    def _record_domain_discovery(self, arguments: dict) -> dict:
        domain = arguments["domain"]
        if self.scoped_stage1_stage2:
            if self.graph_stage1a_result is None or self.graph_stage1b_result is None:
                raise RegistryError("close domains only after Stage 1A and Stage 1B complete")
            if not self.graph_gap_audits[domain]:
                raise RegistryError(
                    f"{domain} requires at least one Stage 1C graph-gap audit before closure"
                )
            if self.graph_gap_audits[domain][-1].get("has_more"):
                raise RegistryError(
                    f"{domain} graph-gap audit is incomplete; continue with the returned token"
                )
            node_ids = list(dict.fromkeys(arguments["source_node_ids"]))
            allowed = self.graph_candidate_node_ids[domain]
            invalid = [node_id for node_id in node_ids if node_id not in allowed]
            if invalid:
                raise RegistryError(
                    f"candidate sources were not produced by Stage 1A/1B/1C for {domain}: {invalid}"
                )
            if arguments["status"] == "covered_with_candidates" and not node_ids:
                raise RegistryError("covered_with_candidates requires at least one graph candidate")
            if not arguments["query_summary"].strip():
                raise RegistryError("discovery ledger requires a non-empty query summary")
            row = {
                **deepcopy(arguments), "source_node_ids": node_ids,
                "stage1_layers": {
                    "stage1a_loaded": True, "stage1b_loaded": True,
                    "stage1c_pages_reviewed": len(self.graph_gap_audits[domain]),
                    "stage1c_has_more": bool(
                        self.graph_gap_audits[domain][-1].get("continuation_token")
                    ),
                },
            }
            self.discovery_coverage[domain] = row
            return row
        missing_needs = [need for need, searches in self.information_need_searches[domain].items()
                         if not searches]
        if missing_needs:
            raise RegistryError(f"domain information-need searches are incomplete: {missing_needs}")
        missing_expansions = [
            need for need in SCOPED_INFORMATION_NEEDS[domain]
            if need != "typical_application_context" and not self.information_need_expansions[domain][need]
        ]
        if missing_expansions:
            raise RegistryError(
                f"domain information-need source expansions are incomplete: {missing_expansions}"
            )
        if "typical_application_context" in SCOPED_INFORMATION_NEEDS[domain]:
            selected_codes = {row.get("layout_code") for row in self.registry.selected_layouts}
            if not any(node.get("source_unit_code") in selected_codes
                       for node in self.retrieved_nodes.values()):
                raise RegistryError("selected Typical Application must be expanded before closing the domain")
        node_ids = arguments["source_node_ids"]
        unique_node_ids = list(dict.fromkeys(node_ids))
        required_primary_nodes = {
            node_id for need, node_id in self.information_need_primary_node_ids[domain].items()
            if need != "typical_application_context" and node_id
        }
        omitted_primary_nodes = sorted(required_primary_nodes - set(unique_node_ids))
        if omitted_primary_nodes:
            raise RegistryError(
                f"{domain} candidate ledger omits program-ranked primary nodes for its review dimensions: "
                f"{omitted_primary_nodes}"
            )
        missing = [node_id for node_id in node_ids if node_id not in self.retrieved_nodes]
        domain_nodes = {
            node_id for values in self.information_need_node_ids[domain].values() for node_id in values
        }
        if domain == "lane_closure_layout":
            selected_codes = {row.get("layout_code") for row in self.registry.selected_layouts}
            domain_nodes.update(
                node_id for node_id, node in self.retrieved_nodes.items()
                if node.get("source_unit_code") in selected_codes
            )
        wrong_domain = [node_id for node_id in unique_node_ids
                        if node_id in self.retrieved_nodes and node_id not in domain_nodes]
        if wrong_domain:
            raise RegistryError(
                f"candidate sources were not retrieved for the declared domain {domain}: {wrong_domain}"
            )
        valid_node_ids = [node_id for node_id in unique_node_ids if node_id in self.retrieved_nodes]
        if arguments["status"] == "covered_with_candidates" and not valid_node_ids:
            raise RegistryError("covered_with_candidates requires at least one retrieved source node")
        if not arguments["query_summary"].strip():
            raise RegistryError("discovery ledger requires a non-empty query summary")
        row = {**deepcopy(arguments), "source_node_ids": valid_node_ids,
               "ignored_unretrieved_source_node_ids": missing,
               "information_needs_searched": {
            need: deepcopy(searches) for need, searches in self.information_need_searches[domain].items()
        }}
        self.discovery_coverage[domain] = row
        return row

    def _search_manual_for_need(self, arguments: dict) -> dict:
        domain, need = arguments["domain"], arguments["information_need"]
        if need not in SCOPED_INFORMATION_NEEDS[domain]:
            raise RegistryError(f"information need {need!r} does not belong to domain {domain!r}")
        if self.information_need_searches[domain][need]:
            raise RegistryError(
                "information need already searched; expand a returned source unit or close the domain"
            )
        if need == "typical_application_context":
            primary = next((row for row in self.registry.selected_layouts
                            if row.get("role") == "primary"), self.registry.selected_layouts[0])
            query = " ".join(str(primary.get(key) or "") for key in ("layout_code", "title")).strip()
            if not query:
                raise RegistryError("selected Typical Application lacks code/title for context query")
        else:
            query = INFORMATION_NEED_QUERIES[need]
        if need == "typical_application_context":
            result = self.retrieval.search_manual(
                query=query, page_size=SCOPED_SEARCH_UNIT_LIMIT, continuation_token=None,
            )
        else:
            result = self.retrieval.search_manual_by_structure(
                query=query,
                source_code_prefixes=list(SCOPED_DOMAIN_SOURCE_PREFIXES[domain]),
                result_limit=SCOPED_GOVERNING_UNIT_LIMIT,
            )
        ranked_units = result.get("items", [])
        atomic_rows: list[dict] = []
        expanded_codes: list[str] = []
        if need != "typical_application_context":
            candidate_codes: list[str] = []
            for item in ranked_units:
                code = item.get("source_unit_code")
                if item.get("unit_type") in {"section", "table"} and code and code not in candidate_codes:
                    candidate_codes.append(code)
                if len(candidate_codes) == SCOPED_AUTO_EXPAND_UNIT_LIMIT:
                    break
            for code in candidate_codes:
                token = None
                while True:
                    page = self.retrieval.expand_source_unit(code, None, 12, token)
                    atomic_rows.extend(page.get("items", []))
                    token = page.get("continuation_token")
                    if not token:
                        break
                expanded_codes.append(code)
            normative = [row for row in atomic_rows if _canonical_modality(row.get("modality"))]

            def relevance(row: dict) -> float:
                text = " ".join(str(row.get(key) or "")
                                for key in ("subject", "relation", "threshold", "source_span"))
                return max(similarity(query, text), subject_similarity(query, text))

            globally_ranked = sorted(normative, key=relevance, reverse=True)
            diverse: list[dict] = []
            selected_ids: set[str] = set()
            for row in globally_ranked[:SCOPED_GLOBAL_ATOM_SEED]:
                node_id = row.get("source_node_id")
                if node_id and node_id not in selected_ids:
                    diverse.append(row)
                    selected_ids.add(node_id)
            ranked_by_unit: dict[str, list[dict]] = {}
            for code in candidate_codes:
                ranked_by_unit[code] = sorted(
                    (row for row in normative if row.get("source_unit_code") == code),
                    key=relevance, reverse=True,
                )[:SCOPED_ATOMS_PER_UNIT]
            # Round-robin across governing units so one long section cannot
            # monopolize the atom budget and a lower-ranked unit cannot vanish.
            for depth in range(SCOPED_ATOMS_PER_UNIT):
                for code in candidate_codes:
                    unit_rows = ranked_by_unit[code]
                    if depth >= len(unit_rows):
                        continue
                    row = unit_rows[depth]
                    node_id = row.get("source_node_id")
                    if node_id and node_id not in selected_ids:
                        diverse.append(row)
                        selected_ids.add(node_id)
                    if len(diverse) >= SCOPED_ATOMIC_ITEM_LIMIT:
                        break
                if len(diverse) >= SCOPED_ATOMIC_ITEM_LIMIT:
                    break
            for row in globally_ranked:
                if len(diverse) >= SCOPED_ATOMIC_ITEM_LIMIT:
                    break
                node_id = row.get("source_node_id")
                if node_id and node_id not in selected_ids:
                    diverse.append(row)
                    selected_ids.add(node_id)
            atomic_rows = diverse[:SCOPED_ATOMIC_ITEM_LIMIT]
            self._remember_retrieved_nodes({"items": atomic_rows})
            result["atomic_items"] = [
                {key: row.get(key) for key in (
                    "source_node_id", "source_unit_code", "paragraph", "modality", "source_span",
                )}
                for row in atomic_rows
            ]
            result["automatically_expanded_source_unit_codes"] = expanded_codes
            self.information_need_expansions[domain][need].extend(expanded_codes)
        result["items"] = [
            {key: item.get(key) for key in (
                "rank", "score", "source_unit_code", "unit_type", "title", "chapter",
                "figure_code", "source_pages", "available_regions",
            )}
            for item in ranked_units
        ]
        self._remember_retrieved_nodes(result)
        self.information_need_node_ids[domain][need].update(
            row.get("source_node_id") for row in atomic_rows if row.get("source_node_id")
        )
        if atomic_rows:
            self.information_need_primary_node_ids[domain][need] = atomic_rows[0].get("source_node_id")
        self.information_need_searches[domain][need].append({
            "query": query, "returned_count": len(result.get("items", [])),
            "has_more": False,
            "source_unit_codes": [item.get("source_unit_code") for item in result.get("items", [])],
        })
        result["continuation_token"] = None
        result["has_more"] = False
        result["resolved_query"] = query
        result["atomic_item_count"] = len(atomic_rows)
        return result

    def _expand_source_unit_for_need(self, arguments: dict) -> dict:
        domain, need = arguments["domain"], arguments["information_need"]
        code = arguments["source_unit_code"]
        if need not in SCOPED_INFORMATION_NEEDS[domain]:
            raise RegistryError(f"information need {need!r} does not belong to domain {domain!r}")
        searches = self.information_need_searches[domain][need]
        if not searches:
            raise RegistryError("search the information need before expanding a source unit")
        allowed_codes = {item for search in searches for item in search.get("source_unit_codes", [])}
        if code not in allowed_codes:
            raise RegistryError("source unit was not returned for this information need")
        if code in self.information_need_expansions[domain][need]:
            cached = deepcopy(self.information_need_expansion_results.get((domain, need, code), {}))
            if cached:
                cached["cache_hit"] = True
                cached["already_expanded"] = True
                return cached
            raise RegistryError("source unit already expanded for this information need")
        rows: list[dict] = []
        token = None
        metadata = None
        while True:
            page = self.retrieval.expand_source_unit(code, None, 12, token)
            metadata = metadata or page.get("source_unit_metadata")
            rows.extend(page.get("items", []))
            token = page.get("continuation_token")
            if not token:
                break
        query = searches[0]["query"]
        normative = [row for row in rows if _canonical_modality(row.get("modality"))]
        ranked = sorted(
            normative,
            key=lambda row: max(
                similarity(query, " ".join(str(row.get(key) or "")
                                            for key in ("subject", "relation", "threshold", "source_span"))),
                subject_similarity(query, " ".join(str(row.get(key) or "")
                                                    for key in ("subject", "relation", "threshold", "source_span"))),
            ),
            reverse=True,
        )[:SCOPED_ATOMIC_ITEM_LIMIT]
        self._remember_retrieved_nodes({"items": ranked})
        self.information_need_node_ids[domain][need].update(
            row.get("source_node_id") for row in ranked if row.get("source_node_id")
        )
        if ranked and self.information_need_primary_node_ids[domain][need] is None:
            self.information_need_primary_node_ids[domain][need] = ranked[0].get("source_node_id")
        self.information_need_expansions[domain][need].append(code)
        result = {
            "operation": "expand_source_unit_for_need",
            "domain": domain,
            "information_need": need,
            "resolved_query": query,
            "source_unit_code": code,
            "source_unit_metadata": metadata,
            "items": ranked,
            "all_region_item_count": len(rows),
            "returned_normative_item_count": len(ranked),
            "continuation_token": None,
            "has_more": False,
        }
        self.information_need_expansion_results[(domain, need, code)] = deepcopy(result)
        return result

    def _submit_atomic_requirement_batch(self, arguments: dict) -> dict:
        """Validate and commit scoped Stage-2 requirements independently.

        Model-generated batches commonly contain a valid requirement next to one
        record with a malformed activation basis.  Treating the whole batch as a
        transaction silently discarded already-correct requirements when the
        model repaired only the rejected record.  Each item is therefore its own
        registry transaction; rejected items are returned with their label and
        reason while valid items remain durably registered.
        """
        accepted: list[dict] = []
        accepted_keys: list[str] = []
        rejected: list[dict] = []
        domain = arguments["domain"]
        requirements = arguments["requirements"]

        for index, requirement in enumerate(requirements):
            requirement = deepcopy(requirement)
            label = requirement.get("candidate_label") or f"item_{index}"
            try:
                node_id = requirement["source_node_id"]
                node = self.retrieved_nodes.get(node_id)
                if node is None:
                    raise RegistryError(f"source node was not retrieved in this run: {node_id}")
                if self.simplified_inspection_checks:
                    excluded_category = _project_scope_exclusion(node)
                    if excluded_category:
                        raise RegistryError(
                            f"excluded_project_scope: {excluded_category}"
                        )
                    if any(node_id in existing.get("source_node_ids", [])
                           for existing in self.registry.requirements.values()):
                        raise RegistryError(
                            "simplified checks must consolidate related branches from one source; "
                            "this source already supports a registered check"
                        )
                domain_candidates = set(self.discovery_coverage[domain].get("source_node_ids", []))
                if (self.discovery_coverage[domain].get("status") != "pending" and
                        node_id not in domain_candidates):
                    raise RegistryError(
                        f"source node is not in the {domain} discovery candidate ledger: {node_id}"
                    )
                facts = self.scene_view.get("scene_facts", {})
                if domain == "conditional_termination_area":
                    termination_triggers = (
                        "downstream_taper_present", "downstream_taper_deployed",
                        "end_road_work_sign_present", "termination_sign_present",
                    )
                    if not any(facts.get(key) is True for key in termination_triggers):
                        raise RegistryError(
                            "conditional termination requirements need an explicit true downstream-taper "
                            "or termination-sign presence fact; none is established in the frozen scene"
                        )
                modality = _canonical_modality(node.get("modality"))
                if modality is None:
                    raise RegistryError(
                        f"source modality {node.get('modality')!r} is not Standard/shall or Guidance/should"
                    )
                if node.get("node_type") == "figure_component":
                    selected_codes = {row.get("layout_code")
                                      for row in self.registry.selected_layouts}
                    if (node.get("source_unit_code") not in selected_codes or
                            not node.get("normative_basis") or modality != "should"):
                        raise RegistryError(
                            "a figure component is registrable only when it is non-optional "
                            "Guidance from the selected Typical Application and carries a "
                            "manual-derived normative basis"
                        )
                basis = requirement["activation_basis"]
                basis_type = basis["type"]
                fact_keys = basis["fact_keys"]
                evidence_node_ids = basis["evidence_source_node_ids"]
                if self.simplified_inspection_checks and basis_type != "unconditional":
                    facts = self.scene_view.get("scene_facts", {})
                    established_facts = [
                        key for key in fact_keys
                        if key in facts and facts[key] is not None and facts[key] is not False
                    ]
                    selected_codes = {row.get("layout_code")
                                      for row in self.registry.selected_layouts}
                    ta_evidence = [
                        item for item in evidence_node_ids
                        if self.retrieved_nodes.get(item, {}).get("source_unit_code")
                        in selected_codes
                    ]
                    if established_facts:
                        basis.update({"type": "scene_fact", "fact_keys": established_facts,
                                      "evidence_source_node_ids": []})
                    elif ta_evidence:
                        basis.update({"type": "selected_ta", "fact_keys": [],
                                      "evidence_source_node_ids": ta_evidence})
                    basis_type = basis["type"]
                    fact_keys = basis["fact_keys"]
                    evidence_node_ids = basis["evidence_source_node_ids"]
                if not basis["explanation"].strip():
                    raise RegistryError("activation basis requires a non-empty explanation")
                if basis_type == "unconditional":
                    if fact_keys or evidence_node_ids:
                        raise RegistryError(
                            "unconditional activation must not cite conditional facts or TA evidence"
                        )
                elif basis_type == "scene_fact":
                    facts = self.scene_view.get("scene_facts", {})
                    bad_facts = [key for key in fact_keys
                                 if key not in facts or facts[key] is None or facts[key] is False]
                    if not fact_keys or bad_facts:
                        raise RegistryError(
                            f"scene-fact activation is not established: {bad_facts or fact_keys}"
                        )
                    evidence_nodes = [self.retrieved_nodes.get(item) for item in evidence_node_ids]
                    if any(item is None for item in evidence_nodes):
                        raise RegistryError("scene-fact activation cites unretrieved evidence")
                    if any(str(item.get("source_unit_code", "")).startswith("TA-")
                           for item in evidence_nodes):
                        raise RegistryError(
                            "scene-fact activation cannot cite TA evidence; use combined activation"
                        )
                elif basis_type == "selected_ta":
                    selected_codes = {row.get("layout_code") for row in self.registry.selected_layouts}
                    evidence_nodes = [self.retrieved_nodes.get(item) for item in evidence_node_ids]
                    if (not evidence_nodes or any(item is None for item in evidence_nodes) or
                            any(item.get("source_unit_code") not in selected_codes for item in evidence_nodes)):
                        raise RegistryError(
                            "selected-TA activation requires retrieved evidence from the selected TA"
                        )
                    if fact_keys:
                        raise RegistryError("selected-TA activation must not cite scene fact keys")
                elif basis_type == "combined":
                    facts = self.scene_view.get("scene_facts", {})
                    bad_facts = [key for key in fact_keys
                                 if key not in facts or facts[key] is None or facts[key] is False]
                    selected_codes = {row.get("layout_code") for row in self.registry.selected_layouts}
                    evidence_nodes = [self.retrieved_nodes.get(item) for item in evidence_node_ids]
                    if not fact_keys or bad_facts:
                        raise RegistryError(
                            f"combined activation has unestablished scene facts: {bad_facts or fact_keys}"
                        )
                    if (not evidence_nodes or any(item is None for item in evidence_nodes) or
                            not any(item.get("source_unit_code") in selected_codes for item in evidence_nodes)):
                        raise RegistryError(
                            "combined activation requires retrieved evidence from the selected TA"
                        )
                locator, span = node.get("source_locator"), node.get("source_span")
                if node.get("node_type") == "figure_component":
                    basis = node["normative_basis"]
                    locator = (
                        f"{locator}; Guidance basis {basis['source_unit_code']} "
                        f"paragraph {basis['paragraph']}"
                    )
                if not locator or not span:
                    raise RegistryError("retrieved source node lacks canonical locator or source span")
                enriched = {
                    **deepcopy(requirement), "source_node_ids": [node_id], "modality": modality,
                    "source_locator": locator, "source_span": span,
                }
                enriched.pop("source_node_id", None)
                incoming_text = " ".join(str(enriched.get(key) or "") for key in (
                    "candidate_label", "subject", "relation", "threshold", "applicability_conditions"
                ))
                incoming_conditions = {
                    str(row.get("condition", "")).strip().lower()
                    for row in enriched["measurement_spec"].get("thresholds", [])
                }
                for existing_key, existing in self.registry.requirements.items():
                    if (existing.get("region") != domain or
                            existing.get("modality") != modality or
                            existing.get("source_locator") != locator):
                        continue
                    existing_text = " ".join(str(existing.get(key) or "") for key in (
                        "candidate_label", "subject", "relation", "threshold", "applicability_conditions"
                    ))
                    existing_conditions = {
                        str(row.get("condition", "")).strip().lower()
                        for row in existing.get("measurement_spec", {}).get("thresholds", [])
                    }
                    distinct_measured_branches = (
                        incoming_conditions and existing_conditions and
                        incoming_conditions.isdisjoint(existing_conditions)
                    )
                    if not distinct_measured_branches and similarity(incoming_text, existing_text) >= 0.82:
                        raise RegistryError(
                            f"semantic duplicate of already registered requirement {existing_key}"
                        )
                result = self.registry.submit_requirement_batch(domain, [enriched])
                accepted.extend(result["accepted_requirements"])
                accepted_keys.extend(result["accepted_requirement_keys"])
                self.discovery_candidate_exclusions[domain].pop(node_id, None)
            except RegistryError as exc:
                rejected.append({"candidate_label": label, "failure_reason": str(exc)})

        if not accepted:
            details = "; ".join(
                f"{row['candidate_label']}: {row['failure_reason']}" for row in rejected
            )
            raise RegistryError(f"atomic batch for {domain} rejected: {details}")
        self.stage2_decision_revision += 1
        result = {
            "accepted_requirements": accepted,
            "accepted_requirement_keys": accepted_keys,
            "rejected_requirements": rejected,
            "registry_requirement_count": len(self.registry.requirements),
        }
        if rejected:
            result["status"] = "partial_success"
            result["repair_instruction"] = (
                "Accepted records are already durable. Resubmit only corrected rejected_requirements; "
                "do not resubmit accepted records."
            )
        return result

    def _exclude_discovery_candidate_batch(self, arguments: dict) -> dict:
        domain = arguments["domain"]
        candidates = set(self.discovery_coverage[domain].get("source_node_ids", []))
        registered = {
            node_id
            for requirement in self.registry.requirements.values()
            if requirement.get("region") == domain
            for node_id in requirement.get("source_node_ids", [])
        }
        accepted, rejected = [], []

        def validate_and_store(item: dict) -> dict:
            node_id = item["source_node_id"]
            if node_id not in candidates:
                raise RegistryError(
                    f"{node_id}: candidate is not in the {domain} discovery ledger"
                )
            if node_id in registered:
                raise RegistryError(
                    f"{node_id}: candidate already supports a registered requirement"
                )
            if not item["reason"].strip():
                raise RegistryError(f"{node_id}: exclusion requires a non-empty reason")
            node = self.retrieved_nodes.get(node_id, {})
            reason_code = item["reason_code"]
            if reason_code == "excluded_project_scope":
                category = _project_scope_exclusion(node)
                if category is None:
                    raise RegistryError(
                        f"{node_id}: excluded_project_scope requires a structured scope tag"
                    )
            if reason_code == "non_normative_context" and _canonical_modality(
                    node.get("modality")) is not None:
                raise RegistryError(
                    f"{node_id}: a Standard/Guidance candidate is normative context"
                )
            if (reason_code == "not_a_field_inspection_predicate" and
                    node_id in self.graph_high_confidence_node_ids[domain]):
                raise RegistryError(
                    f"{node_id}: high-confidence Standard/Guidance candidates cannot be silently "
                    "discarded as non-field; register the observable predicate or use a "
                    "verifiable activation, scope, or duplicate reason"
                )
            if reason_code == "duplicate_same_compliance_predicate":
                candidate_text = " ".join(str(node.get(key) or "") for key in (
                    "subject", "relation", "threshold", "applicability_conditions"
                ))
                candidate_modality = _canonical_modality(node.get("modality"))
                duplicates = []
                for requirement in self.registry.requirements.values():
                    if (requirement.get("region") != domain or
                            requirement.get("modality") != candidate_modality):
                        continue
                    if node_id in requirement.get("source_node_ids", []):
                        duplicates.append((1.0, requirement))
                        continue
                    requirement_text = " ".join(
                        str(requirement.get(key) or "") for key in (
                            "subject", "relation", "threshold", "applicability_conditions"
                        )
                    )
                    score = similarity(candidate_text, requirement_text)
                    if score >= 0.82:
                        duplicates.append((score, requirement))
                if not duplicates:
                    raise RegistryError(
                        f"{node_id}: duplicate exclusion is not supported by a registered "
                        "same-modality predicate with high semantic equivalence"
                    )
            record = deepcopy(item)
            self.discovery_candidate_exclusions[domain][node_id] = record
            return record

        for item in arguments["exclusions"]:
            try:
                accepted.append(validate_and_store(item))
            except RegistryError as exc:
                rejected.append({
                    "source_node_id": item.get("source_node_id"),
                    "reason_code": item.get("reason_code"),
                    "failure_reason": str(exc),
                })
        if not accepted:
            details = "; ".join(
                f"{row['source_node_id']}: {row['failure_reason']}" for row in rejected
            )
            raise RegistryError(f"candidate exclusion batch for {domain} rejected: {details}")
        self.stage2_decision_revision += 1
        result = {
            "domain": domain, "accepted_exclusions": accepted,
            "rejected_exclusions": rejected,
            "candidate_exclusion_count": len(self.discovery_candidate_exclusions[domain]),
        }
        if rejected:
            result["status"] = "partial_success"
            result["repair_instruction"] = (
                "Accepted exclusions are already durable. Repair only rejected_exclusions."
            )
        return result

    def _audit_stage2_candidate_coverage(self) -> dict:
        """Expose unresolved deterministic KG predicates for a second-pass review.

        This is deliberately a structural verifier rather than a case answer
        list.  It is built only from the run's deterministic graph expansion,
        canonical manual nodes, structured project-scope tags, and the current
        registration/exclusion state.  No evaluator gold data is read here.
        """
        globally_registered = {
            node_id
            for requirement in self.registry.requirements.values()
            for node_id in requirement.get("source_node_ids", [])
        }
        globally_excluded = {
            node_id
            for rows in self.discovery_candidate_exclusions.values()
            for node_id in rows
        }
        domains_by_node: dict[str, list[str]] = {}
        for domain in COVERAGE_DOMAINS:
            for node_id in self.graph_deterministic_node_ids[domain]:
                domains_by_node.setdefault(node_id, []).append(domain)

        unresolved = []
        for node_id, domains in domains_by_node.items():
            if node_id in globally_registered or node_id in globally_excluded:
                continue
            node = self.retrieved_nodes.get(node_id, {})
            if (_canonical_modality(node.get("modality")) is None or
                    _project_scope_exclusion(node) is not None):
                continue
            is_high = any(
                node_id in self.graph_high_confidence_node_ids[domain]
                for domain in domains
            )
            unresolved.append({
                "source_node_id": node_id,
                "domain": domains[0],
                **({"also_domains": domains[1:]} if len(domains) > 1 else {}),
                "priority": "high" if is_high else "review",
                "modality": _canonical_modality(node.get("modality")),
                "locator": node.get("source_locator"),
                "subject": node.get("subject"),
                "relation": node.get("relation"),
                "threshold": node.get("threshold"),
                "conditions": node.get("applicability_conditions", []),
            })
        domain_order = {domain: index for index, domain in enumerate(COVERAGE_DOMAINS)}
        unresolved.sort(key=lambda row: (
            0 if row["priority"] == "high" else 1,
            domain_order[row["domain"]],
            str(row.get("locator") or ""),
            row["source_node_id"],
        ))

        newly_presented = [
            row for row in unresolved
            if row["source_node_id"] not in self.stage2_audited_node_ids
        ]
        self.stage2_audited_node_ids.update(
            row["source_node_id"] for row in newly_presented
        )
        self.stage2_candidate_audit_calls += 1
        self.stage2_audit_revision = self.stage2_decision_revision
        self.stage2_verification_unresolved = deepcopy(unresolved)
        resolved_node_ids = {
            node_id
            for requirement in self.registry.requirements.values()
            for node_id in requirement.get("source_node_ids", [])
        } | {
            node_id
            for rows in self.discovery_candidate_exclusions.values()
            for node_id in rows
        }
        pending_decisions = sorted(self.stage2_audited_node_ids - resolved_node_ids)
        return {
            "decision_revision": self.stage2_decision_revision,
            "unresolved_candidate_count": len(unresolved),
            "new_candidate_count": len(newly_presented),
            **({"previously_presented_unresolved_count": len(unresolved)}
               if not newly_presented else {}),
            "unresolved_candidates": newly_presented,
            "pending_structured_decision_count": len(pending_decisions),
            **({"pending_structured_decision_source_node_ids": pending_decisions}
               if not newly_presented else {}),
            "verification_questions": [
                "Is its activation antecedent established by the layout or scene facts?",
                "Could it fail while every registered predicate passes?",
                "Is it identical to a registered predicate in modality, subject, conditions, relation, and threshold?",
            ],
            "next_action": (
                "Review each new candidate; retain applicable independent predicates or exclude. "
                "Use submit_stage2_candidate_decision_batch for every pending candidate. Re-run this audit after the "
                "final batch; sealing is allowed when both new_candidate_count and pending_structured_decision_count are zero."
            ),
        }

    def _program_activation_basis(self, node_id: str) -> dict:
        fact_keys: set[str] = set()
        evidence_ids: set[str] = set()
        for row in self.graph_candidate_provenance.get(node_id, []):
            if row.get("type") == "selected_ta":
                evidence_ids.update(
                    item for item in row.get("evidence_source_node_ids", [])
                    if item in self.retrieved_nodes
                )
            for trigger in row.get("triggers", []):
                key = trigger.get("fact_key")
                if (trigger.get("kind") == "scene_fact" and key and
                        self.scene_view.get("scene_facts", {}).get(key) is True):
                    fact_keys.add(key)
        if fact_keys and evidence_ids:
            basis_type = "combined"
        elif fact_keys:
            basis_type = "scene_fact"
        elif evidence_ids:
            basis_type = "selected_ta"
        else:
            basis_type = "unconditional"
        return {
            "type": basis_type,
            "fact_keys": sorted(fact_keys),
            "evidence_source_node_ids": sorted(evidence_ids),
            "explanation": (
                "Program-bound activation basis from deterministic Knowledge Graph provenance "
                "and frozen scene facts."
            ),
        }

    def _submit_stage2_candidate_decision_batch(self, arguments: dict) -> dict:
        accepted, rejected = [], []
        registered_source_ids = {
            node_id
            for requirement in self.registry.requirements.values()
            for node_id in requirement.get("source_node_ids", [])
        }
        excluded_source_ids = {
            node_id
            for rows in self.discovery_candidate_exclusions.values()
            for node_id in rows
        }

        for item in arguments["decisions"]:
            decision = deepcopy(item)
            node_id = decision.get("source_node_id")
            try:
                if node_id not in self.stage2_audited_node_ids:
                    raise RegistryError(
                        f"{node_id}: candidate was not presented by the Stage-2 coverage audit"
                    )
                if node_id in registered_source_ids or node_id in excluded_source_ids:
                    raise RegistryError(f"{node_id}: candidate already has a final disposition")
                node = self.retrieved_nodes.get(node_id)
                if node is None:
                    raise RegistryError(f"{node_id}: retrieved canonical node is unavailable")
                domains = [
                    domain for domain in COVERAGE_DOMAINS
                    if node_id in self.graph_deterministic_node_ids[domain]
                ]
                if not domains:
                    raise RegistryError(f"{node_id}: candidate is not deterministic KG output")
                domain = domains[0]
                if not str(decision.get("reason") or "").strip():
                    raise RegistryError(f"{node_id}: structured decision requires a reason")

                action = decision["action"]
                basis = decision["decision_basis"]
                activation = decision["activation_status"]
                independent = decision["independently_violable"]
                duplicate_of = decision["duplicate_of_source_node_id"]
                if action == "retain":
                    if not (basis == "activated_independent" and activation == "established" and
                            independent is True and duplicate_of is None):
                        raise RegistryError(
                            f"{node_id}: retain requires established activation, independent violation, "
                            "no duplicate, and activated_independent basis"
                        )
                    modality = _canonical_modality(node.get("modality"))
                    if modality is None:
                        raise RegistryError(f"{node_id}: candidate is not Standard or Guidance")
                    locator, span = node.get("source_locator"), node.get("source_span")
                    if node.get("node_type") == "figure_component":
                        normative_basis = node.get("normative_basis")
                        if not normative_basis:
                            raise RegistryError(
                                f"{node_id}: figure candidate lacks a normative basis"
                            )
                        locator = (
                            f"{locator}; Guidance basis {normative_basis['source_unit_code']} "
                            f"paragraph {normative_basis['paragraph']}"
                        )
                    requirement = {
                        "candidate_label": (
                            f"{node.get('source_unit_code')} {node.get('paragraph')}: "
                            f"{str(node.get('subject') or 'field predicate')[:120]}"
                        ),
                        "subject": node.get("subject") or "field predicate",
                        "modality": modality,
                        "relation": node.get("relation") or "must_be_checked",
                        "threshold": node.get("threshold") or node.get("source_span"),
                        "applicability_conditions": deepcopy(
                            node.get("applicability_conditions", [])
                        ),
                        "required_inputs": deepcopy(node.get("required_inputs", [])),
                        "source_node_ids": [node_id],
                        "source_locator": locator,
                        "source_span": span,
                        "model_extracted_source_span": span,
                        "activation_basis": self._program_activation_basis(node_id),
                        "measurement_spec": deepcopy(decision["measurement_spec"]),
                    }
                    result = self.registry.submit_requirement_batch(domain, [requirement])
                    registered_key = result["accepted_requirement_keys"][0]
                    registered_source_ids.add(node_id)
                    stored = {
                        **decision, "domain": domain,
                        "registered_requirement_key": registered_key,
                    }
                else:
                    if basis == "activated_independent":
                        raise RegistryError(
                            f"{node_id}: activated_independent decisions must be retained"
                        )
                    if basis == "activation_false" and activation != "false":
                        raise RegistryError(f"{node_id}: activation_false basis requires false status")
                    if basis == "activation_unknown" and activation != "unknown":
                        raise RegistryError(f"{node_id}: activation_unknown basis requires unknown status")
                    if basis == "duplicate" and not duplicate_of:
                        raise RegistryError(f"{node_id}: duplicate basis requires duplicate_of_source_node_id")
                    if basis == "not_independent" and independent is not False:
                        raise RegistryError(f"{node_id}: not_independent basis requires false")
                    reason_code = {
                        "activation_false": "activation_predicate_not_established",
                        "activation_unknown": "activation_predicate_not_established",
                        "duplicate": "duplicate_same_compliance_predicate",
                        "not_independent": "not_a_field_inspection_predicate",
                        "not_field_inspectable": "not_a_field_inspection_predicate",
                    }[basis]
                    self.discovery_candidate_exclusions[domain][node_id] = {
                        "source_node_id": node_id,
                        "reason_code": reason_code,
                        "reason": decision["reason"].strip(),
                    }
                    excluded_source_ids.add(node_id)
                    stored = {**decision, "domain": domain,
                              "registered_requirement_key": None}
                self.stage2_candidate_decisions[node_id] = deepcopy(stored)
                accepted.append(stored)
            except (RegistryError, KeyError, TypeError) as exc:
                rejected.append({"source_node_id": node_id, "failure_reason": str(exc)})

        if not accepted:
            raise RegistryError(
                "structured decision batch rejected: " +
                "; ".join(
                    f"{row['source_node_id']}: {row['failure_reason']}" for row in rejected
                )
            )
        self.stage2_decision_revision += 1
        result = {
            "accepted_decisions": accepted,
            "rejected_decisions": rejected,
            "structured_decision_count": len(self.stage2_candidate_decisions),
        }
        if rejected:
            result["status"] = "partial_success"
            result["repair_instruction"] = (
                "Accepted decisions are durable. Repair only rejected_decisions."
            )
        return result

    def _discovery_candidate_disposition_gaps(self,
                                              deterministic_only: bool = False) -> list[dict]:
        missing = []
        globally_registered = {
            node_id
            for requirement in self.registry.requirements.values()
            for node_id in requirement.get("source_node_ids", [])
        }
        globally_excluded = {
            node_id for rows in self.discovery_candidate_exclusions.values()
            for node_id in rows
        }
        for domain, coverage in self.discovery_coverage.items():
            candidates = (
                set(self.graph_high_confidence_node_ids[domain])
                if deterministic_only else
                set(coverage.get("source_node_ids", []))
            )
            for node_id in sorted(candidates - globally_registered - globally_excluded):
                node = self.retrieved_nodes.get(node_id, {})
                missing.append({
                    "domain": domain,
                    "source_node_id": node_id,
                    "source_locator": node.get("source_locator"),
                    "subject": node.get("subject"),
                })
        return missing

    def _validate_discovery_candidate_dispositions(self,
                                                   deterministic_only: bool = False) -> None:
        missing = self._discovery_candidate_disposition_gaps(deterministic_only)
        if missing:
            raise RegistryError(
                "discovery candidates lack an explicit Stage-2 disposition; register each activated "
                "predicate or exclude the source candidate with a permitted reason: " +
                json.dumps(missing, ensure_ascii=False, separators=(",", ":"))
            )
    def _resolved_thresholds(self, requirement: dict) -> list[dict]:
        facts = self.scene_view.get("scene_facts", {})
        resolved = []
        for rule in requirement["measurement_spec"]["thresholds"]:
            value = rule.get("value")
            parameter = rule.get("formula_parameter")
            multiplier = rule.get("multiplier")
            if value is None:
                if not parameter or multiplier is None or facts.get(parameter) is None:
                    raise RegistryError(f"registered threshold formula input is unavailable: {parameter}")
                value = float(facts[parameter]) * float(multiplier)
            resolved.append({**deepcopy(rule), "value": float(value)})
        return resolved

    @staticmethod
    def _stage4_id(prefix: str, payload: Any) -> str:
        material = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":")).encode()
        return f"{prefix}_{hashlib.sha256(material).hexdigest()[:20]}"

    @staticmethod
    def _requirement_text(requirement: dict) -> str:
        return " ".join(str(requirement.get(field, "")) for field in (
            "candidate_label", "subject", "relation", "threshold", "required_inputs",
        )).casefold()

    def _stage4_representatives(self, reviewed_class: str) -> list[dict]:
        ids = self._representative_observation_ids(reviewed_class)
        return sorted(
            (self.scene.observations[value] for value in ids),
            key=lambda row: (row.get("frame", 0), row.get("camera", ""), row["observation_id"]),
        )

    def _measurement_target_inputs(self, requirement: dict, tool_name: str) -> list[str]:
        availability = self.registry.data_availability[requirement["discovered_requirement_key"]]
        targets = []
        for input_name in availability.get("missing_inputs", []):
            if tool_name in acquisition_tools_for_input(input_name):
                targets.append(input_name)
                continue
            text = input_name.casefold().replace("-", " ")
            if tool_name == "audit_channelizer_spacing" and (
                "taper or tangent" in text or "device function" in text
            ):
                targets.append(input_name)
        return targets

    def _compose_stage4_plan(self) -> dict:
        if self.registry.stage4_plan is not None:
            return deepcopy(self.registry.stage4_plan)
        self.registry._require_phase("measurement")
        requirements = list(self.registry.requirements.values())
        requirements_by_key = {
            row["discovered_requirement_key"]: row for row in requirements
        }
        all_text = " ".join(self._requirement_text(row) for row in requirements)
        visual_jobs: list[dict] = []

        def relevant_keys(terms: tuple[str, ...]) -> list[str]:
            return sorted(
                key for key, row in requirements_by_key.items()
                if any(term in self._requirement_text(row) for term in terms)
            )

        def add_observation_jobs(role: str, observations: list[dict], keys: list[str]) -> None:
            for index in range(0, len(observations), 12):
                batch = observations[index:index + 12]
                observation_ids = [row["observation_id"] for row in batch]
                payload = {"role": role, "observation_ids": observation_ids}
                visual_jobs.append({
                    "visual_job_id": self._stage4_id("visual_job", payload),
                    "job_type": "observation_batch",
                    "role": role,
                    "observation_ids": observation_ids,
                    "reviewed_classes": sorted({row.get("reviewed_class") for row in batch}),
                    "relevant_requirement_keys": keys,
                })

        # Route visual work by the registered coverage domain and required
        # input modality.  Requirement wording is evidence, not a dispatch
        # API, so a figure-derived or unusually phrased predicate must receive
        # the same inspection coverage as any other predicate in its domain.
        visual_tool_names = {"inspect_temporal_images", "inspect_observation_images"}
        visual_keys = {
            key for key, requirement in requirements_by_key.items()
            if any(
                acquisition_tools_for_input(input_name) & visual_tool_names
                for input_name in self.registry.data_availability[key].get("missing_inputs", [])
            )
        }
        sign_keys = sorted(
            key for key in visual_keys
            if requirements_by_key[key].get("region") == "advance_warning_sign_system"
        )
        if sign_keys:
            add_observation_jobs(
                "traffic_sign_representatives",
                self._stage4_representatives("traffic_sign"), sign_keys,
            )
        arrow_keys = sorted(
            key for key in visual_keys
            if requirements_by_key[key].get("region") == "conditional_active_devices"
        )
        channelizer_keys = sorted(
            key for key in visual_keys
            if requirements_by_key[key].get("region") in {
                "lane_closure_layout", "channelization_system",
                "transition_and_taper_geometry", "conditional_termination_area",
            }
        )
        if arrow_keys or channelizer_keys:
            samples = self._stage4_representatives("arrow_board") if arrow_keys else []
            for reviewed_class in (
                "channelizing_device", "traffic_cone", "traffic_drum", "barricade",
            ):
                rows = self._stage4_representatives(reviewed_class)
                if rows:
                    samples.append(max(
                        rows,
                        key=lambda row: max(0.0, row["bbox"][2] - row["bbox"][0]) *
                        max(0.0, row["bbox"][3] - row["bbox"][1]),
                    ))
            add_observation_jobs(
                "device_representatives", samples,
                sorted(set(arrow_keys) | set(channelizer_keys)),
            )

        temporal_keys = sorted(
            key for key in visual_keys
            if requirements_by_key[key].get("region") in {
                "lane_closure_layout", "advance_warning_sign_system",
                "transition_and_taper_geometry", "conditional_active_devices",
                "conditional_termination_area",
            }
        )
        front_total = len(self.scene.rows_by_channel.get("CAM_FRONT", []))
        if temporal_keys and front_total:
            count = min(8, front_total)
            stride = max(1, (front_total - 1) // max(1, count - 1))
            payload = {"channel": "CAM_FRONT", "start_cursor": 0,
                       "count": count, "stride": stride,
                       "total_frames": front_total}
            visual_jobs.append({
                "visual_job_id": self._stage4_id("visual_job", payload),
                "job_type": "temporal_batch",
                "role": "route_temporal_coverage",
                **payload,
                "relevant_requirement_keys": temporal_keys,
            })

        measurement_jobs = []
        blocked_attempts = []
        for requirement in requirements:
            key = requirement["discovered_requirement_key"]
            availability = self.registry.data_availability[key]
            spec = requirement.get("measurement_spec") or {}
            registered_tool = spec.get("tool") if spec.get("required") else None
            if registered_tool:
                targets = self._measurement_target_inputs(requirement, registered_tool)
                job_payload = {"key": key, "tool": registered_tool, "targets": targets}
                measurement_jobs.append({
                    "measurement_job_id": self._stage4_id("measurement_job", job_payload),
                    "discovered_requirement_key": key,
                    "candidate_label": requirement.get("candidate_label"),
                    "tool": registered_tool,
                    "target_inputs": targets,
                    "quantity": spec.get("quantity"),
                    "thresholds": deepcopy(spec.get("thresholds", [])),
                })
            for planned_tool in availability.get("planned_tools", []):
                if planned_tool not in NORMATIVE_MEASUREMENT_TOOLS or planned_tool == registered_tool:
                    continue
                targets = [
                    input_name for input_name in availability.get("missing_inputs", [])
                    if planned_tool in acquisition_tools_for_input(input_name)
                ]
                if not targets:
                    continue
                attempt_payload = {"key": key, "tool": planned_tool, "targets": targets,
                                   "reason": "not_authorized_by_frozen_measurement_spec"}
                attempt = {
                    "attempt_id": self._stage4_id("attempt", attempt_payload),
                    "measurement_job_id": None,
                    "discovered_requirement_key": key,
                    "tool": planned_tool,
                    "target_inputs": targets,
                    "status": "blocked_before_call",
                    "failure_reason": "The frozen requirement measurement_spec does not authorize this planned tool.",
                    "source_ids": [],
                }
                blocked_attempts.append(attempt)
                stored_attempt = self.registry.record_acquisition_attempt(attempt)
                self.registry.record_evidence_batch([{
                    "discovered_requirement_key": key,
                    "evidence_kind": "acquisition_failure",
                    "source_ids": [stored_attempt["attempt_id"]],
                    "acquired_inputs": [],
                    "unresolved_inputs": targets,
                    "finding": stored_attempt["failure_reason"],
                    "limitations": "The program did not expose an unregistered measurement tool.",
                    "tools_used": [],
                    "acquisition_attempt_id": stored_attempt["attempt_id"],
                }])

        measurement_owned: dict[str, set[str]] = {key: set() for key in requirements_by_key}
        for job in measurement_jobs:
            measurement_owned[job["discovered_requirement_key"]].update(job["target_inputs"])
        blocked_owned: dict[str, set[str]] = {key: set() for key in requirements_by_key}
        for attempt in blocked_attempts:
            blocked_owned[attempt["discovered_requirement_key"]].update(attempt["target_inputs"])
        visual_owned: dict[str, set[str]] = {key: set() for key in requirements_by_key}
        for key in requirements_by_key:
            availability = self.registry.data_availability[key]
            for input_name in availability.get("missing_inputs", []):
                tools = acquisition_tools_for_input(input_name)
                if tools & {"inspect_observation_images", "inspect_temporal_images"}:
                    if input_name not in measurement_owned[key] and input_name not in blocked_owned[key]:
                        visual_owned[key].add(input_name)

        # Missing inputs with no authorized Stage 4 route are deterministically
        # unresolved; the model cannot repair them by inventing a tool call.
        for key in requirements_by_key:
            availability = self.registry.data_availability[key]
            owned = measurement_owned[key] | blocked_owned[key] | visual_owned[key]
            unroutable = [
                value for value in availability.get("missing_inputs", []) if value not in owned
            ]
            if not unroutable:
                continue
            attempt_payload = {"key": key, "tool": None, "targets": unroutable,
                               "reason": "no_authorized_stage4_acquisition_route"}
            attempt = {
                "attempt_id": self._stage4_id("attempt", attempt_payload),
                "measurement_job_id": None,
                "discovered_requirement_key": key,
                "tool": None,
                "target_inputs": unroutable,
                "status": "blocked_before_call",
                "failure_reason": "No authorized Stage 4 tool can acquire this frozen required input.",
                "source_ids": [],
            }
            blocked_attempts.append(attempt)
            stored_attempt = self.registry.record_acquisition_attempt(attempt)
            self.registry.record_evidence_batch([{
                "discovered_requirement_key": key,
                "evidence_kind": "acquisition_failure",
                "source_ids": [stored_attempt["attempt_id"]],
                "acquired_inputs": [],
                "unresolved_inputs": unroutable,
                "finding": stored_attempt["failure_reason"],
                "limitations": "The frozen Stage 3 plan and registered tools provide no acquisition route.",
                "tools_used": [],
                "acquisition_attempt_id": stored_attempt["attempt_id"],
            }])
            blocked_owned[key].update(unroutable)

        for job in visual_jobs:
            job["target_inputs_by_requirement"] = {
                key: sorted(visual_owned[key])
                for key in job["relevant_requirement_keys"] if visual_owned[key]
            }
            job["relevant_requirement_keys"] = sorted(
                job["target_inputs_by_requirement"]
            )

        # Stage 3 already froze the direct-input provenance. Materialize it once
        # so the model only has to classify newly inspected or measured inputs.
        already_accounted = {
            key: {
                value for row in self.registry.evidence_records.values()
                if row["discovered_requirement_key"] == key
                for value in row.get("acquired_inputs", []) + row.get("unresolved_inputs", [])
            }
            for key in requirements_by_key
        }
        direct_records = []
        for key, requirement in requirements_by_key.items():
            availability = self.registry.data_availability[key]
            direct_inputs = [
                value for value in availability.get("available_inputs", [])
                if value not in already_accounted[key]
            ]
            if not direct_inputs:
                continue
            sources = []
            for source_id in availability.get("basis_evidence_ids", []):
                if source_id.startswith("manifest:"):
                    source_id = "scene_manifest:" + source_id.split(":", 1)[1]
                sources.append(source_id)
            direct_records.append({
                "discovered_requirement_key": key,
                "evidence_kind": "direct_fact",
                "source_ids": sources or ["scene_manifest:data_availability_record"],
                "acquired_inputs": direct_inputs,
                "unresolved_inputs": [],
                "finding": "Frozen direct inputs: " + "; ".join(direct_inputs) + ".",
                "limitations": "Only the listed direct inputs are established; remaining inputs require Stage 4 acquisition.",
                "tools_used": [],
            })
        if direct_records:
            self.registry.record_evidence_batch(direct_records)

        # User/domain-reviewer confirmations in the sole materialized scene are
        # direct Stage 4 evidence. Bind them by predicate semantics and coverage
        # domain, never by a benchmark label such as CH-02. A confirmed instance
        # is enough to test a universal device-condition or serviceability rule,
        # while the representative image jobs still provide system-wide context.
        confirmed_condition_rows = self.scene.confirmed_device_condition_findings
        if confirmed_condition_rows:
            condition_records = []
            condition_terms = (
                "condition", "serviceab", "maintain", "maintenance", "replace",
                "clean", "visible", "visibility", "retroreflect",
            )
            for key, requirement in requirements_by_key.items():
                if requirement.get("region") != "channelization_system":
                    continue
                predicate_text = self._requirement_text(requirement)
                if not any(term in predicate_text for term in condition_terms):
                    continue
                visual_inputs = sorted({
                    input_name
                    for input_name in requirement.get("required_inputs", [])
                    if acquisition_tools_for_input(input_name) & {
                        "inspect_temporal_images", "inspect_observation_images"
                    }
                })
                if not visual_inputs:
                    continue
                source_ids = sorted({
                    row.get("observation_id") for row in confirmed_condition_rows
                    if row.get("observation_id") in self.scene.observations
                })
                if not source_ids:
                    continue
                findings = "; ".join(
                    f"{row.get('element_id')}: {row.get('condition')}"
                    for row in confirmed_condition_rows
                    if row.get("observation_id") in source_ids
                )
                condition_records.append({
                    "discovered_requirement_key": key,
                    "evidence_kind": "direct_fact",
                    "source_ids": source_ids,
                    "acquired_inputs": visual_inputs,
                    "unresolved_inputs": [],
                    "finding": "User/domain-reviewer confirmed device-condition findings: " + findings + ".",
                    "limitations": (
                        "These confirmations establish the listed defective devices and do not by "
                        "themselves establish the condition of every other deployed device."
                    ),
                    "tools_used": [],
                })
            for index in range(0, len(condition_records), self.registry.max_batch_size):
                self.registry.record_evidence_batch(
                    condition_records[index:index + self.registry.max_batch_size]
                )

        plan_material = {
            "requirement_keys": sorted(requirements_by_key),
            "visual_jobs": visual_jobs,
            "measurement_jobs": measurement_jobs,
            "blocked_attempts": blocked_attempts,
        }
        plan = {
            "plan_id": self._stage4_id("stage4_plan", plan_material),
            **plan_material,
            "coverage_policy": {
                "all_representative_traffic_signs": bool(sign_keys),
                "all_arrow_boards": bool(arrow_keys),
                "one_per_present_channelizer_class": bool(channelizer_keys),
                "cam_front_minimum_frames": 8 if temporal_keys else 0,
                "cam_front_minimum_span_ratio": 0.70 if temporal_keys else 0.0,
            },
        }
        return self.registry.set_stage4_plan(plan)

    def _stage4_plan_view(self) -> dict:
        plan = self._compose_stage4_plan()
        completed_jobs = {
            row.get("visual_job_id") for row in self.registry.inspection_bundles.values()
        }
        attempts_by_job = {
            row.get("measurement_job_id"): row
            for row in self.registry.acquisition_attempts.values()
            if row.get("measurement_job_id")
        }
        return {
            **deepcopy(plan),
            "visual_jobs": [
                {**deepcopy(row), "status": (
                    "completed" if row["visual_job_id"] in completed_jobs else "pending"
                )}
                for row in plan.get("visual_jobs", [])
            ],
            "measurement_jobs": [
                {**deepcopy(row), "status": (
                    attempts_by_job.get(row["measurement_job_id"], {}).get("status", "pending")
                )}
                for row in plan.get("measurement_jobs", [])
            ],
        }

    def _inspect_stage4_visual_job(self, visual_job_id: str) -> dict:
        plan = self._compose_stage4_plan()
        job = next((row for row in plan["visual_jobs"]
                    if row["visual_job_id"] == visual_job_id), None)
        if job is None:
            raise RegistryError("unknown Stage 4 visual job")
        existing = next((row for row in self.registry.inspection_bundles.values()
                         if row.get("visual_job_id") == visual_job_id), None)
        if existing is not None:
            return {"status": "acquired", "cache_hit": True, **deepcopy(existing)}
        if job["job_type"] == "observation_batch":
            result = self.scene.inspect_observation_images(job["observation_ids"])
            underlying_tool = "inspect_observation_images"
            source_ids = [row["observation_id"] for row in result.get("observations", [])]
            reviewed_classes = sorted({
                row.get("reviewed_class") for row in result.get("observations", [])
            })
            compact_items = [{key: row.get(key) for key in (
                "observation_id", "frame", "camera", "reviewed_class", "bbox",
                "refined_element_id", "raw_device_id",
            )} for row in result.get("observations", [])]
        else:
            result = self.scene.inspect_temporal_images(
                job["channel"], job["start_cursor"], job["count"], job["stride"]
            )
            underlying_tool = "inspect_temporal_images"
            source_ids = [row["image_id"] for row in result.get("images", [])]
            reviewed_classes = []
            compact_items = [{key: row.get(key) for key in (
                "image_id", "timestamp_us",
            )} for row in result.get("images", [])]
        self.registry.record_tool_call(underlying_tool, result)
        if result.get("status") == "failure":
            raise RegistryError(result.get("failure_reason", "visual inspection failed"))
        bundle_payload = {"visual_job_id": visual_job_id, "source_ids": source_ids}
        bundle = self.registry.record_inspection_bundle({
            "inspection_bundle_id": self._stage4_id("visual_bundle", bundle_payload),
            "visual_job_id": visual_job_id,
            "role": job["role"],
            "job_type": job["job_type"],
            "source_ids": source_ids,
            "source_metadata": {
                (row.get("observation_id") or row.get("image_id")): {
                    key: value for key, value in row.items()
                    if key in {"reviewed_class", "timestamp_us"}
                }
                for row in compact_items
            },
            "reviewed_classes": reviewed_classes,
            "relevant_requirement_keys": job["relevant_requirement_keys"],
            "underlying_tool": underlying_tool,
            "item_count": len(compact_items),
        })
        return {
            "status": "acquired",
            **bundle,
            "items": compact_items,
            "_image_paths": result.get("_image_paths", []),
        }

    def _record_visual_job_note(self, arguments: dict) -> dict:
        self._compose_stage4_plan()
        bundle = next((
            row for row in self.registry.inspection_bundles.values()
            if row.get("visual_job_id") == arguments["visual_job_id"]
        ), None)
        if bundle is None:
            raise RegistryError("visual job has not been inspected")
        return self.registry.record_inspection_bundle_note(
            bundle["inspection_bundle_id"], arguments["finding"], arguments["limitations"]
        )

    @staticmethod
    def _measurement_is_usable(measurement: dict) -> bool:
        if measurement.get("status") == "failure" or not measurement.get("measurement_id"):
            return False
        if measurement.get("measurement_type") == "channelizer_spacing_series":
            return measurement.get("sequence_inference_valid") is True
        # A longitudinal value can be numerically computable while its selected
        # endpoint is far outside the traveled road corridor.  Preserve that raw
        # measurement for audit, but do not let it satisfy a required input.
        if "large_trajectory_lateral_residual" in measurement.get("quality_flags", []):
            return False
        return bool(
            measurement.get("endpoint_semantics_valid") is True
            and measurement.get("geometry_direction_valid") is True
            and measurement.get("threshold_assessment", {}).get("status") != "geometry_not_eligible"
        )

    def _run_registered_measurement(self, arguments: dict) -> dict:
        plan = self._compose_stage4_plan()
        job_id = arguments["measurement_job_id"]
        job = next((row for row in plan["measurement_jobs"]
                    if row["measurement_job_id"] == job_id), None)
        if job is None:
            raise RegistryError("unknown registered measurement job")
        previous = next((row for row in self.registry.acquisition_attempts.values()
                         if row.get("measurement_job_id") == job_id), None)
        if previous is not None:
            measurement = self.scene.measurements.get(previous.get("measurement_id"), {})
            return {"status": previous["status"], "cache_hit": True,
                    "attempt_id": previous["attempt_id"], **deepcopy(measurement)}
        tool_name = job["tool"]
        call_args: dict[str, Any] = {
            "discovered_requirement_key": job["discovered_requirement_key"],
        }
        inspected_observations = {
            source_id for bundle in self.registry.inspection_bundles.values()
            for source_id in bundle.get("source_ids", [])
            if source_id in self.scene.observations
        }
        if tool_name in {
            "measure_longitudinal_distance", "measure_taper_length", "measure_buffer_length",
            "measure_sign_spacing", "measure_downstream_taper",
        }:
            start = arguments.get("start_observation_id")
            end = arguments.get("end_observation_id")
            if not start or not end:
                raise RegistryError("registered endpoint measurement requires start and end observations")
            if start not in inspected_observations or end not in inspected_observations:
                raise RegistryError("measurement endpoints must come from completed inspection bundles")
            call_args.update({"start_observation_id": start, "end_observation_id": end})
            if tool_name == "measure_longitudinal_distance":
                call_args.update({"measurement_type": job.get("quantity") or "longitudinal_distance",
                                  "start_role": "start", "end_role": "end"})
        elif tool_name == "measure_device_spacing":
            ids = arguments.get("observation_ids", [])
            if len(ids) < 2 or not set(ids).issubset(inspected_observations):
                raise RegistryError("device spacing requires at least two inspected observations")
            call_args["observation_ids"] = ids
        elif tool_name == "estimate_available_width":
            ids = arguments.get("observation_ids", [])
            if len(ids) != 2 or not set(ids).issubset(inspected_observations):
                raise RegistryError("available width requires two inspected boundary observations")
            call_args.update({"left_observation_id": ids[0], "right_observation_id": ids[1]})
        # A frozen requirement can legitimately depend on a field parameter
        # that the current scene does not provide (for example, a formula
        # requiring a measured roadway width).  That is an acquisition
        # outcome, not a reason to leave the Stage 4 job pending forever.
        # Preserve the failure as a durable attempt so readiness can advance
        # and Stage 5 can report the requirement as not assessed.
        try:
            measurement = self._measurement_call(tool_name, call_args)
        except RegistryError as exc:
            measurement = {
                "status": "failure",
                "measurement_id": None,
                "failure_reason": str(exc),
                "quality_flags": ["registered_measurement_unavailable"],
            }
        self.registry.record_tool_call(
            tool_name, measurement, job["discovered_requirement_key"]
        )
        status = (
            "usable" if self._measurement_is_usable(measurement)
            else "failed" if measurement.get("status") == "failure"
            else "quality_rejected"
        )
        attempt_payload = {
            "measurement_job_id": job_id,
            "arguments": {key: value for key, value in call_args.items()
                          if key != "discovered_requirement_key"},
        }
        attempt = self.registry.record_acquisition_attempt({
            "attempt_id": self._stage4_id("attempt", attempt_payload),
            "measurement_job_id": job_id,
            "discovered_requirement_key": job["discovered_requirement_key"],
            "tool": tool_name,
            "target_inputs": job["target_inputs"],
            "status": status,
            "failure_reason": measurement.get("failure_reason") or (
                None if status == "usable" else "measurement failed the registered quality gate"
            ),
            "measurement_id": measurement.get("measurement_id"),
            "source_ids": [measurement["measurement_id"]] if measurement.get("measurement_id") else [],
        })
        compact = {key: measurement.get(key) for key in (
            "status", "measurement_id", "measurement_type", "value", "unit",
            "confidence_interval", "thresholds_applied", "threshold_assessment",
            "deficiency_supported", "sequence_inference_valid", "endpoint_semantics_valid",
            "geometry_direction_valid", "gaps_evaluated", "clear_exceedance_gap_count",
            "violation_run_count", "quality_flags", "failure_reason",
        )}
        return {**compact, "status": "acquired", "measurement_quality_status": status,
                "attempt_id": attempt["attempt_id"], "measurement_job_id": job_id}

    def _compose_visual_evidence(self, arguments: dict) -> dict:
        self._compose_stage4_plan()
        key = arguments["discovered_requirement_key"]
        bundles = [
            bundle for bundle in self.registry.inspection_bundles.values()
            if key in bundle.get("relevant_requirement_keys", [])
        ]
        if not bundles:
            raise RegistryError(f"no completed inspection bundle is routed to requirement {key}")
        source_ids = sorted({source for row in bundles for source in row["source_ids"]})
        tools_used = sorted({row["underlying_tool"] for row in bundles})
        plan = self.registry.stage4_plan or {}
        jobs_by_id = {row["visual_job_id"]: row for row in plan.get("visual_jobs", [])}
        allowed_inputs = {
            value for bundle in bundles
            for value in jobs_by_id.get(bundle["visual_job_id"], {}).get(
                "target_inputs_by_requirement", {}
            ).get(key, [])
        }
        submitted_inputs = set(arguments["acquired_inputs"])
        if not submitted_inputs.issubset(allowed_inputs):
            raise RegistryError(
                "visual finding may classify only program-routed visual inputs: " +
                json.dumps({"unexpected": sorted(submitted_inputs - allowed_inputs),
                            "allowed": sorted(allowed_inputs)}, ensure_ascii=False)
            )
        return {
            "discovered_requirement_key": key,
            "evidence_kind": "visual_observation",
            "source_ids": source_ids,
            "acquired_inputs": arguments["acquired_inputs"],
            "unresolved_inputs": sorted(allowed_inputs - submitted_inputs),
            "finding": arguments["finding"],
            "limitations": arguments["limitations"],
            "tools_used": tools_used,
            "inspection_bundle_ids": sorted(
                row["inspection_bundle_id"] for row in bundles
            ),
        }

    def _record_visual_finding(self, arguments: dict) -> dict:
        return self.registry.record_evidence_batch([
            self._compose_visual_evidence(arguments)
        ])

    def _record_visual_finding_batch(self, arguments: dict) -> dict:
        pending, existing_ids = [], []
        seen = set()
        for row in arguments["findings"]:
            evidence = self._compose_visual_evidence(row)
            signature = (
                evidence["discovered_requirement_key"],
                tuple(sorted(evidence["inspection_bundle_ids"])),
                tuple(sorted(evidence["acquired_inputs"])),
                tuple(sorted(evidence["unresolved_inputs"])),
            )
            if signature in seen:
                continue
            seen.add(signature)
            existing = next((
                value for value in self.registry.evidence_records.values()
                if value.get("evidence_kind") == "visual_observation"
                and value.get("discovered_requirement_key") == evidence["discovered_requirement_key"]
                and tuple(sorted(value.get("inspection_bundle_ids", []))) == signature[1]
                and tuple(sorted(value.get("acquired_inputs", []))) == signature[2]
                and tuple(sorted(value.get("unresolved_inputs", []))) == signature[3]
            ), None)
            if existing:
                existing_ids.append(existing["evidence_id"])
            else:
                pending.append(evidence)
        accepted = self.registry.record_evidence_batch(pending) if pending else {
            "accepted_evidence_ids": [],
            "evidence_record_count": len(self.registry.evidence_records),
        }
        return {**accepted, "existing_evidence_ids": existing_ids,
                "idempotent_reuse_count": len(existing_ids)}

    def _compose_measurement_evidence(self, arguments: dict) -> dict:
        plan = self._compose_stage4_plan()
        job_id = arguments["measurement_job_id"]
        job = next((row for row in plan["measurement_jobs"]
                    if row["measurement_job_id"] == job_id), None)
        if job is None:
            raise RegistryError("unknown registered measurement job")
        attempt = next((row for row in self.registry.acquisition_attempts.values()
                        if row.get("measurement_job_id") == job_id), None)
        if attempt is None:
            raise RegistryError("registered measurement job has not been attempted")
        usable = attempt["status"] == "usable"
        source_ids = attempt.get("source_ids") or [attempt["attempt_id"]]
        return {
            "discovered_requirement_key": job["discovered_requirement_key"],
            "evidence_kind": "measurement_context" if usable else "acquisition_failure",
            "source_ids": source_ids,
            "acquired_inputs": job["target_inputs"] if usable else [],
            "unresolved_inputs": [] if usable else job["target_inputs"],
            "finding": arguments["finding"],
            "limitations": arguments["limitations"],
            "tools_used": [job["tool"]],
            "acquisition_attempt_id": attempt["attempt_id"],
        }

    def _record_measurement_finding(self, arguments: dict) -> dict:
        return self.registry.record_evidence_batch([
            self._compose_measurement_evidence(arguments)
        ])

    def _record_measurement_finding_batch(self, arguments: dict) -> dict:
        pending, existing_ids = [], []
        seen_attempts = set()
        for row in arguments["findings"]:
            evidence = self._compose_measurement_evidence(row)
            attempt_id = evidence["acquisition_attempt_id"]
            if attempt_id in seen_attempts:
                continue
            seen_attempts.add(attempt_id)
            existing = next((
                value for value in self.registry.evidence_records.values()
                if value.get("acquisition_attempt_id") == attempt_id
            ), None)
            if existing:
                existing_ids.append(existing["evidence_id"])
            else:
                pending.append(evidence)
        accepted = self.registry.record_evidence_batch(pending) if pending else {
            "accepted_evidence_ids": [],
            "evidence_record_count": len(self.registry.evidence_records),
        }
        return {**accepted, "existing_evidence_ids": existing_ids,
                "idempotent_reuse_count": len(existing_ids)}

    def _record_acquisition_failure(self, arguments: dict) -> dict:
        self._compose_stage4_plan()
        attempt = self.registry.acquisition_attempts.get(arguments["attempt_id"])
        if attempt is None:
            raise RegistryError("unknown acquisition attempt")
        if attempt.get("status") == "usable":
            raise RegistryError("a usable acquisition attempt cannot be recorded as a failure")
        evidence = {
            "discovered_requirement_key": attempt["discovered_requirement_key"],
            "evidence_kind": "acquisition_failure",
            "source_ids": attempt.get("source_ids") or [attempt["attempt_id"]],
            "acquired_inputs": [],
            "unresolved_inputs": attempt["target_inputs"],
            "finding": arguments["reason"],
            "limitations": arguments["limitations"],
            "tools_used": ([attempt["tool"]]
                           if attempt.get("status") != "blocked_before_call" else []),
            "acquisition_attempt_id": attempt["attempt_id"],
        }
        return self.registry.record_evidence_batch([evidence])

    def _stage4_readiness(self) -> dict:
        plan = self._compose_stage4_plan()
        completed_visual = {
            row.get("visual_job_id") for row in self.registry.inspection_bundles.values()
        }
        missing_visual_jobs = [
            row["visual_job_id"] for row in plan["visual_jobs"]
            if row["visual_job_id"] not in completed_visual
        ]
        attempts_by_job = {
            row.get("measurement_job_id"): row
            for row in self.registry.acquisition_attempts.values()
            if row.get("measurement_job_id")
        }
        missing_measurement_attempts = [
            row["measurement_job_id"] for row in plan["measurement_jobs"]
            if row["measurement_job_id"] not in attempts_by_job
        ]
        evidence_by_key: dict[str, list[dict]] = {
            key: [] for key in self.registry.requirements
        }
        for evidence in self.registry.evidence_records.values():
            evidence_by_key[evidence["discovered_requirement_key"]].append(evidence)
        missing_evidence = []
        input_accounting_gaps = {}
        overlaps = {}
        for key, requirement in self.registry.requirements.items():
            rows = evidence_by_key[key]
            if not rows:
                missing_evidence.append(key)
            acquired = {value for row in rows for value in row.get("acquired_inputs", [])}
            unresolved = {value for row in rows for value in row.get("unresolved_inputs", [])}
            required = set(requirement["required_inputs"])
            if acquired | unresolved != required:
                input_accounting_gaps[key] = {
                    "missing": sorted(required - acquired - unresolved),
                    "unexpected": sorted((acquired | unresolved) - required),
                }
            if acquired & unresolved:
                overlaps[key] = sorted(acquired & unresolved)

        class_by_source = {
            key: value.get("reviewed_class") for key, value in self.scene.observations.items()
        }
        present_channelizer_classes = {
            reviewed_class for reviewed_class in (
                "channelizing_device", "traffic_cone", "traffic_drum", "barricade",
            ) if self._representative_observation_ids(reviewed_class)
        }
        provenance_gaps = []
        temporal_sources = {
            source for bundle in self.registry.inspection_bundles.values()
            if bundle.get("job_type") == "temporal_batch"
            for source in bundle.get("source_ids", [])
        }
        for key, requirement in self.registry.requirements.items():
            rows = evidence_by_key[key]
            sources = {source for row in rows for source in row.get("source_ids", [])}
            text = self._requirement_text(requirement)
            if "arrow board" in text or "arrow-board" in text:
                if not any(class_by_source.get(source) == "arrow_board" for source in sources):
                    provenance_gaps.append(f"{key}:missing_arrow_board_source")
            if any(term in text for term in ("warning sign", "sign legend", "road work sign")):
                if not any(class_by_source.get(source) == "traffic_sign" for source in sources):
                    provenance_gaps.append(f"{key}:missing_traffic_sign_source")
            if requirement.get("candidate_label") == "CH-02":
                bound_classes = {class_by_source.get(source) for source in sources}
                missing_classes = present_channelizer_classes - bound_classes
                if missing_classes:
                    provenance_gaps.append(
                        f"{key}:missing_channelizer_classes={','.join(sorted(missing_classes))}"
                    )
            temporal_inputs = {
                value for value in requirement.get("required_inputs", [])
                if any(term in value.casefold() for term in (
                    "transition", "taper", "work-space", "work space", "downstream",
                    "operation type", "traffic movement", "arrangement",
                ))
            }
            acquired_temporal = {
                value for row in rows if row.get("evidence_kind") == "visual_observation"
                for value in row.get("acquired_inputs", [])
                if value in temporal_inputs
            }
            if acquired_temporal and not (sources & temporal_sources):
                provenance_gaps.append(f"{key}:missing_temporal_bundle_source")

        blocked_attempt_ids = {
            row["attempt_id"] for row in self.registry.acquisition_attempts.values()
            if row.get("status") == "blocked_before_call"
        }
        cited_attempt_ids = {
            row.get("acquisition_attempt_id") for row in self.registry.evidence_records.values()
            if row.get("acquisition_attempt_id")
        }
        unrecorded_blocked_attempts = sorted(blocked_attempt_ids - cited_attempt_ids)
        measurement_attempt_ids = {
            row["attempt_id"] for row in attempts_by_job.values()
        }
        unrecorded_measurement_attempts = sorted(measurement_attempt_ids - cited_attempt_ids)
        ready = not any((
            missing_visual_jobs, missing_measurement_attempts, missing_evidence,
            input_accounting_gaps, overlaps, provenance_gaps,
            unrecorded_blocked_attempts, unrecorded_measurement_attempts,
        ))
        next_actions = []
        if missing_visual_jobs:
            next_actions.append({"tool": "inspect_stage4_visual_job",
                                 "visual_job_ids": missing_visual_jobs})
        if input_accounting_gaps or provenance_gaps:
            next_actions.append({
                "tool": "record_visual_finding_batch",
                "requirement_keys": sorted(set(input_accounting_gaps) | {
                    value.split(":", 1)[0] for value in provenance_gaps
                }),
            })
        if missing_measurement_attempts:
            next_actions.append({"tool": "run_registered_measurement",
                                 "measurement_job_ids": missing_measurement_attempts})
        if unrecorded_measurement_attempts:
            next_actions.append({"tool": "record_measurement_finding_batch",
                                 "attempt_ids": unrecorded_measurement_attempts})
        if ready:
            next_actions.append({"tool": "seal_measurements"})
        return {
            "ready": ready,
            "plan_id": plan["plan_id"],
            "visual_jobs_completed": len(plan["visual_jobs"]) - len(missing_visual_jobs),
            "visual_jobs_total": len(plan["visual_jobs"]),
            "missing_visual_jobs": missing_visual_jobs,
            "measurement_jobs_attempted": len(plan["measurement_jobs"]) - len(missing_measurement_attempts),
            "measurement_jobs_total": len(plan["measurement_jobs"]),
            "missing_measurement_attempts": missing_measurement_attempts,
            "requirements_without_evidence": missing_evidence,
            "input_accounting_gaps": input_accounting_gaps,
            "acquired_unresolved_overlaps": overlaps,
            "provenance_gaps": provenance_gaps,
            "unrecorded_blocked_attempts": unrecorded_blocked_attempts,
            "unrecorded_measurement_attempts": unrecorded_measurement_attempts,
            "next_actions": next_actions,
        }

    def _compose_stage5_plan(self) -> dict:
        if self.registry.phase not in {"inspection_conclusion", "result_submission"}:
            raise RegistryError("Stage 5 plan is available only after Stage 4 is sealed")
        if self.registry.stage5_plan is not None:
            return deepcopy(self.registry.stage5_plan)
        jobs = []
        for key, requirement in self.registry.requirements.items():
            evidence = [
                row for row in self.registry.evidence_records.values()
                if row.get("discovered_requirement_key") == key
            ]
            acquired = sorted({
                value for row in evidence for value in row.get("acquired_inputs", [])
            })
            unresolved = sorted({
                value for row in evidence for value in row.get("unresolved_inputs", [])
            })
            confirmed_deficiency = any(
                row.get("evidence_kind") == "direct_fact"
                and row.get("finding", "").startswith(
                    "User/domain-reviewer confirmed device-condition findings:"
                )
                for row in evidence
            )
            allowed_statuses = (
                ["not_assessed"] if unresolved else
                ["deficient"] if confirmed_deficiency else
                ["satisfied", "deficient"]
            )
            jobs.append({
                "discovered_requirement_key": key,
                "candidate_label": requirement.get("candidate_label"),
                "modality": requirement.get("modality"),
                "normative_class": (
                    "Mandatory" if requirement.get("modality") == "shall" else "Guidance"
                ),
                "subject": requirement.get("subject"),
                "relation": requirement.get("relation"),
                "threshold": requirement.get("threshold"),
                "applicability_conditions": requirement.get("applicability_conditions", []),
                "required_inputs": requirement.get("required_inputs", []),
                "acquired_inputs": acquired,
                "unresolved_inputs": unresolved,
                "allowed_inspection_statuses": allowed_statuses,
                "confirmed_deficiency_evidence": confirmed_deficiency,
                "source_locator": requirement.get("source_locator"),
                "evidence": [{key_name: row.get(key_name) for key_name in (
                    "evidence_id", "evidence_kind", "acquired_inputs", "unresolved_inputs",
                    "finding", "limitations", "source_ids",
                )} for row in evidence],
            })
        material = [{key: row.get(key) for key in (
            "discovered_requirement_key", "modality", "acquired_inputs", "unresolved_inputs",
        )} for row in jobs]
        plan = {
            "plan_id": self._stage4_id("stage5_plan", material),
            "conclusion_jobs": jobs,
            "decision_policy": {
                "unresolved_input_requires_not_assessed": True,
                "all_required_inputs_resolved_requires_definitive_decision": True,
                "false_or_indeterminate_applicability_requires_not_assessed": True,
                "mandatory_guidance_class_comes_from_registered_modality": True,
                "absence_is_not_a_deficiency_when_observation_is_unreadable_or_unresolved": True,
                "explicit_user_or_domain_reviewer_deficiency_is_binding": True,
            },
        }
        return self.registry.set_stage5_plan(plan)

    def _stage5_plan_view(self) -> dict:
        plan = self._compose_stage5_plan()
        return {
            **deepcopy(plan),
            "conclusion_jobs": [
                {**deepcopy(row), "status": (
                    "completed" if row["discovered_requirement_key"] in
                    self.registry.conclusion_drafts else "pending"
                )}
                for row in plan["conclusion_jobs"]
            ],
        }

    def _compose_conclusion_draft(self, submitted: dict) -> dict:
        plan = self._compose_stage5_plan()
        key = submitted["discovered_requirement_key"]
        job = next((row for row in plan["conclusion_jobs"]
                    if row["discovered_requirement_key"] == key), None)
        if job is None:
            raise RegistryError("unknown Stage 5 conclusion job")
        status = submitted["inspection_status"]
        applicability = submitted["normative_applicability"]
        if status not in job["allowed_inspection_statuses"]:
            raise RegistryError(
                f"{key} has unresolved inputs and therefore must be not_assessed"
            )
        if applicability in {"false", "indeterminate"} and status != "not_assessed":
            raise RegistryError(
                "false or indeterminate normative applicability cannot support a compliance conclusion"
            )
        reason = submitted["inspection_reason"].strip()
        if not reason:
            raise RegistryError("Stage 5 conclusion requires a reason")
        evidence = [
            row for row in self.registry.evidence_records.values()
            if row.get("discovered_requirement_key") == key
        ]
        evidence_ids = sorted(row["evidence_id"] for row in evidence)
        measurement_ids = sorted({
            source_id for row in evidence for source_id in row.get("source_ids", [])
            if source_id in self.registry.measurement_records
        })
        tools_called = sorted({
            tool for row in evidence for tool in row.get("tools_used", [])
        })
        acquisition_attempts = sorted({
            row.get("acquisition_attempt_id") for row in evidence
            if row.get("acquisition_attempt_id")
        })
        return {
            "discovered_requirement_key": key,
            "candidate_label": job["candidate_label"],
            "modality": job["modality"],
            "normative_class": job["normative_class"],
            "normative_applicability": applicability,
            "acquisition_plan": list(
                self.registry.data_availability.get(key, {}).get("planned_tools", [])
            ),
            "acquisition_attempts": acquisition_attempts,
            "tools_called": tools_called,
            "acquired_inputs": job["acquired_inputs"],
            "derivation_evidence_ids": [],
            "external_evidence_ids": [],
            "unresolved_inputs": job["unresolved_inputs"],
            "final_data_availability": (
                "acquired" if not job["unresolved_inputs"] else "partial"
            ),
            "failure_reason": (
                None if not job["unresolved_inputs"] else
                "Required inputs remain unresolved: " + "; ".join(job["unresolved_inputs"])
            ),
            "image_assessable": any(
                row.get("evidence_kind") == "visual_observation" and
                row.get("acquired_inputs") for row in evidence
            ),
            "inspection_status": status,
            "evidence_ids": evidence_ids,
            "measurement_ids": measurement_ids,
            "inspection_reason": reason,
            "requires_human_review": False,
            "source_locator": job["source_locator"],
        }

    def _record_stage5_conclusion_batch(self, arguments: dict) -> dict:
        drafts = [self._compose_conclusion_draft(row)
                  for row in arguments["conclusions"]]
        return self.registry.record_conclusion_draft_batch(drafts)

    def _stage5_readiness(self) -> dict:
        plan = self._compose_stage5_plan()
        planned = {row["discovered_requirement_key"] for row in plan["conclusion_jobs"]}
        drafted = set(self.registry.conclusion_drafts)
        missing = sorted(planned - drafted)
        unexpected = sorted(drafted - planned)
        constraint_errors = []
        for key, row in self.registry.conclusion_drafts.items():
            requirement = self.registry.requirements[key]
            expected_class = "Mandatory" if requirement["modality"] == "shall" else "Guidance"
            if row.get("modality") != requirement["modality"] or row.get("normative_class") != expected_class:
                constraint_errors.append(f"{key}:modality_mismatch")
            if row.get("unresolved_inputs") and row.get("inspection_status") != "not_assessed":
                constraint_errors.append(f"{key}:unresolved_but_concluded")
            if (row.get("normative_applicability") in {"false", "indeterminate"} and
                    row.get("inspection_status") != "not_assessed"):
                constraint_errors.append(f"{key}:inapplicable_but_concluded")
            if not set(row.get("evidence_ids", [])).issubset(self.registry.evidence_records):
                constraint_errors.append(f"{key}:unknown_evidence")
        ready = not missing and not unexpected and not constraint_errors
        return {
            "ready": ready,
            "plan_id": plan["plan_id"],
            "conclusion_drafts_completed": len(drafted & planned),
            "conclusion_drafts_total": len(planned),
            "missing_requirement_keys": missing,
            "unexpected_requirement_keys": unexpected,
            "constraint_errors": constraint_errors,
            "mandatory_count": sum(
                row.get("normative_class") == "Mandatory"
                for row in self.registry.conclusion_drafts.values()
            ),
            "guidance_count": sum(
                row.get("normative_class") == "Guidance"
                for row in self.registry.conclusion_drafts.values()
            ),
            "status_counts": dict(Counter(
                row.get("inspection_status")
                for row in self.registry.conclusion_drafts.values()
            )),
            "next_actions": ([{"tool": "seal_conclusions"}] if ready else
                             [{"tool": "record_stage5_conclusion_batch",
                               "requirement_keys": missing}]),
        }

    def _submit_next_stage6_batch(self) -> dict:
        """Copy sealed Stage 5 drafts into final records without reinterpretation."""
        self.registry._require_phase("result_submission")
        missing_drafts = sorted(
            set(self.registry.requirements) - set(self.registry.conclusion_drafts)
        )
        if missing_drafts:
            raise RegistryError(
                f"Stage 6 cannot start before all conclusion drafts are sealed: {missing_drafts}"
            )
        pending = sorted(
            set(self.registry.requirements) - set(self.registry.inspections)
        )[:self.registry.max_batch_size]
        if not pending:
            raise RegistryError("no pending Stage 6 results")
        inspection_fields = (
            "discovered_requirement_key", "normative_applicability", "acquisition_plan",
            "acquisition_attempts", "tools_called", "acquired_inputs",
            "derivation_evidence_ids", "external_evidence_ids", "unresolved_inputs",
            "final_data_availability", "failure_reason", "image_assessable",
            "inspection_status", "evidence_ids", "measurement_ids",
            "inspection_reason", "requires_human_review",
        )
        inspections = [
            {
                field: deepcopy(self.registry.conclusion_drafts[key].get(field))
                for field in inspection_fields
            }
            for key in pending
        ]
        arguments = {"inspections": inspections}
        self._validate_inspection_evidence(arguments)
        result = self.registry.submit_inspection_batch(**arguments)
        return {
            **result,
            "copied_from_sealed_stage5_drafts": True,
            "remaining_result_count": len(self.registry.requirements) - len(self.registry.inspections),
        }

    def _finalize_stage6(self) -> dict:
        """Create completion metadata from persistent state and finalize once."""
        self.registry._require_phase("result_submission")
        pending = sorted(set(self.registry.requirements) - set(self.registry.inspections))
        if pending:
            raise RegistryError(f"Stage 6 results remain pending: {pending}")
        not_assessed = sorted(
            key for key, row in self.registry.inspections.items()
            if row.get("inspection_status") == "not_assessed"
        )
        source_units = sorted({
            str(row.get("source_locator") or "").split(";")[0].strip()
            for row in self.registry.requirements.values()
            if row.get("source_locator")
        })
        completion = {
            "stop_reason": (
                "Every registered requirement has one final result copied from the sealed "
                "Stage 5 conclusion ledger."
            ),
            "searched_layouts": sorted({
                row.get("layout_code") for row in self.registry.selected_layouts
                if row.get("layout_code")
            }),
            "searched_regions": sorted(self.registry.regions),
            "followed_cross_references": source_units,
            "unresolved_queries": ([
                "Some registered requirements remain not assessed because their bound evidence "
                "ledger contains unresolved inputs or does not support a definitive conclusion."
            ] if not_assessed else []),
            "remaining_potentially_checkable_items": not_assessed,
            "agent_declared_completion_status": "complete",
        }
        return self.registry.finalize(completion)

    def _measurement_call(self, name: str, arguments: dict) -> dict:
        key = arguments["discovered_requirement_key"]
        requirement, _ = self.registry.validate_measurement_request(key, name)
        thresholds = self._resolved_thresholds(requirement)
        call_args = {k: v for k, v in arguments.items() if k != "discovered_requirement_key"}
        if name == "audit_channelizer_spacing":
            by_condition: dict[str, dict] = {}
            for rule in thresholds:
                condition = rule["condition"].lower()
                region = "taper" if "taper" in condition else "tangent" if "tangent" in condition else None
                if not region or region in by_condition:
                    raise RegistryError("registered spacing thresholds must uniquely identify taper and tangent conditions")
                by_condition[region] = {key: rule[key] for key in ("value", "unit", "violation_when")}
            result = self.scene.audit_channelizer_spacing(by_condition)
        else:
            if len(thresholds) != 1:
                raise RegistryError("measurement tool requires exactly one registered threshold")
            rule = thresholds[0]
            threshold_args = {"threshold_value": rule["value"], "threshold_unit": rule["unit"],
                              "violation_when": rule["violation_when"]}
            result = getattr(self.scene, name)(**call_args, **threshold_args)
        bound = self.registry.bind_measurement(key, name, result)
        if bound.get("measurement_id"):
            self.scene.measurements[bound["measurement_id"]] = bound
        return bound

    def _validate_inspection_evidence(self, args: dict) -> None:
        observations = set(self.scene.observations)
        measurements = set(self.scene.measurements)
        speeds = set(self.scene.speed_evidence)
        stage4_evidence = set(self.registry.evidence_records)
        direct_sources = {"scene_facts", "scene_data_manifest"}
        manual_sources = {row["node_id"] for row in self.retrieval.nodes}
        for row in args["inspections"]:
            if row.get("requires_human_review"):
                raise RegistryError("human review is forbidden in this autonomous canary")
            key = row.get("discovered_requirement_key", "")
            requirement = self.registry.requirements.get(key, {})
            requirement_text = " ".join(str(requirement.get(k, "")) for k in ("subject", "relation", "threshold")).lower()
            exit_text = " ".join([str(row.get("failure_reason") or ""), str(row.get("inspection_reason") or ""),
                                  " ".join(row.get("unresolved_inputs", []))]).lower()
            if self.scene.pcms_observation_ids and ("pcms" in requirement_text or "changeable message" in requirement_text):
                if row.get("inspection_status") == "not_assessed" and (
                    ("deployment" in exit_text and "unknown" in exit_text) or
                    "no confirmed pcms" in exit_text or "pcms_deployed" in exit_text
                ):
                    raise RegistryError("accepted PCMS bbox establishes deployment; deployment-unknown exit is forbidden")
            cited = [self.scene.measurements[mid] for mid in row.get("measurement_ids", []) if mid in measurements]
            for measurement in cited:
                if measurement.get("discovered_requirement_key") != key:
                    raise RegistryError("measurement is bound to a different registered requirement")
                if measurement.get("requirement_fingerprint") != requirement.get("requirement_fingerprint"):
                    raise RegistryError("measurement requirement fingerprint mismatch")
                if measurement.get("requirement_registration_event_index", 10**12) >= measurement.get("measurement_event_index", -1):
                    raise RegistryError("measurement_before_requirement_registration")
            geometry_terms = {"distance", "spacing", "interval", "length", "width", "taper", "buffer"}
            if row.get("inspection_status") == "deficient" and any(term in requirement_text for term in geometry_terms):
                if not cited or not any(measurement.get("deficiency_supported") is True for measurement in cited):
                    raise RegistryError("geometry deficiency lacks a bound, confidence-supported measurement")
            bad_evidence = (set(row["evidence_ids"]) - observations - measurements - speeds -
                            stage4_evidence - direct_sources - manual_sources)
            bad_measurements = set(row["measurement_ids"]) - measurements
            bad_derived = (set(row["derivation_evidence_ids"]) - measurements - speeds - observations -
                           stage4_evidence - direct_sources)
            bad_external = set(row["external_evidence_ids"]) - speeds
            if bad_evidence or bad_measurements or bad_derived or bad_external:
                raise RegistryError(f"unknown evidence IDs: evidence={sorted(bad_evidence)}, measurement={sorted(bad_measurements)}, derived={sorted(bad_derived)}, external={sorted(bad_external)}")

    def _validate_stage4_evidence_sources(self, arguments: dict) -> None:
        inspected_visual_ids: set[str] = set()
        for trace_row in self.trace:
            result = trace_row.get("result", {})
            if result.get("status") == "failure":
                continue
            if trace_row.get("tool") == "inspect_observation_images":
                for observation in result.get("observations", []):
                    inspected_visual_ids.add(observation.get("observation_id"))
                    if observation.get("source_image"):
                        inspected_visual_ids.add(Path(observation["source_image"]).stem)
            elif trace_row.get("tool") == "inspect_temporal_images":
                inspected_visual_ids.update(
                    image.get("image_id") for image in result.get("images", []) if image.get("image_id")
                )
        measurement_ids = set(self.scene.measurements)
        persistent_evidence_ids = set(self.registry.evidence_records)
        facts = self.scene_view.get("scene_facts", {})
        for item in arguments["evidence"]:
            kind = item["evidence_kind"]
            source_ids = set(item["source_ids"])
            if kind == "visual_observation":
                unknown = source_ids - inspected_visual_ids
                if unknown:
                    raise RegistryError(f"visual evidence cites images or observations not inspected: {sorted(unknown)}")
            elif kind == "measurement_context":
                unknown = source_ids - measurement_ids
                if unknown:
                    raise RegistryError(f"measurement evidence cites unknown measurements: {sorted(unknown)}")
                measured_inputs = [
                    value for value in item.get("acquired_inputs", [])
                    if value.casefold().startswith("measured ")
                ]
                if measured_inputs:
                    cited_measurements = [self.scene.measurements[value] for value in source_ids]
                    usable = any(
                        (row.get("measurement_type") == "channelizer_spacing_series" and
                         row.get("sequence_inference_valid") is True)
                        or (row.get("endpoint_semantics_valid") is True and
                            row.get("geometry_direction_valid") is True and
                            row.get("threshold_assessment", {}).get("status") != "geometry_not_eligible")
                        for row in cited_measurements
                    )
                    if not usable:
                        raise RegistryError(
                            f"measurement quality gate failed; inputs must remain unresolved: {measured_inputs}"
                        )
            elif kind == "direct_fact":
                unknown = []
                for source_id in source_ids:
                    if source_id.startswith("scene_fact:"):
                        fact_name = source_id.split(":", 1)[1].split("=", 1)[0]
                        if fact_name not in facts or facts[fact_name] is None:
                            unknown.append(source_id)
                    elif not (source_id.startswith("scene_manifest:") or
                              source_id.startswith("selected_layout:")):
                        unknown.append(source_id)
                if unknown:
                    raise RegistryError(f"direct evidence cites unknown or null facts: {sorted(unknown)}")
            elif kind == "acquisition_failure" and source_ids:
                known = inspected_visual_ids | measurement_ids | persistent_evidence_ids
                unknown = []
                for source_id in source_ids:
                    if source_id in known:
                        continue
                    if source_id.startswith("scene_fact:"):
                        fact_name = source_id.split(":", 1)[1].split("=", 1)[0]
                        if fact_name in facts and facts[fact_name] is not None:
                            continue
                    if source_id.startswith("scene_manifest:") or source_id.startswith("selected_layout:"):
                        continue
                    unknown.append(source_id)
                if unknown:
                    raise RegistryError(
                        f"acquisition failure cites sources that were not inspected or persisted: {sorted(unknown)}"
                    )

    def _representative_observation_ids(self, reviewed_class: str) -> set[str]:
        representatives: dict[str, tuple[float, str]] = {}
        for observation in self.scene.observations.values():
            if observation.get("reviewed_class") != reviewed_class:
                continue
            entity_id = (observation.get("refined_element_id") or
                         observation.get("raw_device_id") or observation["observation_id"])
            bbox = observation["bbox"]
            area = max(0.0, float(bbox[2]) - float(bbox[0])) * max(
                0.0, float(bbox[3]) - float(bbox[1])
            )
            current = representatives.get(entity_id)
            if current is None or area > current[0]:
                representatives[entity_id] = (area, observation["observation_id"])
        return {value[1] for value in representatives.values()}

    def _validate_stage4_completion(self) -> None:
        inspected_observations: set[str] = set()
        temporal_indices: dict[str, set[int]] = {}
        for trace_row in self.trace:
            if trace_row.get("result", {}).get("status") == "failure":
                continue
            if trace_row.get("tool") == "inspect_observation_images":
                inspected_observations.update(trace_row.get("arguments", {}).get("observation_ids", []))
            elif trace_row.get("tool") == "inspect_temporal_images":
                arguments = trace_row.get("arguments", {})
                channel = arguments.get("channel")
                start = int(arguments.get("start_cursor", 0))
                count = int(arguments.get("count", 0))
                stride = int(arguments.get("stride", 1))
                total = len(self.scene.rows_by_channel.get(channel, []))
                temporal_indices.setdefault(channel, set()).update(
                    index for index in range(start, start + count * stride, stride) if index < total
                )

        requirement_text = " ".join(
            " ".join(str(requirement.get(field, "")) for field in (
                "subject", "relation", "threshold", "required_inputs"
            )).casefold()
            for requirement in self.registry.requirements.values()
        )
        if any(term in requirement_text for term in ("warning sign", "sign legend", "road work sign")):
            sign_representatives = self._representative_observation_ids("traffic_sign")
            missing = sign_representatives - inspected_observations
            if missing:
                raise RegistryError(
                    f"Stage 4 must inspect every representative traffic-sign candidate before sealing: "
                    f"{len(missing)} remain"
                )
        if "arrow board" in requirement_text or "arrow-board" in requirement_text:
            arrow_representatives = self._representative_observation_ids("arrow_board")
            missing = arrow_representatives - inspected_observations
            if missing:
                raise RegistryError("Stage 4 must inspect the accepted Arrow Board candidate before sealing")
        if "channeliz" in requirement_text or "device condition" in requirement_text:
            for reviewed_class in ("channelizing_device", "traffic_cone", "traffic_drum", "barricade"):
                representatives = self._representative_observation_ids(reviewed_class)
                if representatives and not (representatives & inspected_observations):
                    raise RegistryError(
                        f"Stage 4 must inspect at least one representative {reviewed_class} candidate before sealing"
                    )
        front_indices = sorted(temporal_indices.get("CAM_FRONT", set()))
        total_front = len(self.scene.rows_by_channel.get("CAM_FRONT", []))
        temporal_required = any(term in requirement_text for term in (
            "transition", "taper", "work space", "work-space", "downstream", "operation type",
            "traffic movement", "advance warning",
        ))
        if (temporal_required and (len(front_indices) < 8 or not front_indices or
                front_indices[-1] - front_indices[0] < 0.7 * max(1, total_front - 1))):
            raise RegistryError(
                "Stage 4 temporal coverage must include at least 8 CAM_FRONT frames spanning 70% of the traversal"
            )

        class_by_observation = {
            key: value.get("reviewed_class") for key, value in self.scene.observations.items()
        }
        for key, requirement in self.registry.requirements.items():
            text = " ".join(str(requirement.get(field, "")) for field in (
                "subject", "relation", "threshold", "required_inputs"
            )).casefold()
            evidence_sources = {
                source_id for evidence in self.registry.evidence_records.values()
                if evidence["discovered_requirement_key"] == key
                for source_id in evidence.get("source_ids", [])
            }
            if "arrow board" in text or "arrow-board" in text:
                if not any(class_by_observation.get(source_id) == "arrow_board"
                           for source_id in evidence_sources):
                    raise RegistryError(f"Arrow Board evidence for {key} must cite an inspected Arrow Board observation")
            if any(term in text for term in ("warning sign", "sign legend", "road work sign")):
                if not any(class_by_observation.get(source_id) == "traffic_sign"
                           for source_id in evidence_sources):
                    raise RegistryError(f"sign evidence for {key} must cite an inspected traffic-sign observation")

    def _validate_simplified_region_completion(self, arguments: dict) -> None:
        required = {
            "lane_closure_layout", "advance_warning_sign_system",
            "channelization_system", "transition_and_taper_geometry",
        }
        facts = self.scene_view.get("scene_facts", {})
        if facts.get("arrow_board_deployed") is True or facts.get("pcms_deployed") is True:
            required.add("conditional_active_devices")
        if any(facts.get(key) is True for key in (
                "downstream_taper_present", "downstream_taper_deployed",
                "end_road_work_sign_present", "termination_sign_present")):
            required.add("conditional_termination_area")
        counts = Counter(row.get("region") for row in self.registry.requirements.values())
        attempted = {row["region"] for row in arguments["regions"]
                     if row.get("status") == "screened"}
        missing = sorted(domain for domain in required
                         if domain in attempted and not counts.get(domain))
        if missing:
            raise RegistryError(
                f"applicable domains require at least one inspection check before completion: {missing}"
            )

    def call(self, name: str, arguments: dict) -> dict:
        cacheable = name in RETRIEVAL_TOOLS | INVENTORY_TOOLS
        cache_key = json.dumps([name, arguments], sort_keys=True, separators=(",", ":"))
        try:
            if _contains_hidden_id(arguments):
                raise RegistryError("internal requirement_id is forbidden")
            if not self._allowed(name):
                if name in NORMATIVE_MEASUREMENT_TOOLS:
                    raise RegistryError("measurement_before_requirement_registration")
                raise RegistryError(f"phase_violation: {name} is unavailable during {self.registry.phase}")
            if cacheable and cache_key in self.cache:
                result = deepcopy(self.cache[cache_key])
                result["cache_hit"] = True
            elif name in RETRIEVAL_TOOLS:
                if self.scoped_stage1_stage2 and name == "expand_source_unit":
                    selected_codes = {row.get("layout_code") for row in self.registry.selected_layouts}
                    if arguments.get("source_unit_code") not in selected_codes:
                        raise RegistryError(
                            "scoped discovery uses expand_source_unit only for the selected TA; "
                            "use expand_source_unit_for_need for governing sections and tables"
                        )
                result = getattr(self.retrieval, name)(**arguments)
                self._remember_retrieved_nodes(result)
            elif name == "load_ta_core_graph":
                result = self._load_ta_core_graph()
            elif name == "load_scene_condition_graph":
                result = self._load_scene_condition_graph()
            elif name == "audit_graph_gaps":
                result = self._audit_graph_gaps(arguments)
            elif name == "load_domain_gap_candidates":
                result = self._load_domain_gap_candidates(arguments)
            elif name == "search_manual_for_need":
                result = self._search_manual_for_need(arguments)
            elif name == "expand_source_unit_for_need":
                result = self._expand_source_unit_for_need(arguments)
            elif name == "record_domain_discovery":
                result = self._record_domain_discovery(arguments)
            elif name == "begin_requirement_registration":
                if self.simplified_inspection_checks:
                    if self.stage1_architecture in {"kg_plus_retrieval", "kg_only"}:
                        if self.graph_stage1a_result is None or self.graph_stage1b_result is None:
                            raise RegistryError("simplified discovery requires Stage 1A and Stage 1B")
                    if self.stage1_architecture in {"kg_plus_retrieval", "retrieval_only"}:
                        pending = [domain for domain, pages in self.graph_gap_audits.items()
                                   if not pages]
                        if pending:
                            raise RegistryError(
                                f"simplified six-domain retrieval is incomplete: {pending}"
                            )
                    for domain in COVERAGE_DOMAINS:
                        node_ids = sorted(self.graph_candidate_node_ids[domain])
                        self.discovery_coverage[domain] = {
                            "domain": domain,
                            "status": ("covered_with_candidates" if node_ids
                                       else "covered_no_activated_candidate"),
                            "query_summary": "program-composed Stage 1A/1B/1C candidate pool",
                            "source_node_ids": node_ids,
                        }
                elif self.scoped_stage1_stage2:
                    pending = [domain for domain, row in self.discovery_coverage.items()
                               if row["status"] == "pending"]
                    if pending:
                        raise RegistryError(f"six-domain discovery ledger is incomplete: {pending}")
                result = self.registry.begin_requirement_registration()
            elif name == "submit_atomic_requirement_batch":
                result = self._submit_atomic_requirement_batch(arguments)
            elif name == "submit_inspection_check_batch":
                result = self._submit_atomic_requirement_batch(arguments)
            elif name == "exclude_discovery_candidate_batch":
                result = self._exclude_discovery_candidate_batch(arguments)
            elif name == "audit_stage2_candidate_coverage":
                result = self._audit_stage2_candidate_coverage()
            elif name == "submit_stage2_candidate_decision_batch":
                result = self._submit_stage2_candidate_decision_batch(arguments)
            elif name == "submit_requirement_batch":
                self._validate_requirement_sources(arguments)
                result = self.registry.submit_requirement_batch(**arguments)
            elif name == "complete_region_batch":
                if self.simplified_inspection_checks:
                    self._validate_simplified_region_completion(arguments)
                result = self.registry.complete_region_batch(**arguments)
            elif name == "seal_requirement_registration":
                if self.scoped_stage1_stage2:
                    if self.simplified_inspection_checks:
                        if self.stage1_architecture in {"kg_plus_retrieval", "kg_only"}:
                            if self.stage2_audit_revision != self.stage2_decision_revision:
                                raise RegistryError(
                                    "Stage 2 candidate coverage audit is missing or stale; call "
                                    "audit_stage2_candidate_coverage after the latest successful "
                                    "registration or exclusion, then review its unresolved candidates"
                                )
                            registered_or_excluded = {
                                node_id
                                for requirement in self.registry.requirements.values()
                                for node_id in requirement.get("source_node_ids", [])
                            } | {
                                node_id
                                for rows in self.discovery_candidate_exclusions.values()
                                for node_id in rows
                            }
                            pending_decisions = sorted(
                                self.stage2_audited_node_ids - registered_or_excluded
                            )
                            if pending_decisions:
                                raise RegistryError(
                                    "Stage 2 structured candidate decisions are incomplete: " +
                                    json.dumps(pending_decisions, separators=(",", ":"))
                                )
                            self.high_confidence_disposition_gaps = (
                                self._discovery_candidate_disposition_gaps(
                                deterministic_only=True
                                )
                            )
                    else:
                        self._validate_discovery_candidate_dispositions()
                result = self.registry.seal_requirement_registration()
            elif name == "submit_data_availability_batch":
                if not self.scene.observations and any(
                    "accepted_bbox_observations" in row.get("available_inputs", [])
                    for row in arguments.get("assessments", [])
                ):
                    raise RegistryError(
                        "This scene has zero accepted bbox observations; "
                        "accepted_bbox_observations must remain a missing input "
                        "until reviewed observations are supplied."
                    )
                result = self.registry.submit_data_availability_batch(**arguments)
            elif name == "seal_data_availability":
                result = self.registry.seal_data_availability()
            elif name == "get_stage4_acquisition_plan":
                result = self._stage4_plan_view()
            elif name == "inspect_stage4_visual_job":
                result = self._inspect_stage4_visual_job(**arguments)
            elif name == "record_visual_job_note":
                result = self._record_visual_job_note(arguments)
            elif name == "run_registered_measurement":
                result = self._run_registered_measurement(arguments)
            elif name == "record_visual_finding":
                result = self._record_visual_finding(arguments)
            elif name == "record_visual_finding_batch":
                result = self._record_visual_finding_batch(arguments)
            elif name == "record_measurement_finding":
                result = self._record_measurement_finding(arguments)
            elif name == "record_measurement_finding_batch":
                result = self._record_measurement_finding_batch(arguments)
            elif name == "record_acquisition_failure":
                result = self._record_acquisition_failure(arguments)
            elif name == "get_stage4_readiness":
                result = self.registry.record_stage4_readiness(self._stage4_readiness())
            elif name in NORMATIVE_MEASUREMENT_TOOLS:
                result = self._measurement_call(name, arguments)
            elif name == "record_evidence_batch":
                self._validate_stage4_evidence_sources(arguments)
                result = self.registry.record_evidence_batch(**arguments)
            elif name == "seal_measurements":
                if self.orchestrated_stage4:
                    readiness = self._stage4_readiness()
                    if not readiness["ready"]:
                        raise RegistryError(
                            "Stage 4 readiness is incomplete: " +
                            json.dumps(readiness, ensure_ascii=False, separators=(",", ":"))
                        )
                else:
                    self._validate_stage4_completion()
                result = self.registry.seal_measurements()
            elif name == "begin_result_submission":
                result = self.registry.begin_result_submission()
            elif name == "get_stage5_conclusion_plan":
                result = self._stage5_plan_view()
            elif name == "record_stage5_conclusion_batch":
                result = self._record_stage5_conclusion_batch(arguments)
            elif name == "get_stage5_readiness":
                result = self.registry.record_stage5_readiness(
                    self._stage5_readiness()
                )
            elif name == "seal_conclusions":
                readiness = self._stage5_readiness()
                if not readiness["ready"]:
                    raise RegistryError(
                        "Stage 5 readiness is incomplete: " +
                        json.dumps(readiness, ensure_ascii=False, separators=(",", ":"))
                    )
                result = self.registry.seal_conclusions()
            elif name == "submit_next_stage6_batch":
                result = self._submit_next_stage6_batch()
            elif name == "finalize_stage6":
                self.registry.assert_measurement_order()
                result = self._finalize_stage6()
            elif name == "submit_inspection_batch":
                self._validate_inspection_evidence(arguments)
                result = self.registry.submit_inspection_batch(**arguments)
            elif name == "finalize_registry":
                self.registry.assert_measurement_order()
                result = self.registry.finalize(**arguments)
            elif hasattr(self.scene, name):
                result = getattr(self.scene, name)(**arguments)
            else:
                raise ValueError(f"unknown tool: {name}")
        except Exception as exc:
            self.tool_failures += 1
            result = {"status": "failure", "failure_reason": str(exc), "tool": name}
        if cacheable and result.get("status") != "failure" and not result.get("cache_hit"):
            self.cache[cache_key] = deepcopy(result)
        if name in NORMATIVE_MEASUREMENT_TOOLS or (hasattr(self.scene, name) and name not in INVENTORY_TOOLS):
            self.registry.record_tool_call(name, result, arguments.get("discovered_requirement_key"))
        visible = {key: value for key, value in result.items() if key != "_image_paths"}
        self.trace.append({"step": len(self.trace) + 1, "phase": self.registry.phase,
                           "tool": name, "arguments": deepcopy(arguments), "result": visible})
        return result

    def resources(self) -> dict[str, Any]:
        return {**self.retrieval.resource_snapshot(), **self.scene.resource_snapshot(),
                "tool_calls_total": len(self.trace), "tool_failures": self.tool_failures,
                "resumed_tool_calls": self.resume_trace_length,
                "session_tool_calls": len(self.trace) - self.resume_trace_length,
                "resumed_tool_failures": self.resume_tool_failure_count,
                "session_tool_failures": self.tool_failures - self.resume_tool_failure_count,
                "tool_retries": self.retries,
                "high_confidence_disposition_gap_count": len(
                    self.high_confidence_disposition_gaps
                ),
                "high_confidence_disposition_gaps": deepcopy(
                    self.high_confidence_disposition_gaps
                ),
                "stage2_candidate_audit_calls": self.stage2_candidate_audit_calls,
                "stage2_audited_candidate_count": len(self.stage2_audited_node_ids),
                "stage2_structured_decision_count": len(self.stage2_candidate_decisions),
                "stage2_structured_decisions": deepcopy(self.stage2_candidate_decisions),
                "stage2_decision_revision": self.stage2_decision_revision,
                "stage2_audit_revision": self.stage2_audit_revision,
                "stage2_verification_unresolved_count": len(
                    self.stage2_verification_unresolved
                ),
                "stage2_verification_unresolved": deepcopy(
                    self.stage2_verification_unresolved
                )}


def validate_trace_measurement_order(trace: list[dict]) -> list[str]:
    registered: set[str] = set()
    issues: list[str] = []
    for row in trace:
        if row.get("tool") in {"submit_requirement_batch", "submit_atomic_requirement_batch",
                               "submit_inspection_check_batch"}:
            registered.update(row.get("result", {}).get("accepted_requirement_keys", []))
            registered.update(row.get("result", {}).get("accepted_requirements", {}).keys()
                              if isinstance(row.get("result", {}).get("accepted_requirements"), dict) else [])
        if row.get("tool") in NORMATIVE_MEASUREMENT_TOOLS:
            if row.get("result", {}).get("status") == "failure":
                continue
            key = row.get("arguments", {}).get("discovered_requirement_key")
            if not key or key not in registered:
                issues.append(f"step {row.get('step')}: measurement_before_requirement_registration ({row.get('tool')})")
    return issues


def schema_fingerprint() -> str:
    return hashlib.sha256(json.dumps(ToolGatewayV5.definitions(), sort_keys=True).encode()).hexdigest()
