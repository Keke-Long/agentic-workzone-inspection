"""Regression checks for cross-case evidence and deployment isolation."""
import unittest

from preflight_srag_bm25_v5 import deployment_inventory_consistent, scene_source_path
from scene_data_tools_v5 import SceneDataToolsV5
from test_srag_bm25_v5 import setup_spacing_gateway


class NewCasePreflightTest(unittest.TestCase):
    def test_deployment_is_scene_specific_and_absence_is_unknown(self):
        for arrow_count, pcms_count in [(0, 0), (1, 0), (0, 2), (2, 3)]:
            manifest = {
                'counts': {'accepted_arrow_board_observations': arrow_count,
                           'accepted_pcms_observations': pcms_count},
                'derived_scene_facts': {'arrow_board_deployed': True if arrow_count else None,
                                        'pcms_deployed': True if pcms_count else None},
            }
            self.assertTrue(deployment_inventory_consistent(manifest))
            manifest['derived_scene_facts']['arrow_board_deployed'] = False
            self.assertFalse(deployment_inventory_consistent(manifest))

    def test_new_scene_cannot_fall_back_to_old_evidence(self):
        with self.assertRaisesRegex(ValueError, 'scene-specific'):
            scene_source_path({'scene_id': 'scene-CATS-19'}, {'reviewed_bboxes': '/old.csv'}, 'reviewed_bboxes')
        path = scene_source_path({'scene_id': 'scene-CATS-19',
                                  'data_sources': {'reviewed_bboxes': '/new.csv'}},
                                 {'reviewed_bboxes': '/old.csv'}, 'reviewed_bboxes')
        self.assertEqual(str(path), '/new.csv')

    def test_empty_reviewed_inventory_is_not_advertised_as_available(self):
        scene = SceneDataToolsV5()
        self.assertIn('accepted_bbox_observations', scene.manifest()['available_direct'])
        scene.observations.clear()
        self.assertNotIn('accepted_bbox_observations', scene.manifest()['available_direct'])
        self.assertEqual(scene.manifest()['counts']['accepted_bbox_observations'], 0)

    def test_stage3_rejects_empty_bbox_inventory_without_registering_claim(self):
        gateway, key = setup_spacing_gateway()
        gateway.registry.phase = 'data_availability'
        gateway.registry.data_availability.clear()
        gateway.registry.requirements[key]['required_inputs'] = ['accepted_bbox_observations']
        gateway.registry.requirements[key]['measurement_spec'] = {'required': False, 'tool': None}
        gateway.scene.observations.clear()
        assessment = {
            'discovered_requirement_key': key, 'condition_data_complete': True,
            'available_inputs': ['accepted_bbox_observations'], 'missing_inputs': [],
            'data_availability': 'available_direct', 'basis_evidence_ids': ['scene_data_manifest'],
            'reason': 'Test unsupported availability claim',
            'planned_tools': ['inspect_temporal_images'],
            'planned_evidence_strategy': 'Acquire missing visual evidence.',
            'planned_decision_rule': 'Abstain until reviewed evidence is supplied.',
        }
        failed = gateway.call('submit_data_availability_batch', {'assessments': [assessment]})
        self.assertEqual(failed['status'], 'failure')
        self.assertIn('zero accepted bbox', failed['failure_reason'])
        self.assertFalse(gateway.registry.data_availability)
        assessment.update(available_inputs=[], missing_inputs=['accepted_bbox_observations'],
                          data_availability='not_attempted')
        accepted = gateway.call('submit_data_availability_batch', {'assessments': [assessment]})
        self.assertIn(key, accepted['accepted_data_availability_keys'])


if __name__ == '__main__':
    unittest.main()
