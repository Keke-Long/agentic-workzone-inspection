"""Missing reviewed geometry must yield durable gaps, not invented measurements."""
import json
import unittest
from types import SimpleNamespace

from inspection_registry_v5 import RegistryError
from project_common import ROOT
from srag_bm25_tools_v5 import ToolGatewayV5
from preflight_srag_bm25_v5 import resume_measurement_boundary_valid


def gateway():
    source = ROOT / 'artifacts/workzone_18/ta22_user_selected/stage3/scene-CATS-19'
    snapshot = json.loads((source / 'stage_1_to_6_registry.json').read_text())
    trace = json.loads((source / 'tool_trace.json').read_text())
    scene = ROOT / 'cases/workzone_18/scene_ta22_camera0_final.json'
    data = json.loads(scene.read_text())
    return ToolGatewayV5.from_checkpoint(
        snapshot['selected_layouts'], {'scene_id': data['scene_id'], 'scene_facts': data['scene_facts']},
        snapshot, trace, scoped_stage1_stage2=True, simplified_inspection_checks=True,
        orchestrated_stage4=True, orchestrated_stage5=True, scene_manifest=scene)


class EmptyInventoryContinuationTest(unittest.TestCase):
    def test_unresolved_sign_evidence_can_seal_without_claiming_a_reviewed_sign(self):
        g = gateway()
        plan = g._compose_stage4_plan()
        for job in plan['visual_jobs']:
            g._inspect_stage4_visual_job(job['visual_job_id'])
            g._record_visual_job_note({'visual_job_id':job['visual_job_id'],
                                      'finding':'Test temporal coverage','limitations':'No reviewed boxes'})
        for job in plan['visual_jobs']:
            for key, inputs in job['target_inputs_by_requirement'].items():
                if inputs:
                    g._record_visual_finding({'discovered_requirement_key':key,
                        'acquired_inputs':[], 'finding':'Evidence remains unresolved',
                        'limitations':'No reviewed sign observations'})
        self.assertTrue(g._stage4_readiness()['ready'])
        self.assertTrue(g.call('get_stage4_readiness', {})['ready'])
        sealed = g.call('seal_measurements', {})
        self.assertEqual(sealed.get('phase'), 'inspection_conclusion', sealed)
        self.assertFalse(g.registry.measurement_records)
        g.registry.phase = 'measurement'
        attempts = g.registry.acquisition_attempts
        g.registry.acquisition_attempts = {}
        with self.assertRaisesRegex(RegistryError, 'not attempted'):
            g.registry.seal_measurements()
        g.registry.acquisition_attempts = attempts
        key = next(k for k,r in g.registry.requirements.items() if r['candidate_label']=='Single-lane closure legend')
        evidence = next(e for e in g.registry.evidence_records.values()
                        if e['discovered_requirement_key']==key and e['evidence_kind']=='visual_observation')
        evidence['acquired_inputs'] = evidence['unresolved_inputs']
        evidence['unresolved_inputs'] = []
        self.assertIn(key+':missing_traffic_sign_source',g._stage4_readiness()['provenance_gaps'])

    def test_failed_acquisition_can_resume_only_after_complete_sealing(self):
        g = SimpleNamespace(scene=SimpleNamespace(measurements={}), orchestrated_stage4=True,
                            registry=SimpleNamespace(stage4_readiness={'ready':True}),
                            _stage4_readiness=lambda: {'ready':True})
        self.assertTrue(resume_measurement_boundary_valid(g, True))
        g._stage4_readiness = lambda: {'ready':False}
        self.assertFalse(resume_measurement_boundary_valid(g, True))
        g.registry.stage4_readiness = None
        self.assertFalse(resume_measurement_boundary_valid(g, True))

    def test_missing_endpoints_close_measurement_attempts_and_keep_visual_work(self):
        g = gateway()
        plan = g._compose_stage4_plan()
        self.assertTrue(plan['reviewed_observations_missing'])
        self.assertTrue(plan['measurement_jobs'])
        job_ids = {r['measurement_job_id'] for r in plan['measurement_jobs']}
        attempts = [r for r in g.registry.acquisition_attempts.values() if r.get('measurement_job_id')]
        self.assertEqual(job_ids, {r['measurement_job_id'] for r in attempts})
        self.assertTrue(all(r['status'] == 'blocked_before_call' for r in attempts))
        self.assertFalse(g.scene.measurements)
        visual_keys = {k for j in plan['visual_jobs'] for k in j['relevant_requirement_keys']}
        condition_keys = {k for k, r in g.registry.requirements.items() if r['region']=='channelization_system'}
        self.assertTrue(condition_keys <= visual_keys)
        self.assertTrue(all(j.get('channel')=='CAM_FRONT' for j in plan['visual_jobs']))

    def test_image_viewing_cannot_create_accepted_boxes(self):
        g = gateway()
        plan = g._compose_stage4_plan()
        job = plan['visual_jobs'][0]
        g._inspect_stage4_visual_job(job['visual_job_id'])
        key = next(k for k, r in g.registry.requirements.items()
                   if 'accepted_bbox_observations' in r['required_inputs'] and k in job['relevant_requirement_keys'])
        with self.assertRaisesRegex(RegistryError, 'do not create accepted bbox'):
            g._compose_visual_evidence({'discovered_requirement_key':key,
                'acquired_inputs':['accepted_bbox_observations'], 'finding':'test', 'limitations':'test'})

    def test_scope_review_and_blocked_geometry_preclude_definitive_conclusions(self):
        g = gateway()
        g._compose_stage4_plan()
        g.registry.phase = 'inspection_conclusion'
        plan = g._compose_stage5_plan()
        reviewed = [j for j in plan['conclusion_jobs'] if j.get('scope_review')]
        self.assertEqual(len(reviewed), 2)
        for job in reviewed:
            self.assertEqual(job['allowed_inspection_statuses'], ['not_assessed'])
            with self.assertRaisesRegex(RegistryError, 'preserve.*applicability review'):
                g._compose_conclusion_draft({'discovered_requirement_key':job['discovered_requirement_key'],
                    'inspection_status':'not_assessed','normative_applicability':'true','inspection_reason':'test'})
        self.assertTrue(all(j['allowed_inspection_statuses']==['not_assessed']
                            for j in plan['conclusion_jobs'] if j.get('registered_measurement_blocked')))


if __name__ == '__main__':
    unittest.main()
