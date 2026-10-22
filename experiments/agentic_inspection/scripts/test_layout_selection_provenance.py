"""User-selected layouts must not be reported as autonomous model choices."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from run_srag_bm25_v5 import layout_selection_metadata


class LayoutSelectionProvenanceTest(unittest.TestCase):
    def test_new_autonomous_run_keeps_unsupplied_layout(self):
        result = layout_selection_metadata({}, "scene-test")
        self.assertFalse(result["correct_layout_page_region_or_target_supplied"])
        self.assertEqual(result["layout_selection_origin"], "model_selected")

    def test_resume_preserves_user_origin_and_rejects_different_scene(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "stage0.json"
            path.write_text(json.dumps({
                "scene_id": "scene-test",
                "selection_provenance": {"origin": "user_directed"},
            }))
            cfg = {"execution": {"resume_stage0_record": str(path)}}
            result = layout_selection_metadata(cfg, "scene-test")
            self.assertTrue(result["correct_layout_page_region_or_target_supplied"])
            self.assertEqual(result["layout_selection_origin"], "user_directed")
            self.assertEqual(len(result["layout_selection_record_sha256"]), 64)
            with self.assertRaisesRegex(ValueError, "different scene"):
                layout_selection_metadata(cfg, "scene-other")

    def test_legacy_model_resume_does_not_become_user_supplied(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "stage0.json"
            path.write_text(json.dumps({"scene_id": "scene-test"}))
            result = layout_selection_metadata(
                {"execution": {"resume_stage0_record": str(path)}}, "scene-test")
            self.assertFalse(result["correct_layout_page_region_or_target_supplied"])


if __name__ == "__main__":
    unittest.main()
