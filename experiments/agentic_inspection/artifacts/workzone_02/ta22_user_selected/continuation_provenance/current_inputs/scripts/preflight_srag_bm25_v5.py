#!/usr/bin/env python3
"""Offline execution lock for the staged S-RAG-BM25 canary."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat

from dense_gap_retrieval import DenseGapIndex
from inspection_registry_v5 import NORMATIVE_MEASUREMENT_TOOLS, REGIONS
from project_common import ROOT, sha256
from run_srag_bm25_v5 import (
    CONFIG_PATH, phase_contract, public_scene_input, stage0_prompt,
    simplified_stage1_stage2_prompt, stage1_stage2_scoped_prompt, workflow_prompt,
)
from scene_data_tools_v5 import SceneDataToolsV5
from srag_bm25_retrieval_v5 import StructuredBM25V5
from srag_bm25_tools_v5 import (
    ToolGatewayV5, scene_tool_definitions, schema_fingerprint,
    scoped_discovery_registration_definitions, validate_trace_measurement_order,
)


INTERNAL_ID_PATTERN = re.compile(r"\bL\d{2}-[A-Z0-9]+(?:-[A-Z0-9]+)+\b")


def record(path: Path) -> dict:
    return {"path": str(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}


def add(checks: list[dict], name: str, passed: bool, evidence) -> None:
    checks.append({"number": len(checks) + 1, "name": name, "passed": bool(passed),
                   "status": "passed" if passed else "failed", "critical": True,
                   "evidence": evidence})


def deployment_inventory_consistent(manifest: dict) -> bool:
    """Absence of accepted observations means unknown, for every case."""
    return all(
        manifest["derived_scene_facts"].get(f"{kind}_deployed") is
        (True if manifest["counts"][f"accepted_{kind}_observations"] else None)
        for kind in ("arrow_board", "pcms")
    )


def scene_source_path(scene: dict, defaults: dict, name: str) -> Path:
    """New cases must never silently freeze Work Zone 01 evidence sources."""
    path = scene.get("data_sources", {}).get(name)
    if path is None:
        if scene.get("scene_id") != "scene-CATS-01":
            raise ValueError(f"scene-specific data_sources.{name} is required")
        path = defaults[name]
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def resume_measurement_boundary_valid(gateway, expects_measurements: bool) -> bool:
    if not expects_measurements:
        return not gateway.scene.measurements
    if gateway.scene.measurements:
        return True
    # A sealed acquisition stage can legitimately contain only documented
    # failures. Require its complete evidence accounting, not invented values.
    return bool(gateway.orchestrated_stage4
                and (gateway.registry.stage4_readiness or {}).get("ready") is True
                and gateway._stage4_readiness().get("ready") is True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()
    config_path = args.config.resolve()
    cfg = json.loads(config_path.read_text())
    scene_path = ROOT / cfg["scene_manifest"]
    scene = json.loads(scene_path.read_text())
    view = public_scene_input(scene, SceneDataToolsV5(scene_path).manifest())
    checks: list[dict] = []

    credential_path = Path(cfg["credential_config"]).expanduser().resolve()
    credential_mode = stat.S_IMODE(credential_path.stat().st_mode) if credential_path.exists() else None
    add(checks, "configured credential is present and private",
        credential_path.exists() and credential_mode == 0o600,
        {"credential_path": str(credential_path),
         "file_mode": None if credential_mode is None else oct(credential_mode)})

    gateway = ToolGatewayV5([], view, scene_manifest=scene_path)
    early = gateway.call("audit_channelizer_spacing", {"discovered_requirement_key": "req_not_registered"})
    add(checks, "unregistered normative measurement is rejected",
        early.get("failure_reason") == "measurement_before_requirement_registration", early)

    expanded = gateway.call("expand_source_unit", {"source_unit_code": "SEC-6K.01",
        "region": "channelizing_devices", "page_size": 12, "continuation_token": None})
    node = next(row for row in expanded["items"] if row.get("paragraph") == "04")
    gateway.call("begin_requirement_registration", {})
    registered = gateway.call("submit_requirement_batch", {"region": "channelization_system", "requirements": [{
        "candidate_label": "channelizer spacing", "subject": node["subject"],
        "modality": node["modality"], "relation": node["relation"], "threshold": node["threshold"],
        "applicability_conditions": node["applicability_conditions"],
        "required_inputs": ["posted_speed_mph", "spacing_measurement"],
        "source_node_ids": [node["source_node_id"]], "source_locator": node["source_locator"],
        "source_span": node["source_span"],
        "measurement_spec": {"required": True, "tool": "audit_channelizer_spacing",
            "quantity": "adjacent device spacing", "thresholds": [
                {"condition": "taper", "value": None, "unit": "ft", "violation_when": "above_maximum",
                 "formula_parameter": "posted_speed_mph", "multiplier": 1.0},
                {"condition": "tangent", "value": None, "unit": "ft", "violation_when": "above_maximum",
                 "formula_parameter": "posted_speed_mph", "multiplier": 2.0},
            ]},
    }]})
    key = registered.get("accepted_requirement_keys", [None])[0]
    gateway.call("complete_region_batch", {"regions": [
        {"region": region, "status": "screened", "reason": "preflight screening"} for region in REGIONS
    ]})
    gateway.call("seal_requirement_registration", {})
    unknown = gateway.call("audit_channelizer_spacing", {"discovered_requirement_key": "req_not_present"})
    add(checks, "nonexistent run-local key is rejected",
        unknown.get("failure_reason") == "measurement_before_requirement_registration", unknown)
    gateway.call("submit_data_availability_batch", {"assessments": [{
        "discovered_requirement_key": key, "condition_data_complete": True,
        "available_inputs": ["posted_speed_mph", "spacing_measurement"], "missing_inputs": [],
        "data_availability": "available_direct", "basis_evidence_ids": ["scene_facts"],
        "reason": "frozen inputs available",
        "planned_tools": ["audit_channelizer_spacing"],
        "planned_evidence_strategy": "Measure the full accepted channelizer line.",
        "planned_decision_rule": "Only a sustained confidence-bounded exceedance supports deficiency.",
    }]})
    gateway.call("seal_data_availability", {})
    spacing = gateway.call("audit_channelizer_spacing", {"discovered_requirement_key": key})
    posted_speed = scene.get("scene_facts", {}).get("posted_speed_mph")
    if posted_speed is None:
        add(checks, "missing speed blocks a speed-dependent measurement without guessing",
            spacing.get("status") == "failure" and
            "formula input is unavailable" in spacing.get("failure_reason", ""), spacing)
    else:
        add(checks, "registered spacing audit evaluates geometry or explicitly has no valid sequence",
            spacing.get("status") == "acquired" and (
                spacing.get("gaps_evaluated", 0) > 0 or (
                    spacing.get("gaps_evaluated") == 0 and
                    spacing.get("sequence_inference_valid") is False and
                    spacing.get("deficiency_supported") is False
                )
            ), {
                k: spacing.get(k) for k in ("status", "measurement_id", "gaps_evaluated",
                                            "clear_exceedance_gap_count", "violation_run_count")})
        add(checks, "threshold is derived from registered formula and scene fact",
            spacing.get("thresholds_applied", {}).get("taper", {}).get("value") == float(posted_speed) and
            spacing.get("thresholds_applied", {}).get("tangent", {}).get("value") == 2.0 * float(posted_speed),
            spacing.get("thresholds_applied"))
    order_issues = validate_trace_measurement_order(gateway.trace)
    add(checks, "every current measurement follows its requirement registration",
        not order_issues and (
            posted_speed is None or
            spacing.get("requirement_registration_event_index", 99) <
            spacing.get("measurement_event_index", -1)
        ), {"issues": order_issues,
            "registration_event": spacing.get("requirement_registration_event_index"),
            "measurement_event": spacing.get("measurement_event_index")})

    schema_text = json.dumps(scene_tool_definitions(), ensure_ascii=False).lower()
    leaks = [token for token in ("6k.01", "s/2s", "9.144", "18.288", "paragraph 04", "pdf page")
             if token in schema_text]
    spacing_schema = next(row for row in scene_tool_definitions() if row["name"] == "audit_channelizer_spacing")
    add(checks, "measurement tool names descriptions schemas and defaults contain no answer leak",
        not leaks and spacing_schema["parameters"]["required"] == ["discovered_requirement_key"],
        {"leaks": leaks, "spacing_parameters": spacing_schema["parameters"]})
    norm_schemas = {row["name"]: row for row in scene_tool_definitions()
                    if row["name"] in NORMATIVE_MEASUREMENT_TOOLS}
    missing_keys = [name for name, row in norm_schemas.items()
                    if "discovered_requirement_key" not in row["parameters"]["required"]]
    add(checks, "all normative geometry tools require a run-local requirement key",
        set(norm_schemas) == NORMATIVE_MEASUREMENT_TOOLS and not missing_keys,
        {"normative_tools": sorted(norm_schemas), "missing_key": missing_keys})

    boundary = json.dumps({"stage0_prompt": stage0_prompt(view), "workflow_prompt": workflow_prompt(view, []),
                           "tools": ToolGatewayV5.definitions(), "scene_view": view}, ensure_ascii=False)
    add(checks, "model payload boundary contains no hidden target requirement ID",
        not INTERNAL_ID_PATTERN.search(boundary) and '"requirement_id"' not in boundary,
        {"pattern_matches": INTERNAL_ID_PATTERN.findall(boundary)})
    add(checks, "phase-specific tool exposure enforces the seven-stage sequence",
        gateway.registry.phase == "measurement" and
        all(name not in {row["name"] for row in gateway.available_definitions()}
            for name in ("search_manual", "submit_requirement_batch", "submit_inspection_batch")),
        {"phase": gateway.registry.phase,
         "available_tools": [row["name"] for row in gateway.available_definitions()]})
    contracts = {phase: phase_contract(phase, True) for phase in (
        "requirement_discovery", "requirement_registration", "data_availability",
    )}
    add(checks, "stage contracts state inputs outputs prohibitions and completion boundary",
        "expand the selected TA without a region filter" in contracts["requirement_discovery"] and
        "concrete compliance predicate" in contracts["requirement_registration"] and
        "set(available_inputs) union set(missing_inputs)" in contracts["data_availability"] and
        all("STOP IMMEDIATELY" in value for value in contracts.values()), contracts)

    retrieval = StructuredBM25V5()
    add(checks, "full-manual structure remains query-independent and has no page whitelist",
        retrieval.index.get("build_policy", {}).get("query_independent") is True and
        retrieval.search_manual("long term lane closure", 3).get("correct_page_or_application_whitelist") is None,
        retrieval.index.get("build_policy"))
    structure_validation_path = ROOT / "inputs/mutcd_structure_v1_validation.json"
    structure_validation = json.loads(structure_validation_path.read_text())
    structure_manifest_path = ROOT / "inputs/mutcd_structure_v1_manifest.json"
    structure_manifest = json.loads(structure_manifest_path.read_text())
    figure_assets = structure_manifest.get("figure_page_assets", [])
    figure_asset_failures = [row["path"] for row in figure_assets
                             if not Path(row["path"]).is_file() or
                             sha256(Path(row["path"])) != row["sha256"]]
    expected_ta_codes = {f"TA-{number}" for number in range(1, 55)}
    figure_asset_codes = {row.get("source_unit_code") for row in figure_assets}
    add(checks, "MUTCD structure validation and all Typical Application images are frozen",
        structure_validation.get("passed") is True and
        structure_validation.get("index_sha256") == sha256(retrieval.index_path) and
        len(figure_assets) == 54 and not figure_asset_failures and
        figure_asset_codes == expected_ta_codes,
        {"validation_report": str(structure_validation_path),
         "figure_asset_count": len(figure_assets), "asset_failures": figure_asset_failures,
         "missing_ta_assets": sorted(expected_ta_codes - figure_asset_codes),
         "unexpected_ta_assets": sorted(figure_asset_codes - expected_ta_codes)})
    graph_path = ROOT / cfg.get("knowledge_graph_index", "inputs/mutcd_knowledge_graph_v2.json")
    graph = json.loads(graph_path.read_text())
    graph_policy = graph.get("build_policy", {})
    graph_tas = {row["source_unit_code"] for row in graph.get("typical_applications", [])}
    graph_provisions = {row["provision_id"] for row in graph.get("normative_provisions", [])}
    structure_node_ids = {row["node_id"] for row in retrieval.index["atomic_nodes"]}
    structure_node_types = {row["node_id"]: row["node_type"]
                            for row in retrieval.index["atomic_nodes"]}
    structure_nodes = {row["node_id"]: row for row in retrieval.index["atomic_nodes"]}
    figure_provision_ids = {
        node_id for node_id in graph_provisions
        if structure_node_types[node_id] == "figure_component"
    }
    add(checks, "KG-first Stage 1 graph is source-bound, scene-independent, and complete over TAs",
        graph.get("schema_version") == "mutcd_knowledge_graph_v2" and
        graph.get("source_structure", {}).get("sha256") == sha256(retrieval.index_path) and
        graph_tas == {f"TA-{number}" for number in range(1, 55)} and
        graph_provisions <= structure_node_ids and
        all(structure_nodes[node_id].get("normative_basis") and
            structure_nodes[node_id].get("modality") == "should" and
            structure_nodes[node_id].get("paragraph") != "figure:diagram"
            for node_id in figure_provision_ids) and
        any(row["source_unit_code"].startswith("TA-")
            for row in graph.get("normative_provisions", [])) and
        graph_policy.get("query_independent") is True and
        graph_policy.get("scene_manifest_read") is False and
        graph_policy.get("hidden_reference_read") is False and
        graph_policy.get("benchmark_requirement_ids_present") is False,
        {"graph": record(graph_path), "statistics": graph.get("statistics"),
         "build_policy": graph_policy, "ta_count": len(graph_tas),
         "figure_guidance_provision_count": len(figure_provision_ids),
         "unknown_provision_count": len(graph_provisions - structure_node_ids)})
    gap_retrieval = cfg.get("stage1c_gap_retrieval", {"method": "bm25"})
    if gap_retrieval.get("method") == "dense_e5":
        dense_index_path = ROOT / gap_retrieval["index"]
        dense_manifest_path = ROOT / gap_retrieval["manifest"]
        dense = DenseGapIndex(
            dense_index_path, dense_manifest_path, retrieval.index_path, graph_path
        )
        dense_policy = dense.manifest.get("build_policy", {})
        dense_ranked = dense.rank("channelization_system", list(graph_provisions))
        add(checks, "dense Stage 1C index is source-bound and label-blind",
            len(dense.provision_ids) == len(graph_provisions) and
            dense_policy.get("scene_manifest_read") is False and
            dense_policy.get("hidden_reference_read") is False and
            dense_policy.get("outcome_labels_read") is False and
            len(dense_ranked) == len(graph_provisions),
            {"model_id": dense.manifest.get("model_id"),
             "provision_count": len(dense.provision_ids),
             "build_policy": dense_policy})
    manifest = gateway.scene.manifest()
    add(checks, "deployment facts are consistent with this scene's accepted inventory",
        deployment_inventory_consistent(manifest),
        {"accepted_arrow_board": manifest["counts"]["accepted_arrow_board_observations"],
         "arrow_board_provenance": manifest["derived_scene_facts"]["arrow_board_deployed_provenance"],
         "accepted_pcms": manifest["counts"]["accepted_pcms_observations"]})
    if scene.get("scene_id") == "scene-CATS-01":
        add(checks, "reference-case spacing result remains unchanged",
            spacing.get("clear_exceedance_gap_count") == 0 and spacing.get("violation_run_count") == 0 and
            spacing.get("deficiency_supported") is False,
            {k: spacing.get(k) for k in ("clear_exceedance_gap_count", "violation_run_count",
                                          "deficiency_supported")})
    if cfg.get("execution", {}).get("stop_before_measurement") is True:
        runner_source = (ROOT / "scripts/run_srag_bm25_v5.py").read_text()
        add(checks, "requirement-review mode stops immediately after Stage 3",
            'call["name"] == "seal_data_availability"' in runner_source and
            '"stopped_before_measurement": True' in runner_source and
            "requirement_review_plan(record)" in runner_source,
            {"stop_before_measurement": True,
             "pause_trigger": "successful seal_data_availability transition",
             "measurement_tools_exposed_before_pause": False})
    if cfg.get("execution", {}).get("stop_after_measurements") is True:
        runner_source = (ROOT / "scripts/run_srag_bm25_v5.py").read_text()
        add(checks, "Stage 4 isolation stops after evidence and measurements are sealed",
            'call["name"] == "seal_measurements"' in runner_source and
            '"stopped_after_measurements": True' in runner_source and
            "no Stage 5 call is permitted" in runner_source,
            {"stop_after_measurements": True,
             "pause_trigger": "successful seal_measurements transition"})
    if cfg.get("execution", {}).get("stop_after_conclusions") is True:
        runner_source = (ROOT / "scripts/run_srag_bm25_v5.py").read_text()
        add(checks, "Stage 5 isolation persists and seals conclusions before Stage 6",
            'call["name"] == "seal_conclusions"' in runner_source and
            '"stopped_after_conclusions": True' in runner_source and
            "no Stage 6 call is permitted" in runner_source,
            {"stop_after_conclusions": True,
             "pause_trigger": "successful seal_conclusions transition"})
    if cfg.get("execution", {}).get("stop_after_requirement_registration") is True:
        scoped_view = {"scene_id": scene["scene_id"], "scene_facts": dict(scene["scene_facts"])}
        simplified = cfg.get("execution", {}).get("simplified_inspection_checks") is True
        generic_ta_code = min(
            (code for code in retrieval.unit_by_code if re.fullmatch(r"TA-[1-9][0-9]?", code)),
            key=lambda code: int(code.split("-")[1]),
        )
        selected = [{
            "layout_code": generic_ta_code, "layout_role": "primary_applicable"
        }]
        scoped_prompt = (simplified_stage1_stage2_prompt(
                             scoped_view, selected, gap_retrieval
                         )
                         if simplified else stage1_stage2_scoped_prompt(scoped_view, selected))
        runner_source = (ROOT / "scripts/run_srag_bm25_v5.py").read_text()
        add(checks, "isolated Stage 1-2 mode stops after registration without perception leakage",
            cfg.get("execution", {}).get("scoped_stage1_stage2_test") is True and
            'call["name"] == "seal_requirement_registration"' in runner_source and
            '"stopped_after_requirement_registration": True' in runner_source and
            "accepted_bbox_observations" not in scoped_prompt and
            "confirmed_device_condition_findings" not in scoped_prompt and
            "scene_data_manifest" not in scoped_prompt and
            scoped_view["scene_facts"] == scene["scene_facts"],
            {"stop_after_requirement_registration": True,
             "coverage_domains": list(REGIONS),
             "pcms_fact_exposed": scoped_view["scene_facts"].get("pcms_deployed"),
             "arrow_board_fact_exposed": scoped_view["scene_facts"].get("arrow_board_deployed"),
             "bbox_inventory_exposed": False})
        scoped_gateway = ToolGatewayV5(selected, scoped_view, scoped_stage1_stage2=True,
                                       simplified_inspection_checks=simplified,
                                       gap_retrieval=gap_retrieval,
                                       scene_manifest=scene_path)
        scoped_names = {row["name"] for row in scoped_gateway.available_definitions()}
        early_registration = scoped_gateway.call("begin_requirement_registration", {})
        architecture = gap_retrieval.get("architecture", "kg_plus_retrieval")
        stage2_policy = cfg.get("stage2_policy", {})
        expected_stage2_mode = (
            "free_form_atomic_registration_v1"
            if architecture == "retrieval_only"
            else "structured_candidate_decision_v1"
        )
        discovery_contract_ok = (
            (
                architecture == "kg_only" and
                "load_ta_core_graph" in scoped_names and
                "load_scene_condition_graph" in scoped_names and
                "load_domain_gap_candidates" not in scoped_names
            ) or (
                architecture == "retrieval_only" and
                "load_ta_core_graph" not in scoped_names and
                "load_scene_condition_graph" not in scoped_names and
                "load_domain_gap_candidates" in scoped_names
            ) or (
                architecture == "kg_plus_retrieval" and
                "load_ta_core_graph" in scoped_names and
                "load_scene_condition_graph" in scoped_names and
                "load_domain_gap_candidates" in scoped_names
            )
            if simplified else
            ("record_domain_discovery" in scoped_names and "audit_graph_gaps" in scoped_names)
        )
        add(checks, "configured Stage 1 architecture and program-grounded registration are enforced",
            discovery_contract_ok and
            "search_manual_for_need" not in scoped_names and
            "search_manual" not in scoped_names and
            "submit_requirement_batch" not in scoped_names and
            early_registration.get("status") == "failure" and
            (("simplified discovery requires" in early_registration.get("failure_reason", "") or
              "retrieval is incomplete" in early_registration.get("failure_reason", ""))
             if simplified else
             ("ledger is incomplete" in early_registration.get("failure_reason", ""))) and
            ("submit_inspection_check_batch" if simplified else
             "submit_atomic_requirement_batch") in
            {row["name"] for row in scoped_discovery_registration_definitions()},
            {"architecture": architecture, "discovery_tools": sorted(scoped_names),
             "early_registration_result": early_registration})
        if cfg.get("method_definition_version") is not None:
            add(checks, "frozen method role uses the architecture-compatible Stage 2 policy",
                cfg.get("method_definition_version") == "stage1_stage2_methods_v1" and
                stage2_policy.get("mode") == expected_stage2_mode and
                ((architecture == "retrieval_only" and
                  stage2_policy.get("primary_comparison_scope") == "stage1_retrieval_only") or
                 (architecture != "retrieval_only" and
                  stage2_policy.get("canonical_predicate_binding") is True and
                  stage2_policy.get("explicit_candidate_disposition_required") is True)),
                {"method_role": cfg.get("method_role"), "architecture": architecture,
                 "expected_stage2_mode": expected_stage2_mode,
                 "configured_stage2_policy": stage2_policy})

    resume_paths = {
        name: Path(cfg.get("execution", {}).get(name, ""))
        for name in ("resume_stage0_record", "resume_registry_checkpoint", "resume_tool_trace")
        if cfg.get("execution", {}).get(name)
    }
    if "resume_registry_checkpoint" in resume_paths or "resume_tool_trace" in resume_paths:
        if not {"resume_registry_checkpoint", "resume_tool_trace"} <= set(resume_paths):
            add(checks, "resume registry inputs are supplied as a complete pair", False,
                {name: str(path) for name, path in resume_paths.items()})
        else:
            resume_snapshot = json.loads(resume_paths["resume_registry_checkpoint"].read_text())
            resume_trace_rows = json.loads(resume_paths["resume_tool_trace"].read_text())
            restored = ToolGatewayV5.from_checkpoint(
                resume_snapshot.get("selected_layouts", []), view, resume_snapshot, resume_trace_rows,
                scoped_stage1_stage2=cfg.get("execution", {}).get("scoped_stage1_stage2_test") is True,
                simplified_inspection_checks=cfg.get("execution", {}).get("simplified_inspection_checks") is True,
                orchestrated_stage4=cfg.get("execution", {}).get("orchestrated_stage4") is True,
                orchestrated_stage5=cfg.get("execution", {}).get("orchestrated_stage5") is True,
                gap_retrieval=cfg.get("stage1c_gap_retrieval", {"method": "bm25"}),
                scene_manifest=scene_path,
            )
            configured_resume_phase = cfg.get("execution", {}).get("resume_expected_phase")
            if configured_resume_phase is not None:
                if configured_resume_phase not in {
                    "requirement_registration", "data_availability", "measurement",
                    "inspection_conclusion", "result_submission", "finalized",
                }:
                    raise ValueError(
                        f"unsupported resume_expected_phase: {configured_resume_phase}"
                    )
                expected_resume_phase = configured_resume_phase
            elif cfg.get("execution", {}).get("stop_after_conclusions") is True:
                expected_resume_phase = "inspection_conclusion"
            elif cfg.get("execution", {}).get("stop_after_measurements") is True:
                expected_resume_phase = "measurement"
            elif cfg.get("execution", {}).get("stop_before_measurement") is True:
                expected_resume_phase = "data_availability"
            else:
                expected_resume_phase = "requirement_registration"
            expected_measurements = expected_resume_phase in {
                "inspection_conclusion", "result_submission", "finalized",
            }
            add(checks, "resume checkpoint is at the authorized phase boundary",
                all(path.exists() for path in resume_paths.values()) and
                restored.registry.phase == expected_resume_phase and
                len(restored.registry.requirements) > 0 and
                resume_measurement_boundary_valid(restored, expected_measurements) and
                not validate_trace_measurement_order(resume_trace_rows),
                {"phase": restored.registry.phase, "expected_phase": expected_resume_phase,
                 "registered_requirements": len(restored.registry.requirements),
                 "measurement_count": len(restored.scene.measurements)})
            if (cfg.get("execution", {}).get("orchestrated_stage4") is True and
                    expected_resume_phase == "measurement"):
                stage4_names = {row["name"] for row in restored.available_definitions()}
                stage4_contract = phase_contract(
                    "measurement", False, False, True, True, True, True,
                )
                orchestrated_stage4_names = {
                    "get_stage4_acquisition_plan", "inspect_stage4_visual_job",
                    "record_visual_job_note", "record_visual_finding_batch",
                    "run_registered_measurement", "record_measurement_finding_batch",
                    "get_stage4_readiness", "seal_measurements",
                }
                add(checks, "orchestrated Stage 4 exposes only plan-bound typed tools",
                    len(stage4_names) == 1 and
                    stage4_names <= orchestrated_stage4_names and
                    "Never invent source IDs" in stage4_contract,
                    {"available_tools": sorted(stage4_names)})
            if (cfg.get("execution", {}).get("orchestrated_stage5") is True and
                    expected_resume_phase == "inspection_conclusion"):
                stage5_names = {row["name"] for row in restored.available_definitions()}
                stage5_contract = phase_contract(
                    "inspection_conclusion", False, False, True, True,
                    False, True, True, True,
                )
                add(checks, "orchestrated Stage 5 exposes only the conclusion plan",
                    stage5_names == {"get_stage5_conclusion_plan"} and
                    "Mandatory" in stage5_contract and "unresolved" in stage5_contract,
                    {"available_tools": sorted(stage5_names)})
    if "resume_stage0_record" in resume_paths:
        stage0_record = json.loads(resume_paths["resume_stage0_record"].read_text())
        primary_codes = [row.get("layout_code") for row in stage0_record.get("selected_layouts", [])
                         if row.get("layout_role") == "primary_applicable"]
        add(checks, "resumed Stage 0 record supplies exactly one valid primary TA",
            stage0_record.get("layout_selection_status") == "determined" and
            len(primary_codes) == 1 and
            re.fullmatch(r"TA-(?:[1-9]|[1-4][0-9]|5[0-4])", str(primary_codes[0])) is not None,
            {"primary_codes": primary_codes})

    frozen: dict[str, dict] = {
        "config": record(config_path), "scene_manifest": record(scene_path),
        "public_scene_manifest": record(ROOT / cfg["public_scene_manifest"]),
        "manual_structure": record(ROOT / cfg["manual_structure_index"]),
        "reference": record(ROOT / cfg["frozen_autonomous_reference"]),
        "normative_manual_pdf": record(Path(gateway.scene.cfg["source"]["manual_pdf"])),
        "credential_identity": record(credential_path),
        "manual_structure_manifest": record(structure_manifest_path),
        "manual_structure_validation": record(structure_validation_path),
    }
    for index, row in enumerate(figure_assets):
        frozen[f"manual_figure_asset_{index:02d}"] = record(Path(row["path"]))
    for index, path_text in enumerate(scene["raw_images"]):
        frozen[f"raw_image_{index:02d}"] = record(Path(path_text))
    for index, name in enumerate(("reviewed_bboxes", "expert_evidence_confirmations", "user_adjudications")):
        frozen[f"bbox_source_{index}"] = record(scene_source_path(scene, gateway.scene.cfg["source"], name))
    for name, path in resume_paths.items():
        frozen[name] = record(path)
    if gap_retrieval.get("method") == "dense_e5":
        frozen["dense_gap_index"] = record(ROOT / gap_retrieval["index"])
        frozen["dense_gap_index_manifest"] = record(ROOT / gap_retrieval["manifest"])
    implementation_paths = [ROOT / "scripts" / name for name in (
        "inspection_registry_v5.py", "scene_data_tools_v5.py", "srag_bm25_tools_v5.py",
        "srag_bm25_retrieval_v5.py", "run_srag_bm25_v5.py", "preflight_srag_bm25_v5.py",
        "test_srag_bm25_v5.py", "materialize_current_scene.py", "api_client.py",
        "mutcd_knowledge_graph_v2.py", "dense_gap_retrieval.py",
    )]
    report = {
        "schema": "srag_bm25_v5_stage_order_preflight_v1", "config_path": str(config_path),
        "passed": all(row["passed"] for row in checks), "checks": checks,
        "frozen_inputs": frozen,
        "implementation_sha256": {str(path): sha256(path) for path in implementation_paths},
        "tool_schema_sha256": schema_fingerprint(),
        "reference_notice": cfg["reporting"]["reference_status"],
    }
    out = ROOT / cfg["execution"]["preflight_report"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "checks": len(checks), "output": str(out)}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
