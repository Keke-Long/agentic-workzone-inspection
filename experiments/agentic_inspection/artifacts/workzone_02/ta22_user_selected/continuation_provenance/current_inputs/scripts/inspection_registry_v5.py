#!/usr/bin/env python3
"""Model-ID-free staged registry for autonomous inspection.

The registry is an executable phase barrier.  A requirement is discovered from
retrieved manual nodes, registered, assigned a run-local key, and data-gated
before any normative measurement can run.  Measurements and final inspection
records are bound to that generated key and to the registered requirement
fingerprint.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any


COVERAGE_DOMAINS = (
    "lane_closure_layout",
    "advance_warning_sign_system",
    "channelization_system",
    "transition_and_taper_geometry",
    "conditional_active_devices",
    "conditional_termination_area",
)
# Compatibility name retained for the existing registry wire format. Values are
# now inspection coverage domains, not MUTCD source regions.
REGIONS = COVERAGE_DOMAINS

PHASES = (
    "requirement_discovery", "requirement_registration", "data_availability",
    "measurement", "inspection_conclusion", "result_submission", "finalized",
)
TERMINAL_REGION_STATES = {"screened", "skipped_no_inspectable_candidate"}
INSPECTION_STATUSES = {"satisfied", "deficient", "not_assessed"}
DATA_AVAILABILITY_STATES = {
    "available_direct", "acquired", "unavailable_after_attempt", "not_attempted", "partial",
}
NORMATIVE_MEASUREMENT_TOOLS = {
    "measure_longitudinal_distance", "measure_device_spacing", "audit_channelizer_spacing",
    "measure_taper_length", "measure_buffer_length", "measure_sign_spacing",
    "measure_downstream_taper", "estimate_available_width",
}
PLANNABLE_EVIDENCE_TOOLS = {
    "get_scene_data_manifest", "list_scene_sensors", "get_reviewed_observations",
    "list_temporal_frames", "inspect_temporal_images", "inspect_observation_images",
    "get_vehicle_trajectory", "get_ego_pose", "get_sensor_calibration", "get_sensor_sync",
    "project_bbox_to_lidar", "locate_device_in_scene", "search_speed_limit_signs",
    "record_speed_sign_reading", "locate_road_segment", "lookup_posted_speed",
    "query_road_authority_source", "resolve_speed_evidence_conflict",
    *NORMATIVE_MEASUREMENT_TOOLS,
}
EVIDENCE_KINDS = {
    "direct_fact", "visual_observation", "measurement_context", "acquisition_failure",
}
ACQUISITION_TOOLS = {
    # Canonical visual-input labels emitted by the Stage 2 compiler.  Keeping
    # these modality-level aliases here lets Stage 4 route requirements
    # without relying on requirement-specific wording.
    "raw_images": {"inspect_temporal_images", "inspect_observation_images"},
    "traffic_sign_observations": {"inspect_temporal_images", "inspect_observation_images"},
    "accepted_bbox_observations": {"inspect_temporal_images", "inspect_observation_images"},
    "channelization_region": {"inspect_temporal_images", "inspect_observation_images"},
    "full_temporal_images": {"inspect_temporal_images", "search_speed_limit_signs"},
    "dense_temporal_images": {"inspect_temporal_images", "search_speed_limit_signs"},
    "lidar_points": {"project_bbox_to_lidar", "locate_device_in_scene", *NORMATIVE_MEASUREMENT_TOOLS},
    "ego_trajectory": {"get_vehicle_trajectory", "locate_device_in_scene", *NORMATIVE_MEASUREMENT_TOOLS},
    "sensor_calibration": {"get_sensor_calibration", "project_bbox_to_lidar", "locate_device_in_scene",
                           *NORMATIVE_MEASUREMENT_TOOLS},
    "posted_speed": {"search_speed_limit_signs", "locate_road_segment", "lookup_posted_speed",
                     "query_road_authority_source", "record_speed_sign_reading",
                     "resolve_speed_evidence_conflict"},
    "posted_speed_mph": {"search_speed_limit_signs", "locate_road_segment", "lookup_posted_speed",
                         "query_road_authority_source", "record_speed_sign_reading",
                         "resolve_speed_evidence_conflict"},
    "measurement": set(NORMATIVE_MEASUREMENT_TOOLS),
    "spacing_measurement": {"measure_device_spacing", "audit_channelizer_spacing"},
    "survey_grade_measurements": set(NORMATIVE_MEASUREMENT_TOOLS),
    "sequence_membership_labels": {"audit_channelizer_spacing"},
    "true_adjacency_labels": {"audit_channelizer_spacing"},
    "available_width": {"estimate_available_width"},
    "available_width_ft": {"estimate_available_width"},
}


def acquisition_tools_for_input(input_name: str) -> set[str]:
    """Map free-text Stage 2 input labels to executable Stage 4 tool families."""
    if input_name in ACQUISITION_TOOLS:
        return set(ACQUISITION_TOOLS[input_name])
    text = input_name.casefold().replace("-", " ")
    if "spacing" in text and ("device" in text or "channel" in text):
        return {"audit_channelizer_spacing", "measure_device_spacing"}
    if "taper length" in text:
        return {"measure_taper_length"}
    if "width" in text or "offset" in text:
        return {"estimate_available_width"}
    if "posted speed" in text or "speed limit" in text:
        return {
            "search_speed_limit_signs", "record_speed_sign_reading", "locate_road_segment",
            "lookup_posted_speed", "query_road_authority_source",
        }
    visual_terms = {
        "observed", "legend", "display", "condition", "visibility", "cleanliness",
        "position", "location", "movement", "arrangement", "transition", "device function",
        "operation status", "operation type", "detour", "field view", "boundary",
        "camera", "image", "view of",
    }
    if any(term in text for term in visual_terms):
        return {"inspect_temporal_images", "inspect_observation_images"}
    return set()


class RegistryError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _contains_forbidden_requirement_id(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key == "requirement_id" or _contains_forbidden_requirement_id(item)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_requirement_id(item) for item in value)
    return False


def _fingerprint(requirement: dict) -> str:
    material = {key: value for key, value in requirement.items()
                if key not in {"discovered_requirement_key", "registration_event_index",
                               "registration_timestamp", "requirement_fingerprint", "region"}}
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


class InspectionRegistry:
    def __init__(self, scene_id: str, selected_layouts: list[dict], max_batch_size: int = 12) -> None:
        self.scene_id = scene_id
        self.selected_layouts = deepcopy(selected_layouts)
        self.max_batch_size = max_batch_size
        self.phase = "requirement_discovery"
        self.regions = {region: {"status": "pending", "reason": "", "requirement_keys": []}
                        for region in REGIONS}
        self.requirements: dict[str, dict] = {}
        self.requirement_fingerprints: dict[str, str] = {}
        self.data_availability: dict[str, dict] = {}
        self.evidence_records: dict[str, dict] = {}
        self.evidence_fingerprints: set[str] = set()
        self.stage4_plan: dict | None = None
        self.inspection_bundles: dict[str, dict] = {}
        self.acquisition_attempts: dict[str, dict] = {}
        self.measurement_records: dict[str, dict] = {}
        self.stage4_readiness: dict | None = None
        self.stage5_plan: dict | None = None
        self.conclusion_drafts: dict[str, dict] = {}
        self.stage5_readiness: dict | None = None
        self.inspections: dict[str, dict] = {}
        self.tool_calls: list[dict] = []
        self.event_history: list[dict] = []
        self.completion: dict | None = None
        self.finalized = False

    @classmethod
    def from_snapshot(cls, snapshot: dict, max_batch_size: int = 12) -> "InspectionRegistry":
        registry = cls(snapshot["scene_id"], snapshot.get("selected_layouts", []), max_batch_size)
        registry.phase = snapshot["phase"]
        registry.regions = deepcopy(snapshot["region_coverage"])
        registry.data_availability = deepcopy(snapshot.get("data_availability", {}))
        registry.evidence_records = deepcopy(snapshot.get("evidence_records", {}))
        registry.evidence_fingerprints = {
            row["evidence_fingerprint"] for row in registry.evidence_records.values()
        }
        registry.stage4_plan = deepcopy(snapshot.get("stage4_plan"))
        registry.inspection_bundles = deepcopy(snapshot.get("inspection_bundles", {}))
        registry.acquisition_attempts = deepcopy(snapshot.get("acquisition_attempts", {}))
        registry.measurement_records = deepcopy(snapshot.get("measurement_records", {}))
        registry.stage4_readiness = deepcopy(snapshot.get("stage4_readiness"))
        registry.stage5_plan = deepcopy(snapshot.get("stage5_plan"))
        registry.conclusion_drafts = deepcopy(snapshot.get("conclusion_drafts", {}))
        registry.stage5_readiness = deepcopy(snapshot.get("stage5_readiness"))
        registry.tool_calls = deepcopy(snapshot.get("tool_calls", []))
        registry.event_history = deepcopy(snapshot.get("event_history", []))
        registry.completion = deepcopy(snapshot.get("completion"))
        registry.finalized = bool(snapshot.get("finalized"))
        normative_fields = {
            "candidate_label", "subject", "modality", "relation", "threshold",
            "applicability_conditions", "required_inputs", "source_node_ids", "source_locator",
            "source_span", "model_extracted_source_span", "measurement_spec",
            "discovered_requirement_key", "region", "requirement_fingerprint",
            "registration_event_index", "registration_timestamp",
        }
        for row in snapshot.get("requirements", []):
            key = row["discovered_requirement_key"]
            requirement = {field: deepcopy(row[field]) for field in normative_fields if field in row}
            registry.requirements[key] = requirement
            registry.requirement_fingerprints[requirement["requirement_fingerprint"]] = key
            if "inspection_event_index" in row:
                registry.inspections[key] = {
                    field: deepcopy(value) for field, value in row.items()
                    if field not in normative_fields and field != "data_availability_record"
                }
        return registry

    def _event(self, event_type: str, **fields: Any) -> dict:
        event = {"event_index": len(self.event_history) + 1, "timestamp": _utc_now(),
                 "event_type": event_type, "phase": self.phase, **deepcopy(fields)}
        self.event_history.append(event)
        return event

    def _require_phase(self, expected: str) -> None:
        if self.phase != expected:
            raise RegistryError(f"phase_violation: expected {expected}, current {self.phase}")

    def begin_requirement_registration(self) -> dict:
        self._require_phase("requirement_discovery")
        event = self._event("phase_transition", from_phase=self.phase,
                            to_phase="requirement_registration")
        self.phase = "requirement_registration"
        return {"phase": self.phase, "transition_event_index": event["event_index"]}

    def _generated_key(self, requirement: dict) -> tuple[str, str]:
        fingerprint = _fingerprint(requirement)
        return f"req_{fingerprint[:16]}", fingerprint

    def submit_requirement_batch(self, region: str, requirements: list[dict]) -> dict:
        self._require_phase("requirement_registration")
        if region not in self.regions:
            raise RegistryError(f"unknown region: {region}")
        if not requirements or len(requirements) > self.max_batch_size:
            raise RegistryError(f"batch size must be between 1 and {self.max_batch_size}")
        pending: list[tuple[str, str, dict]] = []
        pending_fingerprints: set[str] = set()
        for requirement in requirements:
            if _contains_forbidden_requirement_id(requirement):
                raise RegistryError("internal requirement_id is forbidden")
            required = {"candidate_label", "subject", "modality", "relation", "threshold",
                        "applicability_conditions", "required_inputs", "source_node_ids",
                        "source_locator", "source_span", "measurement_spec"}
            missing = required - set(requirement)
            if missing:
                raise RegistryError(f"missing normative fields: {sorted(missing)}")
            if requirement["modality"] not in {"shall", "should"}:
                raise RegistryError("registered modality must be shall (Standard) or should (Guidance)")
            if not requirement["source_node_ids"]:
                raise RegistryError("at least one retrieved source_node_id is required")
            spec = requirement["measurement_spec"]
            if spec.get("required"):
                if spec.get("tool") not in NORMATIVE_MEASUREMENT_TOOLS:
                    raise RegistryError("measurement_spec requires a supported normative measurement tool")
                if not spec.get("thresholds"):
                    raise RegistryError("measurement_spec requires an extracted threshold")
            elif spec.get("tool") is not None or spec.get("thresholds"):
                raise RegistryError("non-measured requirements must not declare a tool or thresholds")
            value = deepcopy(requirement)
            key, fingerprint = self._generated_key(value)
            if (key in self.requirements or fingerprint in self.requirement_fingerprints or
                    fingerprint in pending_fingerprints):
                raise RegistryError(f"duplicate discovered requirement content: {value['candidate_label']}")
            broad = f"{value['subject']} {value['relation']} {value['threshold']}".lower()
            if any(phrase in broad for phrase in ("entire work zone is correct", "overall setup is correct",
                                                   "all traffic control devices are correct")):
                raise RegistryError("broad overall conclusions cannot replace atomic inspection items")
            pending.append((key, fingerprint, value))
            pending_fingerprints.add(fingerprint)
        accepted = []
        for key, fingerprint, value in pending:
            event = self._event("requirement_registered", discovered_requirement_key=key,
                                candidate_label=value["candidate_label"], region=region,
                                requirement_fingerprint=fingerprint)
            stored = {**value, "discovered_requirement_key": key, "region": region,
                      "requirement_fingerprint": fingerprint,
                      "registration_event_index": event["event_index"],
                      "registration_timestamp": event["timestamp"]}
            self.requirements[key] = stored
            self.requirement_fingerprints[fingerprint] = key
            self.regions[region]["requirement_keys"].append(key)
            accepted.append({"candidate_label": value["candidate_label"],
                             "discovered_requirement_key": key,
                             "registration_event_index": event["event_index"],
                             "requirement_fingerprint": fingerprint})
        return {"accepted_requirements": accepted,
                "accepted_requirement_keys": [row["discovered_requirement_key"] for row in accepted],
                "registry_requirement_count": len(self.requirements)}

    def complete_region(self, region: str, status: str, reason: str) -> dict:
        self._require_phase("requirement_registration")
        if region not in self.regions:
            raise RegistryError(f"unknown region: {region}")
        if status not in TERMINAL_REGION_STATES:
            raise RegistryError(f"invalid terminal region status: {status}")
        if status == "skipped_no_inspectable_candidate" and not reason.strip():
            raise RegistryError("a skipped region requires a reason")
        self.regions[region]["status"] = status
        self.regions[region]["reason"] = reason.strip()
        self._event("region_screened", region=region, status=status)
        return {"region": region, "status": status}

    def complete_region_batch(self, regions: list[dict]) -> dict:
        self._require_phase("requirement_registration")
        if not regions or len(regions) > len(REGIONS):
            raise RegistryError("region batch must contain between one and twelve records")
        accepted = []
        for row in regions:
            accepted.append(self.complete_region(row["region"], row["status"], row["reason"]))
        return {"completed_regions": accepted}

    def seal_requirement_registration(self) -> dict:
        self._require_phase("requirement_registration")
        pending = [region for region, row in self.regions.items()
                   if row["status"] not in TERMINAL_REGION_STATES]
        if pending:
            raise RegistryError(f"regions are not screened: {pending}")
        if not self.requirements:
            raise RegistryError("at least one retained requirement is required")
        event = self._event("phase_transition", from_phase=self.phase,
                            to_phase="data_availability")
        self.phase = "data_availability"
        return {"phase": self.phase, "transition_event_index": event["event_index"],
                "frozen_requirement_count": len(self.requirements)}

    def submit_data_availability_batch(self, assessments: list[dict]) -> dict:
        self._require_phase("data_availability")
        if not assessments or len(assessments) > self.max_batch_size:
            raise RegistryError(f"batch size must be between 1 and {self.max_batch_size}")
        accepted = []
        pending: list[tuple[str, dict]] = []
        for assessment in assessments:
            key = assessment.get("discovered_requirement_key", "").strip()
            if key not in self.requirements:
                raise RegistryError(f"data availability references unknown requirement: {key}")
            if key in self.data_availability or key in accepted:
                raise RegistryError(f"duplicate data availability record: {key}")
            state = assessment.get("data_availability")
            if state not in DATA_AVAILABILITY_STATES:
                raise RegistryError(f"invalid data availability for {key}: {state}")
            if state == "unavailable_after_attempt":
                raise RegistryError(
                    "unavailable_after_attempt is a Stage 4 final state; "
                    "Stage 3 must use not_attempted or partial before evidence acquisition"
                )
            required_inputs = set(self.requirements[key]["required_inputs"])
            available_inputs = set(assessment.get("available_inputs", []))
            missing_inputs = set(assessment.get("missing_inputs", []))
            overlap = available_inputs & missing_inputs
            if overlap:
                raise RegistryError(f"available and missing inputs overlap: {sorted(overlap)}")
            declared = available_inputs | missing_inputs
            if declared != required_inputs:
                raise RegistryError(
                    "data availability must exactly partition required inputs; "
                    f"missing={sorted(required_inputs - declared)}, "
                    f"unexpected={sorted(declared - required_inputs)}"
                )
            if state in {"available_direct", "acquired"} and missing_inputs:
                raise RegistryError(f"{state} cannot contain missing inputs")
            if state == "partial" and (not available_inputs or not missing_inputs):
                raise RegistryError("partial requires at least one available and one missing input")
            if state == "not_attempted" and available_inputs:
                raise RegistryError("not_attempted cannot contain available inputs; use partial")
            planned_tools = set(assessment.get("planned_tools", []))
            unknown_tools = planned_tools - PLANNABLE_EVIDENCE_TOOLS
            if unknown_tools:
                raise RegistryError(f"unknown planned tools: {sorted(unknown_tools)}")
            for input_name in missing_inputs:
                eligible_tools = acquisition_tools_for_input(input_name)
                if eligible_tools and not (eligible_tools & planned_tools):
                    raise RegistryError(
                        f"planned tools do not cover missing input {input_name}: "
                        f"expected one of {sorted(eligible_tools)}"
                    )
            measurement_tool = self.requirements[key]["measurement_spec"].get("tool")
            if state not in {"unavailable_after_attempt", "not_attempted"} and measurement_tool and measurement_tool not in planned_tools:
                raise RegistryError(f"planned tools omit registered measurement tool: {measurement_tool}")
            accepted.append(key)
            pending.append((key, deepcopy(assessment)))
        for key, assessment in pending:
            event = self._event("data_availability_recorded", discovered_requirement_key=key,
                                data_availability=assessment["data_availability"])
            self.data_availability[key] = {**assessment,
                                           "availability_event_index": event["event_index"],
                                           "availability_timestamp": event["timestamp"]}
        return {"accepted_data_availability_keys": accepted,
                "data_availability_count": len(self.data_availability)}

    def seal_data_availability(self) -> dict:
        self._require_phase("data_availability")
        missing = sorted(set(self.requirements) - set(self.data_availability))
        if missing:
            raise RegistryError(f"requirements lack data availability records: {missing}")
        event = self._event("phase_transition", from_phase=self.phase, to_phase="measurement")
        self.phase = "measurement"
        return {"phase": self.phase, "transition_event_index": event["event_index"]}

    def record_evidence_batch(self, evidence: list[dict]) -> dict:
        self._require_phase("measurement")
        if not evidence or len(evidence) > self.max_batch_size:
            raise RegistryError(f"batch size must be between 1 and {self.max_batch_size}")
        pending: list[tuple[str, str, dict]] = []
        batch_fingerprints: set[str] = set()
        actual_tools = {row["tool"] for row in self.tool_calls}
        acquired_by_key: dict[str, set[str]] = {key: set() for key in self.requirements}
        unresolved_by_key: dict[str, set[str]] = {key: set() for key in self.requirements}
        for existing in self.evidence_records.values():
            key = existing["discovered_requirement_key"]
            acquired_by_key[key].update(existing.get("acquired_inputs", []))
            unresolved_by_key[key].update(existing.get("unresolved_inputs", []))
        for item in evidence:
            key = item.get("discovered_requirement_key", "").strip()
            if key not in self.requirements:
                raise RegistryError(f"evidence references unknown requirement: {key}")
            kind = item.get("evidence_kind")
            if kind not in EVIDENCE_KINDS:
                raise RegistryError(f"invalid evidence kind for {key}: {kind}")
            required = set(self.requirements[key]["required_inputs"])
            acquired = set(item.get("acquired_inputs", []))
            unresolved = set(item.get("unresolved_inputs", []))
            if acquired & unresolved:
                raise RegistryError(f"evidence acquired and unresolved inputs overlap: {sorted(acquired & unresolved)}")
            cross_record_overlap = (
                (acquired & unresolved_by_key[key]) |
                (unresolved & acquired_by_key[key])
            )
            if cross_record_overlap:
                raise RegistryError(
                    f"evidence conflicts with previously recorded input status: {sorted(cross_record_overlap)}"
                )
            unexpected = (acquired | unresolved) - required
            if unexpected:
                raise RegistryError(f"evidence references unexpected required inputs: {sorted(unexpected)}")
            tools_used = set(item.get("tools_used", []))
            unknown_tools = tools_used - PLANNABLE_EVIDENCE_TOOLS
            if unknown_tools:
                raise RegistryError(f"evidence names unknown tools: {sorted(unknown_tools)}")
            if not tools_used.issubset(actual_tools):
                raise RegistryError(f"evidence claims tools not actually called: {sorted(tools_used - actual_tools)}")
            source_ids = item.get("source_ids", [])
            if kind != "acquisition_failure" and not source_ids:
                raise RegistryError(f"{kind} evidence requires at least one source ID")
            if kind == "visual_observation" and not (
                {"inspect_temporal_images", "inspect_observation_images"} & tools_used
            ):
                raise RegistryError("visual evidence requires an image-inspection tool")
            if kind == "measurement_context" and not (NORMATIVE_MEASUREMENT_TOOLS & tools_used):
                raise RegistryError("measurement evidence requires a normative measurement tool")
            if (kind == "acquisition_failure" and not tools_used and not
                    all(str(source_id).startswith("attempt_") for source_id in source_ids)):
                raise RegistryError(
                    "acquisition failure requires an attempted tool or a persisted blocked attempt"
                )
            fingerprint_payload = {
                "key": key, "kind": kind, "sources": sorted(source_ids),
                "acquired": sorted(acquired), "unresolved": sorted(unresolved),
                "finding": item.get("finding", "").strip(),
            }
            fingerprint = hashlib.sha256(json.dumps(
                fingerprint_payload, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()
            if fingerprint in self.evidence_fingerprints or fingerprint in batch_fingerprints:
                raise RegistryError(f"duplicate evidence record for {key}")
            evidence_id = f"evidence_{fingerprint[:20]}"
            batch_fingerprints.add(fingerprint)
            pending.append((evidence_id, fingerprint, deepcopy(item)))
            acquired_by_key[key].update(acquired)
            unresolved_by_key[key].update(unresolved)
        accepted = []
        for evidence_id, fingerprint, item in pending:
            event = self._event(
                "evidence_recorded",
                discovered_requirement_key=item["discovered_requirement_key"],
                evidence_id=evidence_id,
                evidence_kind=item["evidence_kind"],
            )
            self.evidence_records[evidence_id] = {
                **item, "evidence_id": evidence_id, "evidence_fingerprint": fingerprint,
                "evidence_event_index": event["event_index"], "evidence_timestamp": event["timestamp"],
            }
            self.evidence_fingerprints.add(fingerprint)
            accepted.append(evidence_id)
        return {"accepted_evidence_ids": accepted,
                "evidence_record_count": len(self.evidence_records)}

    def set_stage4_plan(self, plan: dict) -> dict:
        self._require_phase("measurement")
        if self.stage4_plan is not None:
            if self.stage4_plan.get("plan_id") != plan.get("plan_id"):
                raise RegistryError("a different Stage 4 acquisition plan is already frozen")
            return deepcopy(self.stage4_plan)
        event = self._event("stage4_plan_frozen", plan_id=plan.get("plan_id"))
        self.stage4_plan = {
            **deepcopy(plan),
            "plan_event_index": event["event_index"],
            "plan_timestamp": event["timestamp"],
        }
        return deepcopy(self.stage4_plan)

    def record_inspection_bundle(self, bundle: dict) -> dict:
        self._require_phase("measurement")
        bundle_id = str(bundle.get("inspection_bundle_id") or "").strip()
        if not bundle_id:
            raise RegistryError("inspection bundle requires an ID")
        if bundle_id in self.inspection_bundles:
            return deepcopy(self.inspection_bundles[bundle_id])
        event = self._event(
            "inspection_bundle_recorded",
            inspection_bundle_id=bundle_id,
            visual_job_id=bundle.get("visual_job_id"),
        )
        stored = {
            **deepcopy(bundle),
            "bundle_event_index": event["event_index"],
            "bundle_timestamp": event["timestamp"],
        }
        self.inspection_bundles[bundle_id] = stored
        return deepcopy(stored)

    def record_inspection_bundle_note(self, bundle_id: str, finding: str,
                                      limitations: str) -> dict:
        self._require_phase("measurement")
        if bundle_id not in self.inspection_bundles:
            raise RegistryError("unknown inspection bundle")
        bundle = self.inspection_bundles[bundle_id]
        if bundle.get("model_observation") is not None:
            return deepcopy(bundle)
        event = self._event(
            "inspection_bundle_note_recorded", inspection_bundle_id=bundle_id
        )
        bundle["model_observation"] = {
            "finding": finding.strip(),
            "limitations": limitations.strip(),
            "note_event_index": event["event_index"],
            "note_timestamp": event["timestamp"],
        }
        return deepcopy(bundle)

    def record_stage4_readiness(self, readiness: dict) -> dict:
        self._require_phase("measurement")
        event = self._event("stage4_readiness_checked", ready=readiness.get("ready"))
        self.stage4_readiness = {
            **deepcopy(readiness),
            "readiness_event_index": event["event_index"],
            "readiness_timestamp": event["timestamp"],
        }
        return deepcopy(self.stage4_readiness)

    def record_acquisition_attempt(self, attempt: dict) -> dict:
        self._require_phase("measurement")
        attempt_id = str(attempt.get("attempt_id") or "").strip()
        if not attempt_id:
            raise RegistryError("acquisition attempt requires an ID")
        if attempt_id in self.acquisition_attempts:
            return deepcopy(self.acquisition_attempts[attempt_id])
        event = self._event(
            "acquisition_attempt_recorded",
            attempt_id=attempt_id,
            measurement_job_id=attempt.get("measurement_job_id"),
            status=attempt.get("status"),
        )
        stored = {
            **deepcopy(attempt),
            "attempt_event_index": event["event_index"],
            "attempt_timestamp": event["timestamp"],
        }
        self.acquisition_attempts[attempt_id] = stored
        return deepcopy(stored)

    def validate_measurement_request(self, key: str, tool_name: str) -> tuple[dict, dict]:
        if self.phase != "measurement":
            raise RegistryError("measurement_before_requirement_registration")
        if key not in self.requirements:
            raise RegistryError("measurement_before_requirement_registration")
        requirement = self.requirements[key]
        availability = self.data_availability.get(key)
        if not availability:
            raise RegistryError("measurement_before_data_availability")
        if availability["data_availability"] in {"unavailable_after_attempt", "not_attempted"}:
            raise RegistryError("measurement_for_unavailable_requirement")
        spec = requirement["measurement_spec"]
        if not spec.get("required") or spec.get("tool") != tool_name:
            raise RegistryError("requirement_does_not_declare_requested_measurement")
        return requirement, availability

    def bind_measurement(self, key: str, tool_name: str, measurement: dict) -> dict:
        requirement, _ = self.validate_measurement_request(key, tool_name)
        if measurement.get("status") == "failure":
            return measurement
        event = self._event("measurement_recorded", discovered_requirement_key=key,
                            tool=tool_name, measurement_id=measurement.get("measurement_id"))
        if requirement["registration_event_index"] >= event["event_index"]:
            raise RegistryError("measurement_before_requirement_registration")
        bound = {**measurement, "discovered_requirement_key": key,
                 "requirement_fingerprint": requirement["requirement_fingerprint"],
                 "requirement_registration_event_index": requirement["registration_event_index"],
                 "requirement_registration_timestamp": requirement["registration_timestamp"],
                 "measurement_event_index": event["event_index"],
                 "measurement_timestamp": event["timestamp"],
                 "registered_source_locator": requirement["source_locator"]}
        if bound.get("measurement_id"):
            self.measurement_records[bound["measurement_id"]] = deepcopy(bound)
        return bound

    def seal_measurements(self) -> dict:
        self._require_phase("measurement")
        by_requirement: dict[str, list[dict]] = {key: [] for key in self.requirements}
        for evidence in self.evidence_records.values():
            by_requirement[evidence["discovered_requirement_key"]].append(evidence)
        missing_evidence = sorted(key for key, rows in by_requirement.items() if not rows)
        if missing_evidence:
            raise RegistryError(f"requirements lack Stage 4 evidence records: {missing_evidence}")
        for key, rows in by_requirement.items():
            accounted = {
                value for row in rows
                for value in row.get("acquired_inputs", []) + row.get("unresolved_inputs", [])
            }
            required = set(self.requirements[key]["required_inputs"])
            if accounted != required:
                raise RegistryError(
                    f"Stage 4 evidence must account for every required input for {key}: "
                    f"missing={sorted(required - accounted)}, unexpected={sorted(accounted - required)}"
                )
            measurement_tool = self.requirements[key]["measurement_spec"].get("tool")
            if measurement_tool:
                attempted = any(
                    row["tool"] == measurement_tool and row.get("discovered_requirement_key") == key
                    for row in self.tool_calls
                )
                documented_block = any(
                    attempt.get("tool") == measurement_tool
                    and attempt.get("discovered_requirement_key") == key
                    and attempt.get("measurement_job_id")
                    and attempt.get("status") == "blocked_before_call"
                    and attempt.get("failure_reason")
                    and any(e.get("acquisition_attempt_id") == attempt.get("attempt_id")
                            and e.get("evidence_kind") == "acquisition_failure"
                            for e in self.evidence_records.values())
                    for attempt in self.acquisition_attempts.values()
                )
                if not attempted and not documented_block:
                    raise RegistryError(f"registered measurement tool was not attempted for {key}: {measurement_tool}")
        event = self._event("phase_transition", from_phase=self.phase,
                            to_phase="inspection_conclusion")
        self.phase = "inspection_conclusion"
        return {"phase": self.phase, "transition_event_index": event["event_index"]}

    def begin_result_submission(self) -> dict:
        self._require_phase("inspection_conclusion")
        event = self._event("phase_transition", from_phase=self.phase,
                            to_phase="result_submission")
        self.phase = "result_submission"
        return {"phase": self.phase, "transition_event_index": event["event_index"]}

    def set_stage5_plan(self, plan: dict) -> dict:
        self._require_phase("inspection_conclusion")
        if self.stage5_plan is not None:
            if self.stage5_plan.get("plan_id") != plan.get("plan_id"):
                raise RegistryError("a different Stage 5 conclusion plan is already frozen")
            return deepcopy(self.stage5_plan)
        event = self._event("stage5_plan_frozen", plan_id=plan.get("plan_id"))
        self.stage5_plan = {
            **deepcopy(plan),
            "plan_event_index": event["event_index"],
            "plan_timestamp": event["timestamp"],
        }
        return deepcopy(self.stage5_plan)

    def record_conclusion_draft_batch(self, conclusions: list[dict]) -> dict:
        self._require_phase("inspection_conclusion")
        if not conclusions or len(conclusions) > self.max_batch_size:
            raise RegistryError(f"batch size must be between 1 and {self.max_batch_size}")
        keys = [row.get("discovered_requirement_key") for row in conclusions]
        if len(keys) != len(set(keys)):
            raise RegistryError("duplicate requirement in conclusion batch")
        for key in keys:
            if key not in self.requirements:
                raise RegistryError(f"conclusion references unknown requirement: {key}")
            if key in self.conclusion_drafts:
                raise RegistryError(f"duplicate conclusion draft: {key}")
        accepted = []
        for row in conclusions:
            key = row["discovered_requirement_key"]
            event = self._event(
                "conclusion_draft_recorded",
                discovered_requirement_key=key,
                inspection_status=row.get("inspection_status"),
            )
            self.conclusion_drafts[key] = {
                **deepcopy(row),
                "conclusion_event_index": event["event_index"],
                "conclusion_timestamp": event["timestamp"],
            }
            accepted.append(key)
        return {
            "accepted_conclusion_keys": accepted,
            "conclusion_draft_count": len(self.conclusion_drafts),
        }

    def record_stage5_readiness(self, readiness: dict) -> dict:
        self._require_phase("inspection_conclusion")
        event = self._event("stage5_readiness_checked", ready=readiness.get("ready"))
        self.stage5_readiness = {
            **deepcopy(readiness),
            "readiness_event_index": event["event_index"],
            "readiness_timestamp": event["timestamp"],
        }
        return deepcopy(self.stage5_readiness)

    def seal_conclusions(self) -> dict:
        self._require_phase("inspection_conclusion")
        missing = sorted(set(self.requirements) - set(self.conclusion_drafts))
        if missing:
            raise RegistryError(f"requirements lack conclusion drafts: {missing}")
        if not (self.stage5_readiness or {}).get("ready"):
            raise RegistryError("Stage 5 readiness must pass before conclusions are sealed")
        event = self._event("phase_transition", from_phase=self.phase,
                            to_phase="result_submission")
        self.phase = "result_submission"
        return {"phase": self.phase, "transition_event_index": event["event_index"]}

    def record_tool_call(self, name: str, result: dict, discovered_requirement_key: str | None = None) -> None:
        event = self._event("tool_called", tool=name,
                            discovered_requirement_key=discovered_requirement_key,
                            status=result.get("status", "returned"))
        self.tool_calls.append({"tool": name, "status": result.get("status", "returned"),
                                "event_index": event["event_index"],
                                "timestamp": event["timestamp"],
                                "discovered_requirement_key": discovered_requirement_key})

    def submit_inspection_batch(self, inspections: list[dict]) -> dict:
        self._require_phase("result_submission")
        if not inspections or len(inspections) > self.max_batch_size:
            raise RegistryError(f"batch size must be between 1 and {self.max_batch_size}")
        accepted = []
        pending: list[tuple[str, dict]] = []
        for inspection in inspections:
            key = inspection.get("discovered_requirement_key", "").strip()
            if key not in self.requirements:
                raise RegistryError(f"inspection references unknown requirement: {key}")
            if key in self.inspections or key in accepted:
                raise RegistryError(f"duplicate inspection result: {key}")
            status = inspection.get("inspection_status")
            if status not in INSPECTION_STATUSES:
                raise RegistryError(f"invalid inspection status for {key}: {status}")
            evidence = (inspection.get("evidence_ids", []) + inspection.get("derivation_evidence_ids", []) +
                        inspection.get("external_evidence_ids", []) + inspection.get("measurement_ids", []))
            if status in {"satisfied", "deficient"} and not evidence:
                raise RegistryError(f"checked item must cite evidence: {key}")
            availability = inspection.get("final_data_availability")
            if availability not in DATA_AVAILABILITY_STATES:
                raise RegistryError(f"invalid final_data_availability for {key}: {availability}")
            called = set(inspection.get("tools_called", []))
            actual = {row["tool"] for row in self.tool_calls}
            if not called.issubset(actual):
                raise RegistryError(f"inspection claims tools that were not actually called: {sorted(called - actual)}")
            attempts = inspection.get("acquisition_attempts", [])
            if availability == "unavailable_after_attempt" and not attempts:
                raise RegistryError(f"unavailable_after_attempt requires recorded attempts: {key}")
            unresolved = set(inspection.get("unresolved_inputs", []))
            for input_name in unresolved:
                eligible = ACQUISITION_TOOLS.get(input_name)
                if availability == "unavailable_after_attempt" and eligible and not (eligible & actual):
                    raise RegistryError(f"recoverable input {input_name} cannot be unavailable_after_attempt without an acquisition tool")
            if availability == "not_attempted" and status != "not_assessed":
                raise RegistryError(f"not_attempted cannot support an explicit conclusion: {key}")
            if status in {"satisfied", "deficient"} and availability not in {"available_direct", "acquired"}:
                raise RegistryError(f"checked item lacks acquired/direct data: {key}")
            accepted.append(key)
            pending.append((key, deepcopy(inspection)))
        for key, value in pending:
            event = self._event("inspection_submitted", discovered_requirement_key=key,
                                inspection_status=value["inspection_status"])
            self.inspections[key] = {**value, "inspection_event_index": event["event_index"],
                                     "inspection_timestamp": event["timestamp"]}
        return {"accepted_inspection_keys": accepted,
                "registry_inspection_count": len(self.inspections)}

    def finalize(self, completion: dict) -> dict:
        self._require_phase("result_submission")
        missing = sorted(set(self.requirements) - set(self.inspections))
        if missing:
            raise RegistryError(f"requirements lack submitted inspection records: {missing}")
        required = {"stop_reason", "searched_layouts", "searched_regions", "followed_cross_references",
                    "unresolved_queries", "remaining_potentially_checkable_items",
                    "agent_declared_completion_status"}
        if required - set(completion):
            raise RegistryError(f"completion fields missing: {sorted(required - set(completion))}")
        self.completion = deepcopy(completion)
        self._event("registry_finalized", completion_status=completion["agent_declared_completion_status"])
        self.phase = "finalized"
        self.finalized = True
        return self.snapshot()

    def assert_measurement_order(self) -> None:
        registrations = {row["discovered_requirement_key"]: row["registration_event_index"]
                         for row in self.requirements.values()}
        for event in self.event_history:
            if event["event_type"] != "measurement_recorded":
                continue
            key = event.get("discovered_requirement_key")
            if key not in registrations or registrations[key] >= event["event_index"]:
                raise RegistryError("measurement_before_requirement_registration")

    def snapshot(self) -> dict:
        rows = []
        for key, requirement in self.requirements.items():
            rows.append({**deepcopy(requirement),
                         "data_availability_record": deepcopy(self.data_availability.get(key)),
                         **deepcopy(self.inspections.get(key, {
                             "final_data_availability": "not_attempted", "image_assessable": False,
                             "inspection_status": "not_assessed", "evidence_ids": [],
                             "inspection_reason": "No inspection batch was submitted for this candidate.",
                         }))})
        return {"scene_id": self.scene_id, "selected_layouts": deepcopy(self.selected_layouts),
                "phase": self.phase, "region_coverage": deepcopy(self.regions),
                "requirements": rows, "data_availability": deepcopy(self.data_availability),
                "evidence_records": deepcopy(self.evidence_records),
                "stage4_plan": deepcopy(self.stage4_plan),
                "inspection_bundles": deepcopy(self.inspection_bundles),
                "acquisition_attempts": deepcopy(self.acquisition_attempts),
                "measurement_records": deepcopy(self.measurement_records),
                "stage4_readiness": deepcopy(self.stage4_readiness),
                "stage5_plan": deepcopy(self.stage5_plan),
                "conclusion_drafts": deepcopy(self.conclusion_drafts),
                "stage5_readiness": deepcopy(self.stage5_readiness),
                "tool_calls": deepcopy(self.tool_calls), "event_history": deepcopy(self.event_history),
                "completion": deepcopy(self.completion), "finalized": self.finalized}


def registry_tool_definitions() -> list[dict[str, Any]]:
    nullable_string = {"type": ["string", "null"]}
    threshold_rule = {
        "type": "object", "additionalProperties": False,
        "required": ["condition", "value", "unit", "violation_when", "formula_parameter", "multiplier"],
        "properties": {
            "condition": {"type": "string"}, "value": {"type": ["number", "null"]},
            "unit": {"enum": ["m", "ft"]},
            "violation_when": {"enum": ["below_minimum", "above_maximum"]},
            "formula_parameter": nullable_string, "multiplier": {"type": ["number", "null"]},
        },
    }
    measurement_spec = {
        "type": "object", "additionalProperties": False,
        "required": ["required", "tool", "quantity", "thresholds"],
        "properties": {
            "required": {"type": "boolean"},
            "tool": {"enum": sorted(NORMATIVE_MEASUREMENT_TOOLS) + [None]},
            "quantity": nullable_string,
            "thresholds": {"type": "array", "items": threshold_rule},
        },
    }
    normative = {
        "type": "object", "additionalProperties": False,
        "required": ["candidate_label", "subject", "modality", "relation", "threshold",
                     "applicability_conditions", "required_inputs", "source_node_ids",
                     "source_locator", "source_span", "measurement_spec"],
        "properties": {
            "candidate_label": {"type": "string"}, "subject": {"type": "string"},
            "modality": {"enum": ["shall", "should"]}, "relation": {"type": "string"},
            "threshold": {"type": "string"},
            "applicability_conditions": {"type": "array", "items": {"type": "string"}},
            "required_inputs": {"type": "array", "items": {"type": "string"}},
            "source_node_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "source_locator": {"type": "string"}, "source_span": {"type": "string"},
            "measurement_spec": measurement_spec,
        },
    }
    data_record = {
        "type": "object", "additionalProperties": False,
        "required": ["discovered_requirement_key", "condition_data_complete", "available_inputs",
                     "missing_inputs", "data_availability", "basis_evidence_ids", "reason",
                     "planned_tools", "planned_evidence_strategy", "planned_decision_rule"],
        "properties": {
            "discovered_requirement_key": {"type": "string"},
            "condition_data_complete": {"type": "boolean"},
            "available_inputs": {"type": "array", "items": {"type": "string"}},
            "missing_inputs": {"type": "array", "items": {"type": "string"}},
            "data_availability": {"enum": sorted(DATA_AVAILABILITY_STATES)},
            "basis_evidence_ids": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
            "planned_tools": {"type": "array", "items": {"enum": sorted(PLANNABLE_EVIDENCE_TOOLS)}},
            "planned_evidence_strategy": {"type": "string"},
            "planned_decision_rule": {"type": "string"},
        },
    }
    evidence_record = {
        "type": "object", "additionalProperties": False,
        "required": ["discovered_requirement_key", "evidence_kind", "source_ids",
                     "acquired_inputs", "unresolved_inputs", "finding", "limitations", "tools_used"],
        "properties": {
            "discovered_requirement_key": {"type": "string"},
            "evidence_kind": {"enum": sorted(EVIDENCE_KINDS)},
            "source_ids": {"type": "array", "items": {"type": "string"}},
            "acquired_inputs": {"type": "array", "items": {"type": "string"}},
            "unresolved_inputs": {"type": "array", "items": {"type": "string"}},
            "finding": {"type": "string"}, "limitations": {"type": "string"},
            "tools_used": {"type": "array", "items": {"enum": sorted(PLANNABLE_EVIDENCE_TOOLS)}},
        },
    }
    inspection = {
        "type": "object", "additionalProperties": False,
        "required": ["discovered_requirement_key", "normative_applicability", "acquisition_plan",
                     "acquisition_attempts", "tools_called", "acquired_inputs", "derivation_evidence_ids",
                     "external_evidence_ids", "unresolved_inputs", "final_data_availability", "failure_reason",
                     "image_assessable", "inspection_status", "evidence_ids", "measurement_ids",
                     "inspection_reason", "requires_human_review"],
        "properties": {
            "discovered_requirement_key": {"type": "string"},
            "normative_applicability": {"enum": ["true", "false", "indeterminate"]},
            "acquisition_plan": {"type": "array", "items": {"type": "string"}},
            "acquisition_attempts": {"type": "array", "items": {"type": "string"}},
            "tools_called": {"type": "array", "items": {"type": "string"}},
            "acquired_inputs": {"type": "array", "items": {"type": "string"}},
            "derivation_evidence_ids": {"type": "array", "items": {"type": "string"}},
            "external_evidence_ids": {"type": "array", "items": {"type": "string"}},
            "unresolved_inputs": {"type": "array", "items": {"type": "string"}},
            "final_data_availability": {"enum": sorted(DATA_AVAILABILITY_STATES)},
            "failure_reason": {"type": ["string", "null"]}, "image_assessable": {"type": "boolean"},
            "inspection_status": {"enum": sorted(INSPECTION_STATUSES)},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "measurement_ids": {"type": "array", "items": {"type": "string"}},
            "inspection_reason": {"type": "string"}, "requires_human_review": {"type": "boolean"},
        },
    }
    transition = lambda name, description: {
        "type": "function", "name": name, "strict": True, "description": description,
        "parameters": {"type": "object", "additionalProperties": False, "properties": {}, "required": []},
    }
    region_item = {"type": "object", "additionalProperties": False,
                   "required": ["region", "status", "reason"],
                   "properties": {"region": {"enum": list(REGIONS)},
                                  "status": {"enum": sorted(TERMINAL_REGION_STATES)},
                                  "reason": {"type": "string"}}}
    return [
        transition("begin_requirement_registration", "End manual discovery and begin registering the retained requirements."),
        {"type": "function", "name": "submit_requirement_batch", "strict": True,
         "description": "Register up to twelve atomic requirements extracted from already retrieved source nodes. The registry returns run-local keys.",
         "parameters": {"type": "object", "additionalProperties": False,
                        "required": ["region", "requirements"],
                        "properties": {"region": {"enum": list(REGIONS)},
                                       "requirements": {"type": "array", "minItems": 1,
                                                        "maxItems": 12, "items": normative}}}},
        {"type": "function", "name": "complete_region_batch", "strict": True,
         "description": "Record screening status for one to twelve manual regions before requirement registration is sealed.",
         "parameters": {"type": "object", "additionalProperties": False, "required": ["regions"],
                        "properties": {"regions": {"type": "array", "minItems": 1,
                                                   "maxItems": 12, "items": region_item}}}},
        transition("seal_requirement_registration", "Freeze the registered requirement set and begin data-availability assessment."),
        {"type": "function", "name": "submit_data_availability_batch", "strict": True,
         "description": "Record availability of every required input before visual or geometric measurement begins.",
         "parameters": {"type": "object", "additionalProperties": False, "required": ["assessments"],
                        "properties": {"assessments": {"type": "array", "minItems": 1,
                                                       "maxItems": 12, "items": data_record}}}},
        transition("seal_data_availability", "Freeze data-availability decisions and begin evidence acquisition and measurement."),
        {"type": "function", "name": "record_evidence_batch", "strict": True,
         "description": "Persist factual Stage 4 findings and acquisition failures, bound to registered requirements, before conclusions are formed.",
         "parameters": {"type": "object", "additionalProperties": False, "required": ["evidence"],
                        "properties": {"evidence": {"type": "array", "minItems": 1,
                                                      "maxItems": 12, "items": evidence_record}}}},
        transition("seal_measurements", "End evidence acquisition and measurement and begin forming inspection conclusions."),
        transition("begin_result_submission", "Finish forming conclusions and begin submitting structured inspection results."),
        {"type": "function", "name": "submit_inspection_batch", "strict": True,
         "description": "Submit evidence-backed or explicitly not-assessed results for up to twelve registered requirements.",
         "parameters": {"type": "object", "additionalProperties": False, "required": ["inspections"],
                        "properties": {"inspections": {"type": "array", "minItems": 1,
                                                       "maxItems": 12, "items": inspection}}}},
        {"type": "function", "name": "finalize_registry", "strict": True,
         "description": "Finalize after every frozen requirement has one submitted result.",
         "parameters": {"type": "object", "additionalProperties": False, "required": ["completion"],
                        "properties": {"completion": {"type": "object", "additionalProperties": False,
                            "required": ["stop_reason", "searched_layouts", "searched_regions",
                                         "followed_cross_references", "unresolved_queries",
                                         "remaining_potentially_checkable_items", "agent_declared_completion_status"],
                            "properties": {"stop_reason": {"type": "string"},
                                "searched_layouts": {"type": "array", "items": {"type": "string"}},
                                "searched_regions": {"type": "array", "items": {"type": "string"}},
                                "followed_cross_references": {"type": "array", "items": {"type": "string"}},
                                "unresolved_queries": {"type": "array", "items": {"type": "string"}},
                                "remaining_potentially_checkable_items": {"type": "array", "items": {"type": "string"}},
                                "agent_declared_completion_status": {"enum": ["complete", "incomplete"]}}}}}},
    ]
