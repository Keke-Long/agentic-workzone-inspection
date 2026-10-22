#!/usr/bin/env python3
"""Report the user-directed TA-22, camera0-only pilot from sealed results."""
from collections import Counter
from html import escape
import json
from pathlib import Path

from project_common import ROOT


def read(path):
    return json.loads(Path(path).read_text())


def main():
    variant = 'ta22_user_selected'
    configs = ROOT / 'config/workzone_18' / variant
    first_config, third_config = [read(configs / f'{name}.json')
                                  for name in ['stage1_kg_bm25', 'stage3']]
    scene_path = ROOT / first_config['scene_manifest']
    scene = read(scene_path)
    first_dir, third_dir = [ROOT / c['output_directory'] for c in [first_config, third_config]]
    first, third = [read(p / 'result.json') for p in [first_dir, third_dir]]
    inputs = ROOT / 'inputs/case_18' / variant
    output = ROOT / 'reports/workzone_18' / variant
    output.mkdir(parents=True, exist_ok=True)
    sensor_validation = read(Path(scene['dataset_root']) / 'validation.json')
    runtime = read(inputs / 'runtime_scene_manifest.json')
    evaluation = read(third_dir / 'stage3_availability_evaluation.json')
    selection = read(first_dir / 'stage_0_layout_selection.json')
    requests = [read(p / 'request_manifest.json') for p in [first_dir, third_dir]]
    requirements = third['record']['requirements']
    unsupported = [r['discovered_requirement_key'] for r in requirements
                   if 'accepted_bbox_observations' in
                   (r.get('data_availability_record') or {}).get('available_inputs', [])]
    assert sensor_validation['passed'] and evaluation['passed']
    assert selection['selected_layouts'][0]['layout_code'] == 'TA-22'
    assert len(selection['selected_layouts']) == 1
    assert selection['selection_provenance']['origin'] == 'user_directed'
    assert all(r['layout_selection_origin'] == 'user_directed' and
               r['correct_layout_page_region_or_target_supplied'] is True for r in requests)
    assert runtime['counts']['camera_frames_by_channel'] == {'CAM_FRONT': 632}
    assert all(r['scene_view']['scene_data_manifest']['counts']['camera_frames_by_channel'] ==
               {'CAM_FRONT': 632} for r in requests)
    assert not scene['accepted_observations'] and not unsupported
    assert third['stopped_before_measurement'] and third['record']['phase'] == 'measurement'
    assert not third['record']['evidence_records'] and not third['record']['measurement_records']
    audit = {'passed': True, 'camera_frames_by_channel': {'CAM_FRONT': 632},
             'accepted_bbox_count': 0, 'unsupported_available_bbox_claim_count': len(unsupported),
             'layout_selection_origin': 'user_directed', 'primary_layout': 'TA-22',
             'context_only_layouts': ['TA-33'], 'stage0_model_selection_executed': False}
    summary = {
        'schema': 'case18_user_directed_ta22_camera0_pilot_v1',
        'status': 'stage1_to3_complete_pending_reviewed_perception_and_independent_requirement_audit',
        'source_case': 'Case_18', 'scene_id': scene['scene_id'],
        'processed_root': scene['dataset_root'], 'manual': 'MUTCD 11th Edition (December 2023)',
        'primary_layout': 'TA-22', 'context_only_layouts': ['TA-33'],
        'layout_selection_origin': 'user_directed', 'autonomous_stage0_evaluation': False,
        'camera_policy': scene['provenance']['camera_selection'],
        'confirmed_context': scene['provenance']['confirmed_context'],
        'registered_requirements': len(requirements),
        'requirement_domain_counts': dict(Counter(r['region'] for r in requirements)),
        'availability_states': dict(Counter(r['data_availability_record']['data_availability']
                                          for r in requirements)),
        'sensor_validation': sensor_validation, 'input_consistency_audit': audit,
        'stage3_evaluation': {k: v for k, v in evaluation.items() if k != 'rows'},
        'execution_diagnostics': {
            'stage1_stage2_api_calls': first['resources'].get('model_api_calls'),
            'stage1_stage2_rejected_tool_calls': first['resources'].get('tool_failures'),
            'stage3_api_calls': third['resources'].get('model_api_calls'),
            'stage3_rejected_tool_calls': third['resources'].get('session_tool_failures'),
            'stage1_stage2_status': first['status'], 'stage3_status': third['status'],
        },
        'stages4_to6_executed': False, 'compliance_conclusions_produced': False,
        'formal_ground_truth_scoring_performed': False,
        'limitations': ['No human-reviewed bbox observations are available.',
                       'Only camera0 is admitted; side and rear camera observations are unavailable.',
                       'TA-22 is the user-selected working layout for a site reported to combine TA-22 and TA-33 features.',
                       'An independent requirement-applicability reference is pending.'],
        'artifacts': {'scene': str(scene_path), 'layout_selection': str(first_dir / 'stage_0_layout_selection.json'),
                      'stage1_result': str(first_dir / 'result.json'), 'stage3_result': str(third_dir / 'result.json'),
                      'stage3_evaluation': str(third_dir / 'stage3_availability_evaluation.json'),
                      'processed_data': scene['dataset_root'],
                      'previous_five_camera_pilot': str(ROOT / 'reports/workzone_18/pilot/report.html')},
    }
    for name, value in [('summary.json', summary), ('input_consistency_audit.json', audit)]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    rows = []
    for requirement in requirements:
        availability = requirement['data_availability_record']
        values = [requirement['candidate_label'], requirement.get('source_locator', ''),
                  availability['data_availability'], '; '.join(availability.get('missing_inputs', []))]
        rows.append('<tr>' + ''.join(f'<td>{escape(str(value))}</td>' for value in values) + '</tr>')
    links = ''.join(f'<li><a href="{escape(path)}">{escape(label)}</a></li>'
                    for label, path in summary['artifacts'].items())
    html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>Case_18：TA-22 / camera0 实验报告</title><style>
body{{font:16px/1.75 system-ui,sans-serif;max-width:1150px;margin:40px auto;padding:0 24px;color:#23303b}}
h1,h2{{line-height:1.3}}.note{{background:#fff4df;padding:18px;border-left:4px solid #bc7d20}}
table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:10px;border:1px solid #dce3e7;text-align:left;vertical-align:top}}
strong{{color:#145b64}}a{{color:#176b82}}img{{max-width:100%;height:auto}}code{{overflow-wrap:anywhere}}
</style><h1>Case_18：TA-22 / camera0 单相机实验</h1>
<p>本轮按用户指定，以 <strong>TA-22</strong> 为主布置方案。用户指出现场兼有 TA-33 特征；
TA-33 保留为背景说明。本轮使用 MUTCD 第11版（2023），布局选择记录标记为用户指定。</p>
<h2>输入与处理</h2><p>图像输入仅使用 <strong>camera0 / CAM_FRONT，共 632 张</strong>。
其余相机已从本轮数据目录、传感器元数据及模型可访问的图像输入中排除。
保留 <strong>632 帧 LiDAR</strong> 与 INS 位姿用于定位和几何计算。
沿用黑车标定、原图像去畸变、LiDAR 运动补偿和位姿插值算法；
保留文件与此前校验输出逐字节一致，{sensor_validation['files_hash_checked']} 个输入/输出文件对及元数据校验通过。
场景参数：限速 <strong>25 mph</strong>，长期施工<strong>超过 3 天</strong>。</p>
<h2>本轮结果</h2><p>KG + BM25 完成 Stage 1–2 条款检索与要求登记，共
<strong>{len(requirements)} 条</strong>；Stage 3 完成
<strong>{evaluation['availability_record_count']}/{evaluation['registered_requirement_count']}</strong> 条取证计划，结构校验通过。
没有将空的人工复核框库存声明为可用。</p>
<p>执行诊断：Stage 1–2 有 {first['resources'].get('tool_failures', 0)} 次工具请求被校验拒绝，
模型根据错误反馈修正后完成登记；Stage 3 本轮有 {third['resources'].get('session_tool_failures', 0)} 次工具请求被拒绝。
完整请求与拒绝原因保留在各阶段工具记录中。</p>
<div class="note">当前人工复核框为 0。Stage 4–6 尚未执行，未生成测量结果或合规结论。
后续取证仅使用 camera0；不在该相机视野内、也无法由 LiDAR/INS 支持的证据须保留为缺失。
TA-22 的使用已按用户意见确定，条款适用性的独立审核仍待完成。</div>
<h2>已登记要求及待获取输入</h2><table><tr><th>要求</th><th>来源</th><th>可用性状态</th><th>待获取输入</th></tr>{''.join(rows)}</table>
<h2>camera0 场景预览</h2><img src="{ROOT / 'inputs/case_18/front_review.jpg'}" alt="camera0 场景时序预览">
<h2>可追溯记录</h2><ul>{links}</ul>
<p>前两次五相机试跑仅作为历史记录保留。本轮同时调整了主布局和相机输入，不能将结果差异单独归因于某一项调整。</p>
</html>'''
    (output / 'report.html').write_text(html)
    pointer_path = ROOT / 'cases/workzone_18/current_run.json'
    pointer = read(pointer_path)
    pointer['status'] = summary['status']
    pointer['registered_requirements'] = len(requirements)
    pointer['stage3_evaluation_passed'] = evaluation['passed']
    pointer_path.write_text(json.dumps(pointer, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'report': str(output / 'report.html'),
                      'registered_requirements': len(requirements), 'input_audit_passed': True}, indent=2))


if __name__ == '__main__':
    main()
