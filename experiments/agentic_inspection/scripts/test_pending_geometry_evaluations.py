#!/usr/bin/env python3

import unittest

from complete_pending_geometry_evaluations import evaluate_formula, normative_digest


class PendingGeometryEvaluationTests(unittest.TestCase):
    def test_mutcd_formula_is_evaluated_from_named_inputs(self) -> None:
        self.assertEqual(evaluate_formula("W*S^2/60", {"W": 10, "S": 30}), 150)

    def test_formula_rejects_calls(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_formula("max(W, S)", {"W": 10, "S": 30})

    def test_outcome_change_does_not_change_stage2_digest(self) -> None:
        requirement = {
            "discovered_requirement_key": "req_1",
            "candidate_label": "example",
            "inspection_status": "not_assessed",
        }
        before = normative_digest([requirement])
        requirement["inspection_status"] = "satisfied"
        self.assertEqual(before, normative_digest([requirement]))


if __name__ == "__main__":
    unittest.main()
