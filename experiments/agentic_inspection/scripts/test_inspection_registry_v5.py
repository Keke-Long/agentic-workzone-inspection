#!/usr/bin/env python3
"""Small unit tests for the current requirement-registration boundary."""

from __future__ import annotations

import unittest

from inspection_registry_v5 import (
    acquisition_tools_for_input,
    InspectionRegistry,
    REGIONS,
    RegistryError,
    registry_tool_definitions,
)


class InspectionRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = InspectionRegistry("scene-1", [{"layout_code": "TA-30"}])
        self.registry.begin_requirement_registration()
        self.requirement = {
            "candidate_label": "TEST-01",
            "subject": "Channelizing-device condition",
            "modality": "shall",
            "relation": "shall be serviceable",
            "threshold": "No unserviceable device",
            "applicability_conditions": ["Channelizing devices are deployed"],
            "required_inputs": ["Observed device condition"],
            "source_node_ids": ["src_test"],
            "source_locator": "MUTCD Section 6K.01 paragraph 15; PDF page 855",
            "source_span": "Channelizing devices that are no longer serviceable shall be replaced.",
            "measurement_spec": {
                "required": False,
                "tool": None,
                "quantity": None,
                "thresholds": [],
            },
        }

    def test_registration_generates_internal_key(self):
        result = self.registry.submit_requirement_batch(
            "channelization_system", [self.requirement]
        )
        key = result["accepted_requirement_keys"][0]
        self.assertTrue(key.startswith("req_"))
        self.assertIn(key, self.registry.requirements)

    def test_duplicate_content_is_rejected(self):
        self.registry.submit_requirement_batch("channelization_system", [self.requirement])
        with self.assertRaisesRegex(RegistryError, "duplicate"):
            self.registry.submit_requirement_batch("channelization_system", [self.requirement])

    def test_requirement_batch_is_atomic(self):
        with self.assertRaises(RegistryError):
            self.registry.submit_requirement_batch(
                "channelization_system", [self.requirement, self.requirement]
            )
        self.assertEqual(self.registry.requirements, {})

    def test_internal_requirement_id_is_rejected(self):
        value = {**self.requirement, "requirement_id": "HIDDEN-01"}
        with self.assertRaisesRegex(RegistryError, "requirement_id"):
            self.registry.submit_requirement_batch("channelization_system", [value])

    def test_only_standard_or_guidance_can_be_registered(self):
        value = {**self.requirement, "modality": "may"}
        with self.assertRaisesRegex(RegistryError, "shall.*should"):
            self.registry.submit_requirement_batch("channelization_system", [value])

    def test_measurement_schema_is_guarded(self):
        value = {
            **self.requirement,
            "measurement_spec": {
                "required": False,
                "tool": "audit_channelizer_spacing",
                "quantity": "spacing",
                "thresholds": [],
            },
        }
        with self.assertRaisesRegex(RegistryError, "non-measured"):
            self.registry.submit_requirement_batch("channelization_system", [value])

    def test_seal_requires_every_region_screened(self):
        self.registry.submit_requirement_batch("channelization_system", [self.requirement])
        with self.assertRaisesRegex(RegistryError, "not screened"):
            self.registry.seal_requirement_registration()
        for region in REGIONS:
            self.registry.complete_region(region, "screened", "Screened in unit test.")
        result = self.registry.seal_requirement_registration()
        self.assertEqual(result["phase"], "data_availability")

    def test_finalize_is_illegal_during_registration(self):
        with self.assertRaisesRegex(RegistryError, "result_submission"):
            self.registry.finalize({})

    def test_tool_schemas_expose_no_hidden_id(self):
        self.assertNotIn("requirement_id", str(registry_tool_definitions()))

    def test_visual_input_modalities_have_a_general_stage4_route(self):
        expected = {"inspect_temporal_images", "inspect_observation_images"}
        for input_name in (
            "raw_images", "traffic_sign_observations", "accepted_bbox_observations",
            "channelization_region", "field view of lane boundaries",
        ):
            with self.subTest(input_name=input_name):
                self.assertEqual(acquisition_tools_for_input(input_name), expected)


if __name__ == "__main__":
    unittest.main()
