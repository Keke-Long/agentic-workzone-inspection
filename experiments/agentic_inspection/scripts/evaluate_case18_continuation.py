#!/usr/bin/env python3
"""Audit the camera0 continuation without requiring fabricated bbox measurements."""
import argparse
from collections import Counter
import json
from pathlib import Path

from project_common import ROOT


def read(path):
    return json.loads(Path(path).read_text())


def evaluate(stage):
    base = ROOT / 'artifacts/workzone_18/ta22_user_selected'
    source = read(base / 'stage3/scene-CATS-19/result.json')
    directory = base / f'stage{stage}/scene-CATS-19'
    result = read(directory / 'result.json')
    record = result['record']
    scene = read(ROOT / 'cases/workzone_18/scene_ta22_camera0_final.json')
    requirements = {r['discovered_requirement_key']: r for r in record['requirements']}
    originals = {r['discovered_requirement_key']: r for r in source['record']['requirements']}
    evidence = list(record['evidence_records'].values())
    attempts = list(record['acquisition_attempts'].values())
    bundles = list(record['inspection_bundles'].values())
    request = read(directory / 'request_manifest.json')
    errors = []
    def check(value, message):
        if not value:
            errors.append(message)
    check(set(requirements) == set(originals), 'registered requirement keys changed')
    for key, row in requirements.items():
        for field in ['source_node_ids', 'source_locator', 'modality', 'measurement_spec',
                      'required_inputs', 'threshold', 'requirement_fingerprint']:
            check(row.get(field) == originals[key].get(field), f'{key}:changed_{field}')
        rows = [e for e in evidence if e['discovered_requirement_key'] == key]
        acquired = {i for e in rows for i in e.get('acquired_inputs', [])}
        unresolved = {i for e in rows for i in e.get('unresolved_inputs', [])}
        check(bool(rows), f'{key}:no_evidence_record')
        check(acquired | unresolved == set(row['required_inputs']), f'{key}:unaccounted_inputs')
        check(not acquired & unresolved, f'{key}:contradictory_availability')
        check('accepted_bbox_observations' not in acquired, f'{key}:invented_reviewed_boxes')
    check(not record.get('measurement_records'), 'unexpected numeric measurements with no reviewed geometry')
    plan = record['stage4_plan']
    measurement_ids = {j['measurement_job_id'] for j in plan['measurement_jobs']}
    measured_attempts = [a for a in attempts if a.get('measurement_job_id')]
    check(measurement_ids == {a['measurement_job_id'] for a in measured_attempts}, 'measurement jobs not accounted')
    for attempt in measured_attempts:
        check(attempt['status']=='blocked_before_call' and bool(attempt.get('failure_reason')), 'blocked measurement lacks reason')
        check(any(e.get('acquisition_attempt_id')==attempt['attempt_id'] for e in evidence), 'uncited blocked measurement')
    image_ids = {s for b in bundles for s in b['source_ids']}
    check(len(image_ids) >= 8, 'fewer than 8 inspected temporal images')
    check(all('__CAM_FRONT__' in s for s in image_ids), 'excluded camera accessed')
    timestamps = sorted(int(s.rsplit('__', 1)[1]) for s in image_ids)
    check(bool(timestamps) and (timestamps[-1]-timestamps[0])/(83199999-20099999)>=.70, 'insufficient route span')
    check(all(bool(b.get('model_observation')) for b in bundles), 'unrecorded image observations')
    check(request['scene_view']['scene_data_manifest']['counts']['camera_frames_by_channel']=={'CAM_FRONT':632}, 'camera input mismatch')
    check(request['layout_selection_origin']=='user_directed', 'layout origin missing')
    phases = {4:'inspection_conclusion',5:'result_submission',6:'finalized'}
    check(record['phase']==phases[stage], 'incorrect phase boundary')
    if stage >= 5:
        drafts = record['conclusion_drafts']
        check(set(drafts)==set(requirements), 'incomplete conclusion coverage')
        for key, draft in drafts.items():
            if draft['unresolved_inputs']:
                check(draft['inspection_status']=='not_assessed', f'{key}:unresolved_but_concluded')
            if requirements[key]['measurement_spec'].get('required'):
                check(draft['inspection_status']=='not_assessed', f'{key}:unmeasured_but_concluded')
            review = next((r for r in scene['inspection_scope_reviews']
                           if set(r['source_node_ids']) & set(requirements[key]['source_node_ids'])), None)
            if review:
                check(draft['normative_applicability']==review['normative_applicability'] and
                      draft['inspection_status']=='not_assessed', f'{key}:scope_review_ignored')
    check((record.get('stage4_readiness') or {}).get('ready') is True, 'Stage 4 not sealed ready')
    output = {'schema':'case18_continuation_evaluation_v1', 'stage':stage,
              'passed':not errors, 'errors':errors, 'validation_scope':'traceability and evidence boundaries; not independent compliance accuracy',
              'registered_requirement_count':len(requirements), 'evidence_record_count':len(evidence),
              'inspected_camera0_frames':len(image_ids), 'blocked_measurement_jobs':len(measured_attempts),
              'numerical_measurements':len(record.get('measurement_records',{})),
              'session_tool_failures':result['resources'].get('session_tool_failures'),
              'inspection_status_counts':dict(Counter(r.get('inspection_status') for r in
                  (record['conclusion_drafts'].values() if stage>=5 else [])))}
    (directory / 'continuation_evaluation.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output,indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage',type=int,choices=[4,5,6],required=True)
    evaluate(parser.parse_args().stage)
