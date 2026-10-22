#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from inspection_registry_v5 import InspectionRegistry, RegistryError, REGIONS
from project_common import ROOT
from run_srag_bm25_v5 import (
    _workflow_state_packet, phase_contract, public_scene_input, requirement_review_plan,
    simplified_stage1_stage2_prompt, stage0_prompt, stage0_schema, stage1_stage2_scoped_prompt,
    validate_stage0_selection, workflow_prompt,
)
from scene_data_tools_v5 import SceneDataToolsV5
from srag_bm25_retrieval_v5 import StructuredBM25V5
from mutcd_knowledge_graph_v2 import DOMAIN_GAP_QUERIES
from srag_bm25_tools_v5 import (
    ToolGatewayV5, _project_scope_exclusion, scene_tool_definitions,
    validate_trace_measurement_order,
)


def scene_view() -> dict:
    scene = json.loads((ROOT / "cases/workzone_01/scene.json").read_text())
    tools = SceneDataToolsV5()
    return public_scene_input(scene, tools.manifest())


def complete_gap_audit(gateway: ToolGatewayV5, domain: str, page_size: int = 12) -> list[dict]:
    pages = []
    token = None
    while True:
        page = gateway.call("audit_graph_gaps", {
            "domain": domain, "page_size": page_size,
            "continuation_token": token,
        })
        pages.append(page)
        if not page.get("has_more"):
            return pages
        token = page["continuation_token"]


def setup_spacing_gateway() -> tuple[ToolGatewayV5, str]:
    gateway = ToolGatewayV5([], scene_view())
    expanded = gateway.call("expand_source_unit", {
        "source_unit_code": "SEC-6K.01", "region": "channelizing_devices",
        "page_size": 12, "continuation_token": None,
    })
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
    key = registered["accepted_requirement_keys"][0]
    gateway.call("complete_region_batch", {"regions": [
        {"region": region, "status": "screened", "reason": "screened in test"} for region in REGIONS
    ]})
    gateway.call("seal_requirement_registration", {})
    gateway.call("submit_data_availability_batch", {"assessments": [{
        "discovered_requirement_key": key, "condition_data_complete": True,
        "available_inputs": ["posted_speed_mph", "spacing_measurement"], "missing_inputs": [],
        "data_availability": "available_direct", "basis_evidence_ids": ["scene_facts"],
        "reason": "Frozen speed and accepted geometry are available.",
        "planned_tools": ["audit_channelizer_spacing"],
        "planned_evidence_strategy": "Measure the full accepted channelizer line.",
        "planned_decision_rule": "Only a sustained confidence-bounded exceedance supports deficiency.",
    }]})
    gateway.call("seal_data_availability", {})
    return gateway, key


def setup_availability_gateway() -> tuple[ToolGatewayV5, str]:
    gateway = ToolGatewayV5([], scene_view())
    expanded = gateway.call("expand_source_unit", {
        "source_unit_code": "TA-30", "region": "applicability",
        "page_size": 12, "continuation_token": None,
    })
    node = expanded["items"][0]
    gateway.call("begin_requirement_registration", {})
    registered = gateway.call("submit_requirement_batch", {
        "region": "lane_closure_layout",
        "requirements": [{
            "candidate_label": "stage3-test", "subject": node["subject"],
            "modality": node["modality"], "relation": node["relation"],
            "threshold": node["threshold"],
            "applicability_conditions": node["applicability_conditions"],
            "required_inputs": ["raw_images"],
            "source_node_ids": [node["source_node_id"]],
            "source_locator": node["source_locator"], "source_span": node["source_span"],
            "measurement_spec": {"required": False, "tool": None,
                                 "quantity": None, "thresholds": []},
        }],
    })
    gateway.call("complete_region_batch", {"regions": [
        {"region": region, "status": "screened", "reason": "screened in test"}
        for region in REGIONS
    ]})
    gateway.call("seal_requirement_registration", {})
    return gateway, registered["accepted_requirement_keys"][0]


def setup_orchestrated_stage4_gateway() -> ToolGatewayV5:
    root = ROOT / "artifacts/workzone_01/pipeline/stage3/scene-CATS-01"
    snapshot = json.loads((root / "stage_1_to_6_registry.json").read_text())
    trace = json.loads((root / "tool_trace.json").read_text())
    return ToolGatewayV5.from_checkpoint(
        snapshot["selected_layouts"], scene_view(), snapshot, trace,
        scoped_stage1_stage2=True, simplified_inspection_checks=True,
        orchestrated_stage4=True,
    )


class SragBM25V5Tests(unittest.TestCase):
    @staticmethod
    def _stage0_record(code: str = "TA-30", status: str = "determined") -> dict:
        return {
            "scene_id": "scene-CATS-01", "layout_selection_status": status,
            "selected_layouts": [{
                "layout_code": code,
                "layout_role": "primary_applicable" if status == "determined" else "cross_reference_only",
                "source_locator": "manual locator", "matched_scene_facts": [],
                "conflicting_scene_facts": [],
            }],
            "missing_scene_fields": [], "selection_reason": "test",
        }

    def test_stage0_schema_enumerates_exactly_the_54_mutcd_typical_applications(self):
        layout_code = stage0_schema()["properties"]["selected_layouts"]["items"]["properties"]["layout_code"]
        self.assertEqual(layout_code["enum"], [f"TA-{number}" for number in range(1, 55)])

    def test_stage0_program_validation_accepts_valid_manual_index_layout(self):
        validate_stage0_selection(self._stage0_record(), {f"TA-{number}" for number in range(1, 55)})

    def test_stage0_program_validation_rejects_out_of_range_and_noncanonical_codes(self):
        for code in ("TA-0", "TA-55", "TA30", "6P-30"):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, "TA-1 through TA-54"):
                validate_stage0_selection(self._stage0_record(code))

    def test_stage0_program_validation_rejects_multiple_primary_layouts(self):
        record = self._stage0_record()
        record["selected_layouts"].append({**record["selected_layouts"][0], "layout_code": "TA-31"})
        with self.assertRaisesRegex(ValueError, "exactly one primary_applicable"):
            validate_stage0_selection(record)

    def test_stage0_program_validation_rejects_layout_absent_from_index(self):
        with self.assertRaisesRegex(ValueError, "absent from the manual index"):
            validate_stage0_selection(self._stage0_record(), {"TA-1", "TA-2"})

    def test_data_availability_batch_is_atomic(self):
        registry = InspectionRegistry("scene", [])
        registry.begin_requirement_registration()
        base = {
            "modality": "shall", "relation": "complies", "threshold": "visible",
            "applicability_conditions": [], "source_node_ids": ["src_manual"],
            "source_locator": "manual-visible locator", "source_span": "manual-visible span",
            "measurement_spec": {"required": False, "tool": None, "quantity": None, "thresholds": []},
        }
        accepted = registry.submit_requirement_batch("advance_warning_sign_system", [
            {**base, "candidate_label": "first", "subject": "first sign", "required_inputs": ["raw_images"]},
            {**base, "candidate_label": "second", "subject": "second sign", "required_inputs": ["raw_images", "closed_lane"]},
        ])["accepted_requirement_keys"]
        registry.complete_region_batch([{"region": region, "status": "screened", "reason": "test"}
                                        for region in REGIONS])
        registry.seal_requirement_registration()
        common = {
            "condition_data_complete": True, "data_availability": "available_direct",
            "basis_evidence_ids": ["scene_facts"], "reason": "test", "planned_tools": [],
            "planned_evidence_strategy": "Inspect accepted evidence.",
            "planned_decision_rule": "Conclude only from supporting evidence.",
        }
        with self.assertRaisesRegex(RegistryError, "exactly partition"):
            registry.submit_data_availability_batch([
                {**common, "discovered_requirement_key": accepted[0],
                 "available_inputs": ["raw_images"], "missing_inputs": []},
                {**common, "discovered_requirement_key": accepted[1],
                 "available_inputs": ["raw_images"], "missing_inputs": []},
            ])
        self.assertEqual(registry.data_availability, {})

    def test_stage3_availability_is_an_exact_partition_and_not_a_final_attempt_state(self):
        gateway, key = setup_availability_gateway()
        base = {
            "discovered_requirement_key": key,
            "condition_data_complete": True,
            "basis_evidence_ids": ["scene_facts"],
            "reason": "test",
            "planned_tools": [],
            "planned_evidence_strategy": "Inspect the registered scene evidence.",
            "planned_decision_rule": "Decide only after the required input is acquired.",
        }
        rejected = gateway.call("submit_data_availability_batch", {"assessments": [{
            **base,
            "available_inputs": [],
            "missing_inputs": ["raw_images", "unexpected"],
            "data_availability": "not_attempted",
        }]})
        self.assertEqual(rejected["status"], "failure")
        self.assertIn("exactly partition", rejected["failure_reason"])
        rejected = gateway.call("submit_data_availability_batch", {"assessments": [{
            **base,
            "available_inputs": [],
            "missing_inputs": ["raw_images"],
            "data_availability": "unavailable_after_attempt",
        }]})
        self.assertEqual(rejected["status"], "failure")
        self.assertIn("Stage 4 final state", rejected["failure_reason"])

    def test_stage3_plan_covers_each_known_missing_input_tool_family(self):
        gateway, key = setup_availability_gateway()
        requirement = gateway.registry.requirements[key]
        requirement["required_inputs"] = ["Measured taper length", "Lane-reduction width or offset"]
        requirement["measurement_spec"] = {
            "required": True, "tool": "measure_taper_length",
            "quantity": "taper length", "thresholds": [],
        }
        rejected = gateway.call("submit_data_availability_batch", {"assessments": [{
            "discovered_requirement_key": key,
            "condition_data_complete": True,
            "available_inputs": [],
            "missing_inputs": ["Measured taper length", "Lane-reduction width or offset"],
            "data_availability": "not_attempted",
            "basis_evidence_ids": ["scene_facts"],
            "reason": "Geometry has not been acquired.",
            "planned_tools": ["measure_taper_length"],
            "planned_evidence_strategy": "Measure the taper and lateral offset.",
            "planned_decision_rule": "Apply the registered threshold after measurement.",
        }]})
        self.assertEqual(rejected["status"], "failure")
        self.assertIn("Lane-reduction width or offset", rejected["failure_reason"])

    def test_scene_manifest_inventory_tool_matches_public_schema_name(self):
        gateway, _ = setup_availability_gateway()
        result = gateway.call("get_scene_data_manifest", {})
        self.assertEqual(result["scene_id"], "scene-CATS-01")
        self.assertIn("derivable_local", result)
        self.assertGreater(result["counts"]["accepted_bbox_observations_by_class"]["channelizing_device"], 0)

    def test_requirement_review_plan_keeps_planned_stage4_acquisition(self):
        gateway, key = setup_availability_gateway()
        gateway.call("submit_data_availability_batch", {"assessments": [{
            "discovered_requirement_key": key,
            "condition_data_complete": False,
            "available_inputs": [],
            "missing_inputs": ["raw_images"],
            "data_availability": "not_attempted",
            "basis_evidence_ids": ["manifest:derivable_local:full_temporal_images"],
            "reason": "Raw imagery can be inspected in Stage 4.",
            "planned_tools": ["inspect_temporal_images"],
            "planned_evidence_strategy": "Inspect temporal images for the required observation.",
            "planned_decision_rule": "Decide only when the required observation is visible.",
        }]})
        plan = requirement_review_plan(gateway.registry.snapshot())
        self.assertEqual(plan["planned_inspection_count"], 1)
        self.assertTrue(plan["requirements"][0]["planned_for_inspection_after_review"])

    def test_reviewed_observation_inventory_filters_and_deduplicates_entities(self):
        tools = SceneDataToolsV5()
        result = tools.get_reviewed_observations(
            cursor=0, limit=100, reviewed_class="traffic_sign", representative_per_entity=True
        )
        self.assertEqual(result["reviewed_class_filter"], "traffic_sign")
        self.assertEqual(result["total"], 23)
        entities = [row.get("refined_element_id") for row in result["observations"]]
        self.assertEqual(len(entities), len(set(entities)))

    def test_stage4_visual_evidence_is_persistent_and_sealable(self):
        gateway, key = setup_availability_gateway()
        gateway.call("submit_data_availability_batch", {"assessments": [{
            "discovered_requirement_key": key, "condition_data_complete": True,
            "available_inputs": [], "missing_inputs": ["raw_images"],
            "data_availability": "not_attempted", "basis_evidence_ids": ["scene_data_manifest"],
            "reason": "Image inspection is pending.",
            "planned_tools": ["inspect_observation_images"],
            "planned_evidence_strategy": "Inspect one accepted candidate image.",
            "planned_decision_rule": "Use only a visible factual observation.",
        }]})
        gateway.call("seal_data_availability", {})
        inventory = gateway.call("get_reviewed_observations", {
            "cursor": 0, "limit": 1, "reviewed_class": "arrow_board",
            "representative_per_entity": True,
        })
        observation_id = inventory["observations"][0]["observation_id"]
        gateway.call("inspect_observation_images", {"observation_ids": [observation_id]})
        recorded = gateway.call("record_evidence_batch", {"evidence": [{
            "discovered_requirement_key": key, "evidence_kind": "visual_observation",
            "source_ids": [observation_id], "acquired_inputs": ["raw_images"],
            "unresolved_inputs": [], "finding": "The inspected source image is readable.",
            "limitations": "This test records no compliance conclusion.",
            "tools_used": ["inspect_observation_images"],
        }]})
        self.assertEqual(len(recorded["accepted_evidence_ids"]), 1)
        sealed = gateway.call("seal_measurements", {})
        self.assertEqual(sealed["phase"], "inspection_conclusion")
        restored = ToolGatewayV5.from_checkpoint([], scene_view(), gateway.registry.snapshot(), gateway.trace)
        self.assertEqual(len(restored.registry.evidence_records), 1)

    def test_stage4_rejects_visual_source_that_was_not_inspected(self):
        gateway, key = setup_availability_gateway()
        gateway.call("submit_data_availability_batch", {"assessments": [{
            "discovered_requirement_key": key, "condition_data_complete": True,
            "available_inputs": [], "missing_inputs": ["raw_images"],
            "data_availability": "not_attempted", "basis_evidence_ids": ["scene_data_manifest"],
            "reason": "Image inspection is pending.", "planned_tools": ["inspect_observation_images"],
            "planned_evidence_strategy": "Inspect an accepted image.",
            "planned_decision_rule": "Use only inspected evidence.",
        }]})
        gateway.call("seal_data_availability", {})
        inventory = gateway.call("get_reviewed_observations", {
            "cursor": 0, "limit": 1, "reviewed_class": "arrow_board",
            "representative_per_entity": True,
        })
        gateway.call("inspect_observation_images", {
            "observation_ids": [inventory["observations"][0]["observation_id"]]
        })
        rejected = gateway.call("record_evidence_batch", {"evidence": [{
            "discovered_requirement_key": key, "evidence_kind": "visual_observation",
            "source_ids": ["not_inspected"], "acquired_inputs": ["raw_images"],
            "unresolved_inputs": [], "finding": "Unsupported finding.", "limitations": "none",
            "tools_used": ["inspect_observation_images"],
        }]})
        self.assertEqual(rejected["status"], "failure")
        self.assertIn("not inspected", rejected["failure_reason"])

    def test_stage4_contract_has_persistent_evidence_and_pause_boundary(self):
        contract = phase_contract(
            "measurement", False, False, True, True, stop_after_measurements=True
        )
        self.assertIn("record_evidence_batch", contract)
        self.assertIn("no Stage 5 call is permitted", contract)

    def test_orchestrated_stage4_plan_tools_provenance_and_readiness_close_without_retries(self):
        gateway = setup_orchestrated_stage4_gateway()
        names = {row["name"] for row in gateway.available_definitions()}
        self.assertEqual(names, {"get_stage4_acquisition_plan"})
        self.assertFalse(names & {
            "get_reviewed_observations", "inspect_observation_images",
            "measure_taper_length", "estimate_available_width", "record_evidence_batch",
        })
        plan = gateway.call("get_stage4_acquisition_plan", {})
        self.assertEqual(len(plan["visual_jobs"]), 4)
        expected_measurement_keys = {
            key for key, requirement in gateway.registry.requirements.items()
            if requirement.get("measurement_spec", {}).get("required") is True
        }
        self.assertEqual(
            {row["discovered_requirement_key"] for row in plan["measurement_jobs"]},
            expected_measurement_keys,
        )
        self.assertGreaterEqual(len(plan["blocked_attempts"]), 1)
        self.assertGreaterEqual(len(gateway.registry.evidence_records), 1)
        confirmed_condition_evidence = [
            row for row in gateway.registry.evidence_records.values()
            if "User/domain-reviewer confirmed device-condition findings" in row.get("finding", "")
        ]
        self.assertGreaterEqual(len(confirmed_condition_evidence), 1)
        self.assertTrue(all(
            set(row["source_ids"])
            == {"F0616_CAM_FRONT_LEFT_000", "F0622_CAM_BACK_LEFT_000"}
            for row in confirmed_condition_evidence
        ))
        first_job = plan["visual_jobs"][0]
        first = gateway.call("inspect_stage4_visual_job", {
            "visual_job_id": first_job["visual_job_id"],
        })
        self.assertEqual(first["status"], "acquired")
        note_schema = next(
            row for row in gateway.available_definitions()
            if row["name"] == "record_visual_job_note"
        )
        self.assertEqual(
            note_schema["parameters"]["properties"]["visual_job_id"]["enum"],
            [first_job["visual_job_id"]],
        )
        gateway.call("record_visual_job_note", {
            "visual_job_id": first_job["visual_job_id"],
            "finding": "Typed visual-job note.",
            "limitations": "No compliance conclusion.",
        })
        for job in plan["visual_jobs"][1:]:
            result = gateway.call("inspect_stage4_visual_job", {
                "visual_job_id": job["visual_job_id"],
            })
            self.assertEqual(result["status"], "acquired")
            gateway.call("record_visual_job_note", {
                "visual_job_id": job["visual_job_id"],
                "finding": "Typed visual-job note.",
                "limitations": "No compliance conclusion.",
            })
        self.assertEqual(len(gateway.registry.inspection_bundles), 4)
        self.assertNotIn(
            "inspect_stage4_visual_job",
            {row["name"] for row in gateway.available_definitions()},
        )

        visual_inputs: dict[str, set[str]] = {}
        for job in plan["visual_jobs"]:
            for key, inputs in job["target_inputs_by_requirement"].items():
                visual_inputs.setdefault(key, set()).update(inputs)
        findings = [{
                "discovered_requirement_key": key,
                "acquired_inputs": sorted(inputs),
                "finding": "Typed Stage 4 test observation.",
                "limitations": "No compliance conclusion.",
            } for key, inputs in visual_inputs.items()]
        for start in range(0, len(findings), 12):
            visual_record = gateway.call(
                "record_visual_finding_batch",
                {"findings": findings[start:start + 12]},
            )
            self.assertNotEqual(visual_record.get("status"), "failure")

        device_bundle = next(
            row for row in gateway.registry.inspection_bundles.values()
            if row["role"] == "device_representatives"
        )
        sign_bundles = [
            row for row in gateway.registry.inspection_bundles.values()
            if row["role"] == "traffic_sign_representatives"
        ]
        measurement_findings = []
        for job in plan["measurement_jobs"]:
            arguments = {
                "measurement_job_id": job["measurement_job_id"],
                "start_observation_id": None, "end_observation_id": None,
                "observation_ids": [],
            }
            if job["tool"] == "measure_taper_length":
                arguments["start_observation_id"], arguments["end_observation_id"] = (
                    device_bundle["source_ids"][-2:]
                )
            elif job["tool"] == "measure_sign_spacing":
                arguments["start_observation_id"] = sign_bundles[0]["source_ids"][0]
                arguments["end_observation_id"] = sign_bundles[-1]["source_ids"][-1]
            measured = gateway.call("run_registered_measurement", arguments)
            self.assertEqual(measured["status"], "acquired")
            self.assertIn(
                measured["measurement_quality_status"],
                {"usable", "quality_rejected", "failed"},
            )
            measurement_findings.append({
                "measurement_job_id": job["measurement_job_id"],
                "finding": "Typed Stage 4 measurement outcome.",
                "limitations": "Quality status is program-derived.",
            })
        measurement_record = gateway.call(
            "record_measurement_finding_batch", {"findings": measurement_findings}
        )
        self.assertNotEqual(measurement_record.get("status"), "failure")
        readiness = gateway.call("get_stage4_readiness", {})
        self.assertTrue(readiness["ready"])
        self.assertEqual(readiness["provenance_gaps"], [])
        sealed = gateway.call("seal_measurements", {})
        self.assertEqual(sealed["phase"], "inspection_conclusion")
        self.assertEqual(
            gateway.tool_failures - gateway.resume_tool_failure_count, 0
        )
        self.assertGreaterEqual(
            len(gateway.trace) - gateway.resume_trace_length,
            len(plan["visual_jobs"]) + len(plan["measurement_jobs"]),
        )
        restored = ToolGatewayV5.from_checkpoint(
            gateway.registry.selected_layouts, scene_view(), gateway.registry.snapshot(),
            gateway.trace, True, True, True,
        )
        self.assertEqual(len(restored.registry.inspection_bundles), 4)
        self.assertEqual(len(restored.scene.measurements), 2)

    def test_orchestrated_stage4_contract_delegates_provenance_to_program(self):
        contract = phase_contract(
            "measurement", False, False, True, True, True, True,
        )
        self.assertIn("Call the only currently exposed tool", contract)
        self.assertIn("record_visual_job_note", contract)
        self.assertIn("record_visual_finding_batch", contract)
        self.assertIn("Never invent source IDs", contract)

    def test_orchestrated_stage4_persists_unresolvable_formula_as_failed_attempt(self):
        gateway, key = setup_spacing_gateway()
        gateway.orchestrated_stage4 = True
        for threshold in gateway.registry.requirements[key]["measurement_spec"]["thresholds"]:
            threshold["formula_parameter"] = "missing_scene_parameter"
        plan = gateway.call("get_stage4_acquisition_plan", {})
        job = plan["measurement_jobs"][0]
        measured = gateway._run_registered_measurement({
            "measurement_job_id": job["measurement_job_id"],
            "start_observation_id": None,
            "end_observation_id": None,
            "observation_ids": [],
        })
        self.assertEqual(measured["status"], "acquired")
        self.assertEqual(measured["measurement_quality_status"], "failed")
        self.assertIn("missing_scene_parameter", measured["failure_reason"])
        attempt = gateway.registry.acquisition_attempts[measured["attempt_id"]]
        self.assertEqual(attempt["status"], "failed")
        self.assertEqual(attempt["source_ids"], [])

    def test_stage4_rejects_endpoint_measurement_with_large_lateral_residual(self):
        measurement = {
            "status": "acquired",
            "measurement_id": "measurement_test",
            "measurement_type": "taper_length",
            "endpoint_semantics_valid": True,
            "geometry_direction_valid": True,
            "threshold_assessment": {"status": "no_clear_violation"},
            "quality_flags": ["large_trajectory_lateral_residual"],
        }
        self.assertFalse(ToolGatewayV5._measurement_is_usable(measurement))

    def test_orchestrated_stage5_persists_complete_modality_preserving_drafts(self):
        root = ROOT / "artifacts/workzone_01/pipeline/stage4/scene-CATS-01"
        snapshot = json.loads((root / "stage_1_to_6_registry.json").read_text())
        trace = json.loads((root / "tool_trace.json").read_text())
        gateway = ToolGatewayV5.from_checkpoint(
            snapshot.get("selected_layouts", []), scene_view(), snapshot, trace,
            True, True, True, True,
        )
        self.assertEqual(
            {row["name"] for row in gateway.available_definitions()},
            {"get_stage5_conclusion_plan"},
        )
        plan = gateway.call("get_stage5_conclusion_plan", {})
        self.assertEqual(
            {row["discovered_requirement_key"] for row in plan["conclusion_jobs"]},
            set(gateway.registry.requirements),
        )
        schema = gateway.available_definitions()[0]["parameters"]["properties"][
            "conclusions"
        ]
        self.assertEqual(schema["minItems"], 1)
        self.assertGreaterEqual(schema["maxItems"], 1)
        conclusions = []
        for job in plan["conclusion_jobs"]:
            label = job["candidate_label"]
            if label == "LC-03R" or job["unresolved_inputs"]:
                status = "not_assessed"
            elif job["confirmed_deficiency_evidence"]:
                status = "deficient"
            else:
                status = "satisfied"
                self.assertNotIn(
                    "not_assessed", job["allowed_inspection_statuses"],
                    "resolved Stage 5 jobs must receive a definitive decision",
                )
            conclusions.append({
                "discovered_requirement_key": job["discovered_requirement_key"],
                "normative_applicability": "false" if label == "LC-03R" else "true",
                "inspection_status": status,
                "inspection_reason": "Test conclusion grounded in the bound evidence ledger.",
            })
        batch_limit = schema["maxItems"]
        for start in range(0, len(conclusions), batch_limit):
            recorded = gateway.call(
                "record_stage5_conclusion_batch",
                {"conclusions": conclusions[start:start + batch_limit]},
            )
            self.assertNotEqual(recorded.get("status"), "failure")
        self.assertEqual(
            len(gateway.registry.conclusion_drafts),
            len(gateway.registry.requirements),
        )
        readiness = gateway.call("get_stage5_readiness", {})
        self.assertTrue(readiness["ready"])
        self.assertEqual(
            readiness["mandatory_count"] + readiness["guidance_count"],
            len(gateway.registry.requirements),
        )
        sealed = gateway.call("seal_conclusions", {})
        self.assertEqual(sealed["phase"], "result_submission")
        self.assertGreaterEqual(len(gateway.trace) - gateway.resume_trace_length, 4)
        self.assertEqual(gateway.tool_failures - gateway.resume_tool_failure_count, 0)
        frozen_drafts = json.loads(json.dumps(gateway.registry.conclusion_drafts))
        self.assertEqual(
            {row["name"] for row in gateway.available_definitions()},
            {"submit_next_stage6_batch"},
        )
        while True:
            copied = gateway.call("submit_next_stage6_batch", {})
            self.assertTrue(copied["copied_from_sealed_stage5_drafts"])
            if copied["remaining_result_count"] == 0:
                break
        self.assertEqual(copied["remaining_result_count"], 0)
        self.assertEqual(
            {row["name"] for row in gateway.available_definitions()},
            {"finalize_stage6"},
        )
        finalized = gateway.call("finalize_stage6", {})
        self.assertTrue(finalized["finalized"])
        for key, draft in frozen_drafts.items():
            submitted = gateway.registry.inspections[key]
            for field in (
                "normative_applicability", "acquisition_plan", "acquisition_attempts",
                "tools_called", "acquired_inputs", "derivation_evidence_ids",
                "external_evidence_ids", "unresolved_inputs", "final_data_availability",
                "failure_reason", "image_assessable", "inspection_status", "evidence_ids",
                "measurement_ids", "inspection_reason", "requires_human_review",
            ):
                self.assertEqual(submitted[field], draft[field])

    def test_phase_contract_and_resume_packet_expose_stage_inputs(self):
        gateway = ToolGatewayV5([], scene_view())
        expanded = gateway.call("expand_source_unit", {
            "source_unit_code": "TA-30", "region": "applicability",
            "page_size": 12, "continuation_token": None,
        })
        node = expanded["items"][0]
        gateway.call("begin_requirement_registration", {})
        registered = gateway.call("submit_requirement_batch", {"region": "lane_closure_layout", "requirements": [{
            "candidate_label": "stage-input-test", "subject": node["subject"],
            "modality": node["modality"], "relation": node["relation"], "threshold": node["threshold"],
            "applicability_conditions": node["applicability_conditions"], "required_inputs": ["raw_images"],
            "source_node_ids": [node["source_node_id"]], "source_locator": node["source_locator"],
            "source_span": node["source_span"],
            "measurement_spec": {"required": False, "tool": None, "quantity": None, "thresholds": []},
        }]})
        gateway.call("complete_region_batch", {"regions": [
            {"region": region, "status": "screened", "reason": "test"} for region in REGIONS
        ]})
        gateway.call("seal_requirement_registration", {})
        packet = _workflow_state_packet(scene_view(), [], gateway)
        key = registered["accepted_requirement_keys"][0]
        self.assertIn('"pending_data_availability_requirements"', packet)
        self.assertIn(key, packet)
        self.assertIn('"required_inputs":["raw_images"]', packet)
        contract = phase_contract("data_availability", True)
        self.assertIn("available_inputs", contract)
        self.assertIn("missing_inputs", contract)
        self.assertIn("STOP IMMEDIATELY", contract)

    def test_retrieval_compound_code_and_no_internal_id(self):
        result = StructuredBM25V5().search_manual("TA-30", 2)
        self.assertEqual(result["items"][0]["source_unit_code"], "TA-30")
        self.assertNotIn("requirement_id", json.dumps(result))

    def test_diagram_tables_are_first_class_retrieval_units(self):
        retrieval = StructuredBM25V5()
        queries = {
            "Table 6P-2 meanings of symbols used in Typical Application diagrams": "TABLE-6P-2",
            "Table 6B-1 letter codes A B C warning sign spacing": "TABLE-6B-1",
            "Table 6B-4 taper length formula": "TABLE-6B-4",
        }
        for query, expected in queries.items():
            with self.subTest(query=query):
                result = retrieval.search_manual(query, 1)
                self.assertEqual(result["items"][0]["source_unit_code"], expected)
                expanded = retrieval.expand_source_unit(expected, None, 12, None)
                self.assertEqual(expanded["matching_node_count"], 1)
                self.assertTrue(expanded["items"][0]["source_span"])

    def test_ta30_diagram_is_prestructured_before_queries(self):
        retrieval = StructuredBM25V5()
        nodes = retrieval.nodes_by_unit["TA-30"]
        components = {row["paragraph"] for row in nodes if row["node_type"] == "figure_component"}
        self.assertTrue({
            "figure:diagram", "figure:sign:W20-1", "figure:sign:W20-5L", "figure:sign:W4-2L",
            "figure:dimensions:A-B-C", "figure:dimension:L", "figure:buffer_space",
            "figure:truck_mounted_attenuator", "figure:work_vehicle",
        } <= components)
        targets = {row["to_source_unit_code"]
                   for row in retrieval.follow_cross_reference("TA-30")["items"]}
        self.assertTrue({"TABLE-6P-2", "TABLE-6B-1", "TABLE-6B-4"} <= targets)
        expanded = retrieval.expand_source_unit("TA-30", None, 12, None)
        self.assertEqual(len(expanded.get("_image_paths", [])), 1)
        self.assertTrue(Path(expanded["_image_paths"][0]).is_file())

    def test_unregistered_spacing_call_fails(self):
        gateway = ToolGatewayV5([], scene_view())
        result = gateway.call("audit_channelizer_spacing", {"discovered_requirement_key": "anything"})
        self.assertEqual(result["failure_reason"], "measurement_before_requirement_registration")

    def test_unknown_key_after_registration_phase_fails(self):
        gateway, _ = setup_spacing_gateway()
        result = gateway.call("audit_channelizer_spacing", {"discovered_requirement_key": "req_missing"})
        self.assertEqual(result["failure_reason"], "measurement_before_requirement_registration")

    def test_registered_spacing_succeeds_and_uses_registry_threshold(self):
        gateway, key = setup_spacing_gateway()
        result = gateway.call("audit_channelizer_spacing", {"discovered_requirement_key": key})
        self.assertEqual(result["status"], "acquired")
        self.assertEqual(result["discovered_requirement_key"], key)
        self.assertEqual(result["thresholds_applied"]["taper"]["value"], 30.0)
        self.assertEqual(result["thresholds_applied"]["tangent"]["value"], 60.0)
        self.assertEqual(result["gaps_evaluated"], 30)
        self.assertEqual(result["clear_exceedance_gap_count"], 0)
        self.assertFalse(result["deficiency_supported"])
        self.assertNotIn("inspection_status", result)
        self.assertNotIn("source_section", result)

    def test_measurement_event_is_after_registration(self):
        gateway, key = setup_spacing_gateway()
        result = gateway.call("audit_channelizer_spacing", {"discovered_requirement_key": key})
        self.assertLess(result["requirement_registration_event_index"], result["measurement_event_index"])
        gateway.registry.assert_measurement_order()
        self.assertEqual(validate_trace_measurement_order(gateway.trace), [])

    def test_requirement_review_plan_is_exported_before_measurement(self):
        gateway, key = setup_spacing_gateway()
        plan = requirement_review_plan(gateway.registry.snapshot())
        self.assertTrue(plan["stopped_before_measurement"])
        self.assertEqual(plan["registered_requirement_count"], 1)
        self.assertEqual(plan["planned_inspection_count"], 1)
        self.assertEqual(plan["planned_normative_measurement_count"], 1)
        self.assertEqual(plan["requirements"][0]["discovered_requirement_key"], key)
        self.assertEqual(plan["requirements"][0]["planned_tools"], ["audit_channelizer_spacing"])
        self.assertFalse(gateway.scene.measurements)

    def test_tool_schema_has_no_normative_answer_leak(self):
        schema = json.dumps(scene_tool_definitions(), ensure_ascii=False).lower()
        for forbidden in ("6k.01", "s/2s", "9.144", "18.288", "paragraph 04", "pdf page"):
            self.assertNotIn(forbidden, schema)
        spacing = next(row for row in scene_tool_definitions() if row["name"] == "audit_channelizer_spacing")
        self.assertEqual(spacing["parameters"]["required"], ["discovered_requirement_key"])

    def test_model_boundary_has_no_hidden_requirement_id(self):
        view = scene_view()
        payload = json.dumps({"stage0": stage0_prompt(view), "workflow": workflow_prompt(view, []),
                              "tools": ToolGatewayV5.definitions()}, ensure_ascii=False)
        self.assertNotRegex(payload, re.compile(r"\bL\d{2}-[A-Z0-9]+(?:-[A-Z0-9]+)+\b"))
        self.assertNotIn('"requirement_id"', payload)

    def test_scoped_stage1_stage2_boundary_exposes_only_six_domains_facts_and_ta(self):
        view = scene_view()
        supplied = {"scene_id": view["scene_id"], "scene_facts": {
            **view["scene_facts"], "pcms_deployed": None,
        }}
        layouts = self._stage0_record()["selected_layouts"]
        prompt = stage1_stage2_scoped_prompt(supplied, layouts)
        for region in REGIONS:
            self.assertIn(region, prompt)
        self.assertIn("TA-30", prompt)
        self.assertNotIn("accepted_bbox", prompt)
        self.assertNotIn("scene_data_manifest", prompt)
        self.assertNotIn("LAYOUT-01", prompt)
        self.assertNotIn("26 requirements", prompt)
        self.assertIn('"pcms_deployed": null', prompt)
        self.assertIn('"arrow_board_deployed": true', prompt)

        gateway = ToolGatewayV5(layouts, supplied)
        packet = _workflow_state_packet(supplied, layouts, gateway, True)
        self.assertNotIn("accepted_bbox_observations", packet)
        self.assertNotIn("accepted_observation_class_counts", packet)
        self.assertNotIn("saved_measurements", packet)

    def test_scoped_stage_contract_stops_after_registration(self):
        discovery = phase_contract("requirement_discovery", False, True, True)
        registration = phase_contract("requirement_registration", False, True, True)
        self.assertIn("load_ta_core_graph", discovery)
        self.assertIn("RAG is only a completeness checker", discovery)
        self.assertIn("submit_atomic_requirement_batch", registration)
        self.assertIn("STOP IMMEDIATELY AFTER Stage 2", registration)

    def test_scoped_gateway_requires_six_domain_discovery_ledger(self):
        gateway = ToolGatewayV5([{"layout_code": "TA-30"}], scene_view(),
                                scoped_stage1_stage2=True)
        names = {row["name"] for row in gateway.available_definitions()}
        self.assertIn("record_domain_discovery", names)
        self.assertIn("load_ta_core_graph", names)
        self.assertIn("load_scene_condition_graph", names)
        self.assertIn("audit_graph_gaps", names)
        self.assertNotIn("search_manual_for_need", names)
        self.assertNotIn("search_manual", names)
        self.assertNotIn("submit_requirement_batch", names)
        blocked = gateway.call("begin_requirement_registration", {})
        self.assertEqual(blocked["status"], "failure")
        self.assertIn("ledger is incomplete", blocked["failure_reason"])
        self.assertNotEqual(gateway.call("load_ta_core_graph", {}).get("status"), "failure")
        self.assertNotEqual(gateway.call("load_scene_condition_graph", {}).get("status"), "failure")
        for domain in REGIONS:
            audit = complete_gap_audit(gateway, domain)[-1]
            self.assertNotEqual(audit.get("status"), "failure")
            candidates = sorted(gateway.graph_candidate_node_ids[domain])
            result = gateway.call("record_domain_discovery", {
                "domain": domain,
                "status": ("covered_with_candidates" if candidates
                           else "covered_no_activated_candidate"),
                "query_summary": f"reviewed graph core, conditions, and gap page for {domain}",
                "source_node_ids": candidates,
            })
            self.assertEqual(result["domain"], domain)
        self.assertEqual(gateway.call("begin_requirement_registration", {})["phase"],
                         "requirement_registration")

    def test_gap_queries_are_broad_domain_concepts_not_expected_clauses(self):
        combined_queries = " ".join(DOMAIN_GAP_QUERIES.values()).lower()
        for clause_like_phrase in (
                "first warning sign encountered", "shall be replaced",
                "clean visible properly positioned", "beginning merging taper",
                "left lane closed", "only indicate lane closure"):
            self.assertNotIn(clause_like_phrase, combined_queries)
        self.assertEqual(set(DOMAIN_GAP_QUERIES), set(REGIONS))

    def test_simplified_prompt_uses_general_predicate_rules_not_target_phrases(self):
        prompt = simplified_stage1_stage2_prompt(
            scene_view(), [{"layout_code": "TA-30"}],
            {"architecture": "kg_plus_retrieval", "method": "bm25"},
        ).lower()
        for target_phrase in (
            "first warning sign encountered", "clean, visible, and properly positioned",
            "left lane closed legend", "w4-2l", "ws²/60",
        ):
            self.assertNotIn(target_phrase, prompt)
        self.assertIn("violated independently", prompt)

    def test_scope_filter_uses_structured_tags_not_incidental_source_words(self):
        retrieval = StructuredBM25V5()
        sign_sequence = next(
            retrieval._node_view(row) for row in retrieval.nodes_by_unit["SEC-6H.02"]
            if row.get("paragraph") == "02"
        )
        spacing_table = retrieval._node_view(retrieval.nodes_by_unit["TABLE-6B-1"][0])
        taper_table = retrieval._node_view(retrieval.nodes_by_unit["TABLE-6B-4"][0])
        self.assertIsNone(_project_scope_exclusion(sign_sequence))
        self.assertIsNone(_project_scope_exclusion(spacing_table))
        self.assertIsNone(_project_scope_exclusion(taper_table))
        pavement = next(
            retrieval._node_view(row) for row in retrieval.index["atomic_nodes"]
            if "pavement_markings" in row.get("scope_tags", [])
        )
        self.assertEqual(_project_scope_exclusion(pavement), "pavement_markings")

    def test_knowledge_graph_is_query_independent_and_covers_all_typical_applications(self):
        graph = json.loads((ROOT / "inputs/mutcd_knowledge_graph_v2.json").read_text())
        self.assertEqual(graph["schema_version"], "mutcd_knowledge_graph_v2")
        self.assertEqual(len(graph["typical_applications"]), 54)
        self.assertTrue(graph["build_policy"]["query_independent"])
        self.assertFalse(graph["build_policy"]["scene_manifest_read"])
        self.assertFalse(graph["build_policy"]["hidden_reference_read"])
        self.assertFalse(graph["build_policy"]["benchmark_requirement_ids_present"])
        self.assertEqual({row["source_unit_code"] for row in graph["typical_applications"]},
                         {f"TA-{number}" for number in range(1, 55)})
        structure = json.loads((ROOT / "inputs/mutcd_structure_v1.json").read_text())
        node_by_id = {row["node_id"]: row for row in structure["atomic_nodes"]}
        figure_provisions = [
            node_by_id[row["provision_id"]] for row in graph["normative_provisions"]
            if node_by_id[row["provision_id"]]["node_type"] == "figure_component"
        ]
        self.assertTrue(figure_provisions)
        self.assertTrue(all(row.get("normative_basis") and row["modality"] == "should"
                            for row in figure_provisions))
        self.assertFalse(any(row["paragraph"] == "figure:diagram"
                             for row in figure_provisions))
        self.assertTrue(any(row["source_unit_code"].startswith("TA-")
                            for row in graph["normative_provisions"]))

    def test_graph_layers_enforce_order_and_scene_activation(self):
        gateway = ToolGatewayV5([{"layout_code": "TA-30"}], scene_view(),
                                scoped_stage1_stage2=True)
        early = gateway.call("load_scene_condition_graph", {})
        self.assertEqual(early["status"], "failure")
        core = gateway.call("load_ta_core_graph", {})
        conditional = gateway.call("load_scene_condition_graph", {})
        self.assertEqual(core["layout_code"], "TA-30")
        self.assertIn("TA-30", core["source_units"])
        self.assertTrue(any(row["source_unit_code"] == "TA-30" and row["paragraph"] == "01"
                            for row in core["candidates"]))
        self.assertTrue(core["candidates"])
        self.assertIn("component:channelizing_device",
                      core["inferred_required_component_ids"])
        self.assertEqual(set(conditional["activated_component_ids"]), {
            "component:arrow_board", "component:channelizing_device",
        })
        self.assertNotIn("component:pcms", conditional["activated_component_ids"])
        self.assertTrue(all(row["modality"] in {"shall", "should", "standard", "guidance"}
                            for row in conditional["candidates"]))

    def test_gap_audit_returns_only_nodes_uncovered_by_graph_layers(self):
        gateway = ToolGatewayV5([{"layout_code": "TA-30"}], scene_view(), True)
        gateway.call("load_ta_core_graph", {})
        gateway.call("load_scene_condition_graph", {})
        domain = "advance_warning_sign_system"
        deterministic = set(gateway.graph_deterministic_node_ids[domain])
        audit = gateway.call("audit_graph_gaps", {
            "domain": domain, "page_size": 12, "continuation_token": None,
        })
        returned = {row["source_node_id"] for row in audit["items"]}
        self.assertTrue(returned)
        self.assertTrue(returned.isdisjoint(deterministic))
        self.assertEqual(audit["query"], DOMAIN_GAP_QUERIES[domain])
        self.assertLess(audit["uncovered_candidate_count"], audit["uncovered_corpus_count"])
        self.assertEqual(audit["ranking_policy"]["candidate_count_cap"], None)
        self.assertEqual(audit["ranking_policy"]["type"],
                         "relative_bm25_relevance_floor")
        self.assertTrue(all("gap_bm25_score" in row for row in audit["items"]))
        self.assertEqual(
            [row["gap_bm25_score"] for row in audit["items"]],
            sorted((row["gap_bm25_score"] for row in audit["items"]), reverse=True),
        )

    def test_domain_cannot_close_before_finite_gap_audit_is_complete(self):
        gateway = ToolGatewayV5([{"layout_code": "TA-30"}], scene_view(), True)
        gateway.call("load_ta_core_graph", {})
        gateway.call("load_scene_condition_graph", {})
        domain = "lane_closure_layout"
        first = gateway.call("audit_graph_gaps", {
            "domain": domain, "page_size": 12, "continuation_token": None,
        })
        self.assertTrue(first["has_more"])
        blocked = gateway.call("record_domain_discovery", {
            "domain": domain, "status": "covered_with_candidates",
            "query_summary": "premature closure",
            "source_node_ids": sorted(gateway.graph_candidate_node_ids[domain]),
        })
        self.assertEqual(blocked["status"], "failure")
        self.assertIn("audit is incomplete", blocked["failure_reason"])

    def test_kg_first_checkpoint_restores_layer_and_candidate_state(self):
        layouts = [{"layout_code": "TA-30"}]
        view = scene_view()
        gateway = ToolGatewayV5(layouts, view, True)
        gateway.call("load_ta_core_graph", {})
        gateway.call("load_scene_condition_graph", {})
        gateway.call("audit_graph_gaps", {
            "domain": "channelization_system", "page_size": 3,
            "continuation_token": None,
        })
        restored = ToolGatewayV5.from_checkpoint(
            layouts, view, gateway.registry.snapshot(), gateway.trace, True,
        )
        self.assertIsNotNone(restored.graph_stage1a_result)
        self.assertIsNotNone(restored.graph_stage1b_result)
        self.assertEqual(len(restored.graph_gap_audits["channelization_system"]), 1)
        self.assertEqual(restored.graph_candidate_node_ids["channelization_system"],
                         gateway.graph_candidate_node_ids["channelization_system"])

    def test_simplified_workflow_uses_finite_domain_loads_and_no_candidate_ledger(self):
        gateway = ToolGatewayV5([{"layout_code": "TA-30"}], scene_view(), True, True)
        names = {row["name"] for row in gateway.available_definitions()}
        self.assertEqual(names, {
            "load_ta_core_graph", "load_scene_condition_graph",
            "load_domain_gap_candidates", "begin_requirement_registration",
        })
        gateway.call("load_ta_core_graph", {})
        gateway.call("load_scene_condition_graph", {})
        for domain in REGIONS:
            result = gateway.call("load_domain_gap_candidates", {"domain": domain})
            self.assertFalse(result["has_more"])
            self.assertIsNone(result["continuation_token"])
            self.assertLess(len(json.dumps(result)), 24000)
        self.assertEqual(gateway.call("begin_requirement_registration", {})["phase"],
                         "requirement_registration")
        registration_names = {row["name"] for row in gateway.available_definitions()}
        self.assertEqual(registration_names, {
            "submit_inspection_check_batch", "exclude_discovery_candidate_batch",
            "audit_stage2_candidate_coverage",
            "submit_stage2_candidate_decision_batch",
            "complete_region_batch",
            "seal_requirement_registration",
        })
        premature = gateway.call("complete_region_batch", {"regions": [
            {"region": domain, "status": "screened", "reason": "premature test"}
            for domain in REGIONS
        ]})
        self.assertEqual(premature["status"], "failure")
        self.assertIn("require at least one inspection check", premature["failure_reason"])

    def test_stage2_coverage_audit_is_general_and_must_follow_final_decision(self):
        gateway = ToolGatewayV5(
            [{"layout_code": "TA-30"}], scene_view(), True, True,
            gap_retrieval={"architecture": "kg_only", "method": "bm25"},
        )
        gateway.call("load_ta_core_graph", {})
        gateway.call("load_scene_condition_graph", {})
        gateway.call("begin_requirement_registration", {})

        audit = gateway.call("audit_stage2_candidate_coverage", {})
        self.assertGreater(audit["unresolved_candidate_count"], 0)
        self.assertEqual(gateway.stage2_audit_revision, audit["decision_revision"])
        self.assertLess(len(json.dumps(audit)), 24000)
        serialized = json.dumps(audit)
        for hidden_id in ("LC-01", "AWS-01", "CH-01", "TT-03", "AD-01"):
            self.assertNotIn(hidden_id, serialized)
        self.assertEqual(len(audit["verification_questions"]), 3)

        candidate = audit["unresolved_candidates"][0]
        domain = candidate["domain"]
        excluded = gateway.call("exclude_discovery_candidate_batch", {
            "domain": domain,
            "exclusions": [{
                "source_node_id": candidate["source_node_id"],
                "reason_code": "activation_predicate_not_established",
                "reason": "The candidate antecedent is not established by the frozen input.",
            }],
        })
        self.assertEqual(len(excluded["accepted_exclusions"]), 1)
        stale = gateway.call("seal_requirement_registration", {})
        self.assertEqual(stale["status"], "failure")
        self.assertIn("audit is missing or stale", stale["failure_reason"])

        refreshed = gateway.call("audit_stage2_candidate_coverage", {})
        self.assertEqual(gateway.stage2_audit_revision, gateway.stage2_decision_revision)
        self.assertEqual(refreshed["new_candidate_count"], 0)
        self.assertGreater(refreshed["previously_presented_unresolved_count"], 0)
        self.assertEqual(gateway.stage2_candidate_audit_calls, 2)

    def test_structured_candidate_decision_program_binds_and_registers_predicate(self):
        gateway = ToolGatewayV5(
            [{"layout_code": "TA-30"}], scene_view(), True, True,
            gap_retrieval={"architecture": "kg_only", "method": "bm25"},
        )
        gateway.call("load_ta_core_graph", {})
        gateway.call("load_scene_condition_graph", {})
        gateway.call("begin_requirement_registration", {})
        audit = gateway.call("audit_stage2_candidate_coverage", {})
        candidate = next(
            row for row in audit["unresolved_candidates"]
            if gateway._program_activation_basis(row["source_node_id"])["type"]
            != "unconditional"
        )
        node = gateway.retrieved_nodes[candidate["source_node_id"]]
        result = gateway.call("submit_stage2_candidate_decision_batch", {
            "decisions": [{
                "source_node_id": candidate["source_node_id"],
                "activation_status": "established",
                "independently_violable": True,
                "duplicate_of_source_node_id": None,
                "action": "retain",
                "decision_basis": "activated_independent",
                "reason": "The frozen component trigger establishes applicability and the predicate can fail independently.",
                "measurement_spec": {"required": False, "tool": None,
                                     "quantity": None, "thresholds": []},
            }],
        })
        self.assertEqual(len(result["accepted_decisions"]), 1)
        key = result["accepted_decisions"][0]["registered_requirement_key"]
        stored = gateway.registry.requirements[key]
        self.assertEqual(stored["subject"], node["subject"])
        self.assertEqual(stored["relation"], node["relation"])
        self.assertEqual(stored["threshold"], node["threshold"])
        self.assertEqual(stored["source_node_ids"], [candidate["source_node_id"]])
        self.assertIn(stored["activation_basis"]["type"], {"scene_fact", "selected_ta", "combined"})

        stale = gateway.call("seal_requirement_registration", {})
        self.assertEqual(stale["status"], "failure")
        self.assertIn("audit is missing or stale", stale["failure_reason"])
        refreshed = gateway.call("audit_stage2_candidate_coverage", {})
        self.assertGreater(refreshed["pending_structured_decision_count"], 0)

    def test_structured_candidate_decision_rejects_inconsistent_retain(self):
        gateway = ToolGatewayV5(
            [{"layout_code": "TA-30"}], scene_view(), True, True,
            gap_retrieval={"architecture": "kg_only", "method": "bm25"},
        )
        gateway.call("load_ta_core_graph", {})
        gateway.call("load_scene_condition_graph", {})
        gateway.call("begin_requirement_registration", {})
        candidate = gateway.call("audit_stage2_candidate_coverage", {})[
            "unresolved_candidates"
        ][0]
        result = gateway.call("submit_stage2_candidate_decision_batch", {
            "decisions": [{
                "source_node_id": candidate["source_node_id"],
                "activation_status": "false",
                "independently_violable": True,
                "duplicate_of_source_node_id": None,
                "action": "retain",
                "decision_basis": "activated_independent",
                "reason": "Intentionally inconsistent test decision.",
                "measurement_spec": {"required": False, "tool": None,
                                     "quantity": None, "thresholds": []},
            }],
        })
        self.assertEqual(result["status"], "failure")
        self.assertIn("retain requires established activation", result["failure_reason"])

    def test_discovery_ledger_has_no_old_per_domain_candidate_ceiling(self):
        gateway = ToolGatewayV5([{"layout_code": "TA-30"}], scene_view(),
                                scoped_stage1_stage2=True)
        domain = "advance_warning_sign_system"
        gateway.call("load_ta_core_graph", {})
        gateway.call("load_scene_condition_graph", {})
        complete_gap_audit(gateway, domain)
        candidates = sorted(gateway.graph_candidate_node_ids[domain])
        self.assertGreater(len(candidates), 5)
        result = gateway.call("record_domain_discovery", {
            "domain": domain, "status": "covered_with_candidates",
            "query_summary": "recall-oriented broad search",
            "source_node_ids": candidates,
        })
        self.assertEqual(len(result["source_node_ids"]), len(candidates))

    def test_selected_ta_non_optional_figure_guidance_can_be_registered(self):
        gateway = ToolGatewayV5([{"layout_code": "TA-30"}], scene_view(),
                                scoped_stage1_stage2=True)
        expanded = gateway.retrieval.expand_source_unit("TA-30", None, 12, None)
        node = next(row for row in expanded["items"] if row.get("node_type") == "figure_component"
                    and row.get("paragraph") == "figure:sign:W4-2L")
        gateway.retrieved_nodes[node["source_node_id"]] = node
        gateway.registry.begin_requirement_registration()
        result = gateway._submit_atomic_requirement_batch({
            "domain": "advance_warning_sign_system", "requirements": [{
                "candidate_label": "selected TA sign position", "subject": node["subject"],
                "relation": node["relation"], "threshold": node["threshold"],
                "applicability_conditions": node["applicability_conditions"],
                "required_inputs": node["required_inputs"],
                "source_node_id": node["source_node_id"],
                "activation_basis": {"type": "selected_ta", "fact_keys": [],
                    "evidence_source_node_ids": [node["source_node_id"]],
                    "explanation": "The selected TA depicts this component as non-optional."},
                "measurement_spec": {"required": False, "tool": None,
                                     "quantity": None, "thresholds": []},
            }],
        })
        accepted = gateway.registry.requirements[result["accepted_requirement_keys"][0]]
        self.assertEqual(accepted["modality"], "should")
        self.assertIn("Guidance basis SEC-6P.01 paragraph 02",
                      accepted["source_locator"])

    def test_atomic_registration_program_binds_canonical_source_fields(self):
        gateway = ToolGatewayV5([{"layout_code": "TA-30"}], scene_view(),
                                scoped_stage1_stage2=True)
        gateway.call("load_ta_core_graph", {})
        gateway.call("load_scene_condition_graph", {})
        node = next(row for row in gateway.retrieved_nodes.values()
                    if row.get("source_unit_code") == "SEC-6K.01" and
                    row.get("paragraph") == "04")
        for domain in REGIONS:
            complete_gap_audit(gateway, domain)
            gateway.call("record_domain_discovery", {
                "domain": domain,
                "status": ("covered_with_candidates" if domain == "channelization_system"
                           else "covered_no_activated_candidate"),
                "query_summary": f"screened {domain}",
                "source_node_ids": [node["source_node_id"]] if domain == "channelization_system" else [],
            })
        gateway.call("begin_requirement_registration", {})
        result = gateway.call("submit_atomic_requirement_batch", {
            "domain": "channelization_system", "requirements": [{
                "candidate_label": "taper spacing", "subject": "channelizing device spacing",
                "relation": "not exceed", "threshold": "1 times speed in feet",
                "applicability_conditions": ["taper channelization"],
                "required_inputs": ["posted_speed_mph", "spacing_measurement"],
                "source_node_id": node["source_node_id"],
                "activation_basis": {"type": "unconditional", "fact_keys": [],
                                     "evidence_source_node_ids": [],
                                     "explanation": "Basic lane-closure channelization rule."},
                "measurement_spec": {"required": True, "tool": "audit_channelizer_spacing",
                    "quantity": "adjacent spacing", "thresholds": [
                        {"condition": "taper", "value": None, "unit": "ft",
                         "violation_when": "above_maximum", "formula_parameter": "posted_speed_mph",
                         "multiplier": 1.0},
                    ]},
            }],
        })
        self.assertEqual(len(result["accepted_requirement_keys"]), 1)
        stored = gateway.registry.requirements[result["accepted_requirement_keys"][0]]
        self.assertEqual(stored["modality"], node["modality"])
        self.assertEqual(stored["source_locator"], node["source_locator"])
        self.assertEqual(stored["source_span"], node["source_span"])
        # Atomicity is semantic, not a case-tuned minimum output count. One
        # independently decidable predicate is valid even when this review
        # dimension produced two atoms in a previous canary.
        gateway._validate_discovery_candidate_dispositions()

    def test_atomic_registration_normalizes_guidance_and_rejects_unknown_activation_fact(self):
        gateway = ToolGatewayV5([], scene_view(), scoped_stage1_stage2=True)
        table = gateway.retrieval.expand_source_unit("TABLE-6B-1", None, 12, None)["items"][0]
        gateway.retrieved_nodes[table["source_node_id"]] = table
        gateway.registry.begin_requirement_registration()
        base = {
            "candidate_label": "table guidance", "subject": table["subject"],
            "relation": table["relation"], "threshold": table["threshold"],
            "applicability_conditions": table["applicability_conditions"],
            "required_inputs": table["required_inputs"], "source_node_id": table["source_node_id"],
            "activation_basis": {"type": "unconditional", "fact_keys": [],
                                 "evidence_source_node_ids": [], "explanation": "test"},
            "measurement_spec": {"required": False, "tool": None,
                                 "quantity": None, "thresholds": []},
        }
        result = gateway._submit_atomic_requirement_batch({
            "domain": "advance_warning_sign_system", "requirements": [base],
        })
        stored = gateway.registry.requirements[result["accepted_requirement_keys"][0]]
        self.assertEqual(stored["modality"], "should")

        arrow_gateway = ToolGatewayV5([], scene_view(), scoped_stage1_stage2=True)
        expanded = arrow_gateway.retrieval.expand_source_unit("SEC-6L.06", None, 12, None)
        arrow = next(row for row in expanded["items"] if row.get("paragraph") == "03")
        arrow_gateway.retrieved_nodes[arrow["source_node_id"]] = arrow
        with self.assertRaisesRegex(RegistryError, "activation is not established"):
            arrow_gateway._submit_atomic_requirement_batch({
                "domain": "conditional_active_devices", "requirements": [{
                    "candidate_label": "unknown operation", "subject": arrow["subject"],
                    "relation": arrow["relation"], "threshold": arrow["threshold"],
                    "applicability_conditions": arrow["applicability_conditions"],
                    "required_inputs": arrow["required_inputs"],
                    "source_node_id": arrow["source_node_id"],
                    "activation_basis": {"type": "scene_fact",
                        "fact_keys": ["arrow_board_operating"],
                        "evidence_source_node_ids": [], "explanation": "unknown operation"},
                    "measurement_spec": {"required": False, "tool": None,
                                         "quantity": None, "thresholds": []},
                }],
            })

    def test_atomic_batch_keeps_valid_items_when_sibling_activation_is_invalid(self):
        gateway = ToolGatewayV5([], scene_view(), scoped_stage1_stage2=True)
        maintenance = gateway.retrieval._node_view(next(
            row for row in gateway.retrieval.nodes_by_unit["SEC-6K.01"]
            if row.get("paragraph") == "14"
        ))
        gateway.retrieved_nodes[maintenance["source_node_id"]] = maintenance
        gateway.registry.begin_requirement_registration()

        def item(label, node, fact_keys):
            return {
                "candidate_label": label, "subject": node["subject"],
                "relation": node["relation"], "threshold": node["threshold"],
                "applicability_conditions": node["applicability_conditions"],
                "required_inputs": node["required_inputs"],
                "source_node_id": node["source_node_id"],
                "activation_basis": {"type": "scene_fact", "fact_keys": fact_keys,
                    "evidence_source_node_ids": [], "explanation": "test activation"},
                "measurement_spec": {"required": False, "tool": None,
                                     "quantity": None, "thresholds": []},
            }

        result = gateway._submit_atomic_requirement_batch({
            "domain": "channelization_system",
            "requirements": [
                item("valid maintenance", maintenance, ["closed_lane"]),
                item("invalid replacement", maintenance, ["unknown_fact"]),
            ],
        })
        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(len(result["accepted_requirement_keys"]), 1)
        self.assertEqual(result["rejected_requirements"][0]["candidate_label"],
                         "invalid replacement")
        self.assertEqual(len(gateway.registry.requirements), 1)

    def test_scoped_stage2_requires_disposition_for_each_discovery_candidate(self):
        gateway = ToolGatewayV5([], scene_view(), scoped_stage1_stage2=True)
        node = gateway.retrieval._node_view(next(
            row for row in gateway.retrieval.nodes_by_unit["SEC-6K.01"]
            if row.get("paragraph") == "14"
        ))
        gateway.retrieved_nodes[node["source_node_id"]] = node
        gateway.discovery_coverage["channelization_system"] = {
            "status": "covered_with_candidates", "query_summary": "test",
            "source_node_ids": [node["source_node_id"]],
        }
        with self.assertRaisesRegex(RegistryError, "lack an explicit Stage-2 disposition"):
            gateway._validate_discovery_candidate_dispositions()
        gateway._exclude_discovery_candidate_batch({
            "domain": "channelization_system",
            "exclusions": [{"source_node_id": node["source_node_id"],
                "reason_code": "activation_predicate_not_established",
                "reason": "test exclusion"}],
        })
        gateway._validate_discovery_candidate_dispositions()

    def test_scoped_stage2_rejects_semantic_retry_of_committed_requirement(self):
        gateway = ToolGatewayV5([], scene_view(), scoped_stage1_stage2=True)
        node = gateway.retrieval._node_view(next(
            row for row in gateway.retrieval.nodes_by_unit["SEC-6K.01"]
            if row.get("paragraph") == "14"
        ))
        gateway.retrieved_nodes[node["source_node_id"]] = node
        gateway.discovery_coverage["channelization_system"] = {
            "status": "covered_with_candidates", "query_summary": "test",
            "source_node_ids": [node["source_node_id"]],
        }
        gateway.registry.begin_requirement_registration()

        def item(label):
            return {
                "candidate_label": label, "subject": "channelizing devices",
                "relation": "should_be_maintained",
                "threshold": "clean, visible, and properly positioned at all times",
                "applicability_conditions": [], "required_inputs": ["raw_images"],
                "source_node_id": node["source_node_id"],
                "activation_basis": {"type": "unconditional", "fact_keys": [],
                    "evidence_source_node_ids": [], "explanation": "test"},
                "measurement_spec": {"required": False, "tool": None,
                                     "quantity": None, "thresholds": []},
            }

        gateway._submit_atomic_requirement_batch({
            "domain": "channelization_system", "requirements": [item("maintenance")],
        })
        with self.assertRaisesRegex(RegistryError, "semantic duplicate"):
            gateway._submit_atomic_requirement_batch({
                "domain": "channelization_system", "requirements": [item("maintenance retry")],
            })

    def test_selected_ta_activation_is_not_rewritten_to_match_a_case_rule(self):
        gateway = ToolGatewayV5([{"layout_code": "TA-30"}], scene_view(),
                                scoped_stage1_stage2=True)
        core = gateway.call("load_ta_core_graph", {})
        node_id = next(row["source_node_id"] for row in core["candidates"]
                       if "advance_warning_sign_system" in row["domains"])
        node = gateway.retrieved_nodes[node_id]
        ta_evidence = next(
            node_id for node_id, item in gateway.retrieved_nodes.items()
            if item.get("source_unit_code") == "TA-30"
        )
        gateway.discovery_coverage["advance_warning_sign_system"] = {
            "status": "covered_with_candidates", "query_summary": "test",
            "source_node_ids": [node["source_node_id"]],
        }
        gateway.registry.begin_requirement_registration()
        result = gateway._submit_atomic_requirement_batch({
            "domain": "advance_warning_sign_system", "requirements": [{
                "candidate_label": "first warning sign", "subject": "ROAD WORK AHEAD sign",
                "relation": "should be first", "threshold": "first warning sign encountered",
                "applicability_conditions": ["multiple warning signs"],
                "required_inputs": ["raw_images"], "source_node_id": node["source_node_id"],
                "activation_basis": {"type": "selected_ta", "fact_keys": [],
                    "evidence_source_node_ids": [ta_evidence],
                    "explanation": "The selected TA establishes applicability."},
                "measurement_spec": {"required": False, "tool": None,
                                     "quantity": None, "thresholds": []},
            }],
        })
        stored = gateway.registry.requirements[result["accepted_requirement_keys"][0]]
        self.assertEqual(stored["activation_basis"]["type"], "selected_ta")
        self.assertEqual(stored["activation_basis"]["fact_keys"], [])
        self.assertEqual(stored["activation_basis"]["evidence_source_node_ids"], [ta_evidence])

    def test_conditional_termination_registration_requires_presence_trigger(self):
        gateway = ToolGatewayV5([], scene_view(), scoped_stage1_stage2=True)
        expanded = gateway.retrieval.expand_source_unit("TABLE-6B-3", None, 12, None)
        gateway._remember_retrieved_nodes(expanded)
        node = expanded["items"][0]
        gateway.registry.begin_requirement_registration()
        with self.assertRaisesRegex(RegistryError, "termination requirements need an explicit true"):
            gateway._submit_atomic_requirement_batch({
                "domain": "conditional_termination_area", "requirements": [{
                    "candidate_label": "termination", "subject": node["subject"],
                    "relation": node["relation"], "threshold": node["threshold"],
                    "applicability_conditions": node["applicability_conditions"],
                    "required_inputs": node["required_inputs"],
                    "source_node_id": node["source_node_id"],
                    "activation_basis": {"type": "unconditional", "fact_keys": [],
                        "evidence_source_node_ids": [], "explanation": "test"},
                    "measurement_spec": {"required": False, "tool": None,
                                         "quantity": None, "thresholds": []},
                }],
            })

    def test_source_modality_must_match_retrieved_standard_or_guidance(self):
        gateway = ToolGatewayV5([], scene_view())
        expanded = gateway.call("expand_source_unit", {
            "source_unit_code": "SEC-6K.01", "region": "channelizing_devices",
            "page_size": 12, "continuation_token": None,
        })
        node = next(row for row in expanded["items"] if row.get("paragraph") == "04")
        gateway.call("begin_requirement_registration", {})
        wrong = "shall" if node["modality"] == "should" else "should"
        result = gateway.call("submit_requirement_batch", {
            "region": "channelization_system", "requirements": [{
                "candidate_label": "wrong modality", "subject": node["subject"],
                "modality": wrong, "relation": node["relation"], "threshold": node["threshold"],
                "applicability_conditions": node["applicability_conditions"], "required_inputs": [],
                "source_node_ids": [node["source_node_id"]], "source_locator": node["source_locator"],
                "source_span": node["source_span"],
                "measurement_spec": {"required": False, "tool": None,
                                     "quantity": None, "thresholds": []},
            }],
        })
        self.assertEqual(result["status"], "failure")
        self.assertIn("modality does not match", result["failure_reason"])

    def test_registration_rejects_hidden_id(self):
        registry = InspectionRegistry("scene", [])
        registry.begin_requirement_registration()
        with self.assertRaisesRegex(RegistryError, "requirement_id"):
            registry.submit_requirement_batch("transition_and_taper_geometry", [{"requirement_id": "hidden"}])

    def test_source_must_have_been_retrieved(self):
        gateway = ToolGatewayV5([], scene_view())
        gateway.call("begin_requirement_registration", {})
        result = gateway.call("submit_requirement_batch", {"region": "transition_and_taper_geometry", "requirements": [{
            "candidate_label": "x", "subject": "x", "modality": "shall", "relation": "x",
            "threshold": "x", "applicability_conditions": [], "required_inputs": [],
            "source_node_ids": ["src_not_seen"], "source_locator": "x", "source_span": "x",
            "measurement_spec": {"required": False, "tool": None, "quantity": None, "thresholds": []},
        }]})
        self.assertEqual(result["status"], "failure")
        self.assertIn("not retrieved", result["failure_reason"])

    def test_grounded_source_excerpt_is_canonicalized_from_visible_node(self):
        gateway = ToolGatewayV5([], scene_view())
        expanded = gateway.call("expand_source_unit", {
            "source_unit_code": "TA-30", "region": "applicability",
            "page_size": 12, "continuation_token": None,
        })
        node = expanded["items"][0]
        gateway.call("begin_requirement_registration", {})
        excerpt = node["source_span"].split(". ", 1)[0] + "."
        result = gateway.call("submit_requirement_batch", {"region": "lane_closure_layout", "requirements": [{
            "candidate_label": "grounded excerpt", "subject": node["subject"],
            "modality": node["modality"], "relation": node["relation"], "threshold": node["threshold"],
            "applicability_conditions": node["applicability_conditions"], "required_inputs": [],
            "source_node_ids": [node["source_node_id"]], "source_locator": node["source_locator"],
            "source_span": excerpt,
            "measurement_spec": {"required": False, "tool": None, "quantity": None, "thresholds": []},
        }]})
        self.assertEqual(len(result["accepted_requirement_keys"]), 1)
        stored = gateway.registry.requirements[result["accepted_requirement_keys"][0]]
        self.assertEqual(stored["model_extracted_source_span"], excerpt)
        self.assertEqual(stored["source_span"], node["source_span"])

    def test_gateway_can_resume_validated_registry_checkpoint(self):
        gateway, key = setup_spacing_gateway()
        restored = ToolGatewayV5.from_checkpoint([], scene_view(), gateway.registry.snapshot(), gateway.trace)
        self.assertEqual(restored.registry.phase, "measurement")
        self.assertIn(key, restored.registry.requirements)
        self.assertTrue(restored.retrieved_nodes)
        self.assertFalse(restored.scene.measurements)

    def test_current_scene_has_confirmed_arrow_board_and_no_superseded_pcms(self):
        gateway = ToolGatewayV5([], scene_view())
        self.assertEqual(gateway.scene.arrow_board_observation_ids,
                         ["F0316_CAM_BACK_LEFT_010"])
        self.assertEqual(gateway.scene.pcms_observation_ids, [])
        manifest = gateway.scene.manifest()
        self.assertIs(manifest["derived_scene_facts"]["arrow_board_deployed"], True)
        self.assertIsNone(manifest["derived_scene_facts"]["pcms_deployed"])

    def test_human_review_is_rejected(self):
        gateway = ToolGatewayV5([], scene_view())
        with self.assertRaisesRegex(RegistryError, "human review"):
            gateway._validate_inspection_evidence({"inspections": [{
                "discovered_requirement_key": "x", "requires_human_review": True,
                "inspection_status": "not_assessed", "failure_reason": "", "inspection_reason": "",
                "unresolved_inputs": [], "evidence_ids": [], "measurement_ids": [],
                "derivation_evidence_ids": [], "external_evidence_ids": [],
            }]})

    def test_geometry_uses_station_interval_and_clear_violation_gate(self):
        tool = SceneDataToolsV5.__new__(SceneDataToolsV5)
        tool.geometry_policy = {"station_confidence_percentiles": [5, 95],
            "lateral_residual_warning_m": 12.0, "lateral_residual_reject_m": 30.0,
            "width_max_longitudinal_offset_m": 10.0, "width_normal_dominance_ratio": 1.0}
        tool.measurements, tool.resources, tool.observations = {}, {"cpu_seconds": 0.0}, {}
        tool.meta_root = Path("/tmp/test_metadata")
        locations = {
            "a": {"status": "acquired", "observation_id": "a", "road_station_m": 10.0,
                  "station_confidence_interval_m": [9, 11], "station_uncertainty_m": 1,
                  "trajectory_lateral_offset_m": 20.0, "trajectory_lateral_residual_m": 20.0,
                  "lateral_confidence_interval_m": [19.5, 20.5], "longitudinal_geometry_usable": True,
                  "depth_cluster_points": 10, "global_xyz_m": [10, 20, 0], "quality_flags": [],
                  "associated_image_ids": ["ia"], "associated_lidar_frames": ["la"]},
            "b": {"status": "acquired", "observation_id": "b", "road_station_m": 30.0,
                  "station_confidence_interval_m": [29, 31], "station_uncertainty_m": 1,
                  "trajectory_lateral_offset_m": 20.0, "trajectory_lateral_residual_m": 20.0,
                  "lateral_confidence_interval_m": [19.5, 20.5], "longitudinal_geometry_usable": True,
                  "depth_cluster_points": 10, "global_xyz_m": [30, 20, 0], "quality_flags": [],
                  "associated_image_ids": ["ib"], "associated_lidar_frames": ["lb"]},
        }
        with patch.object(tool, "locate_device_in_scene", side_effect=lambda key: locations[key]):
            result = tool.measure_taper_length("a", "b", 25, "m", "below_minimum")
        self.assertEqual(result["confidence_interval"], [18.0, 22.0])
        self.assertTrue(result["deficiency_supported"])


if __name__ == "__main__":
    unittest.main()
