#!/usr/bin/env python3
"""Summarize the Case_18 pilot without scoring a pending reference."""
from collections import Counter
from html import escape
import json
from pathlib import Path
import re

from project_common import ROOT


def read(path):
    return json.loads(Path(path).read_text())


def main():
    scene = read(ROOT / 'cases/workzone_18/scene.json')
    data = Path(scene['dataset_root'])
    inputs = ROOT / 'inputs/case_18'
    out = ROOT / 'reports/workzone_18/pilot'
    out.mkdir(parents=True, exist_ok=True)
    stage1_dir = ROOT / read(ROOT / 'config/workzone_18/stage1_kg_bm25.json')['output_directory']
    stage3_dir = ROOT / read(ROOT / 'config/workzone_18/stage3.json')['output_directory']
    first_dir = ROOT / 'artifacts/workzone_18/pilot_before_inventory_fix'
    stage1, stage3 = read(stage1_dir / 'result.json'), read(stage3_dir / 'result.json')
    validation = read(data / 'validation.json')
    stage3_eval = read(inputs / 'stage3_availability_evaluation.json')
    prior = read(first_dir / 'stage1_stage2/scene-CATS-19/stage_0_layout_selection.json')
    primary = lambda result: [r['layout_code'] for r in result['selected_layouts'] if r['layout_role'] == 'primary_applicable']
    count = len(scene['accepted_observations'])
    invalid = [r['discovered_requirement_key'] for r in stage3['record']['requirements']
               if not count and 'accepted_bbox_observations' in
               r.get('data_availability_record', {}).get('available_inputs', [])]
    declaration = read(inputs / 'runtime_scene_manifest.json')
    input_consistency = {
        'passed': not invalid and (count > 0 or 'accepted_bbox_observations' not in declaration['available_direct']),
        'accepted_bbox_count': count,
        'unsupported_available_bbox_claim_count': len(invalid),
        'unsupported_requirement_keys': invalid,
        'first_pilot_unsupported_claim_count': 5,
    }
    (out / 'input_consistency_audit.json').write_text(json.dumps(input_consistency, indent=2) + '\n')
    assert validation['passed'] and input_consistency['passed']
    assert stage3['stopped_before_measurement'] is True
    assert stage3['record']['phase'] == 'measurement'
    assert not stage3['record']['evidence_records'] and not stage3['record']['measurement_records']
    tests = re.search(r'Ran (\d+) tests', (inputs / 'regression_tests.log').read_text())
    summary = {
        'schema': 'case18_sensor_and_stage0_to3_pilot_v1',
        'status': 'stage0_to3_pilot_complete_pending_reviewed_perception_and_independent_applicability_audit',
        'source_case': 'Case_18', 'scene_id': scene['scene_id'],
        'source_root': scene['source_raw_root'], 'processed_root': str(data),
        'confirmed_context': scene['provenance']['confirmed_context'],
        'sensor_validation': validation,
        'primary_method': 'kg_plus_bm25',
        'prior_primary_layouts': primary(prior),
        'current_primary_layouts': primary(stage1['stage0']),
        'layout_choice_requires_independent_review': primary(prior) != primary(stage1['stage0']),
        'layout_comparison_note': 'These are two pilot runs with an inventory-declaration correction, not a controlled repeatability benchmark.',
        'registered_requirements': len(stage1['record']['requirements']),
        'requirement_domain_counts': dict(Counter(r['region'] for r in stage1['record']['requirements'])),
        'availability_states': dict(Counter(r['data_availability'] for r in stage3['record']['data_availability'].values())),
        'stage3_structural_evaluation': {k: v for k, v in stage3_eval.items() if k != 'rows'},
        'input_consistency_audit': input_consistency,
        'regression_tests_passed': int(tests.group(1)),
        'reference_scene_validation': read(inputs / 'reference_validation.log'),
        'reference_public_manifest_parity': read(inputs / 'reference_manifest_parity.json'),
        'config_consistency': read(inputs / 'config_consistency.json'),
        'formal_ground_truth_scoring_performed': False,
        'compliance_conclusions_produced': False,
        'stages4_to6_executed': False,
        'limitations': [
            'No human-reviewed bbox observations are available for Case_18.',
            'Scene geometry/context is provisional assistant interpretation, except the user-confirmed speed and duration.',
            'Two pilot runs selected different primary TAs; verify intersection/work-zone relationship independently.',
            'Independent MUTCD applicability audit is pending; no precision/recall or compliance accuracy claims.',
            'Original detection/aggregation scripts were removed during prior cleanup; preprocessing alone does not reproduce the full reviewed-perception chain.',
        ],
        'artifacts': {'scene': str(ROOT / 'cases/workzone_18/scene.json'),
                      'stage1_result': str(stage1_dir / 'result.json'),
                      'stage3_result': str(stage3_dir / 'result.json'),
                      'first_pilot': str(first_dir), 'processing_manifest': str(data / 'processing_manifest.json')},
    }
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    rows = []
    for r in stage3['record']['requirements']:
        a = r.get('data_availability_record', {})
        rows.append('<tr>' + ''.join(f'<td>{escape(str(v))}</td>' for v in [
            r['candidate_label'], r['region'], a.get('data_availability'),
            '; '.join(a.get('missing_inputs', [])),
        ]) + '</tr>')
    links = ''.join(f'<li><a href="{escape(path)}">{escape(label)}</a></li>' for label, path in summary['artifacts'].items())
    html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>Case_18 实验试跑报告</title><style>
body{{font:16px/1.7 system-ui,sans-serif;max-width:1150px;margin:40px auto;padding:0 24px;color:#23303b}}
h1,h2{{line-height:1.3}}.note{{background:#fff4df;padding:18px;border-left:4px solid #bc7d20}}
.stats{{display:flex;gap:18px;flex-wrap:wrap}}.stats div{{background:#edf4f6;padding:18px;flex:1}}
strong{{color:#145b64}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:10px;border:1px solid #dce3e7;text-align:left;vertical-align:top}}
img{{max-width:100%;height:auto}}code{{overflow-wrap:anywhere}}a{{color:#176b82}}
</style><h1>Case_18：统一预处理与 Stage 0–3 试跑</h1>
<p>输入：<code>{escape(scene['source_raw_root'])}</code>；场景编号：{escape(scene['scene_id'])}。
用户确认：限速 <strong>25 mph</strong>，长期施工<strong>超过 3 天</strong>。</p>
<div class="stats"><div><strong>3,160</strong><br>去畸变图像 / 5 路相机</div>
<div><strong>632</strong><br>运动补偿 LiDAR 帧</div><div><strong>2.53 亿</strong><br>保留点数</div>
<div><strong>{summary['registered_requirements']}</strong><br>当前已登记要求（未经独立适用性审核）</div></div>
<h2>处理一致性</h2><p>复用原有去畸变、逐点运动补偿、ENU 位姿插值、SLERP 和标定组合算法。
新数据本身为 10 Hz，保留全部帧；按实际存在的五路相机生成元数据。原始文件未修改。
全部 3,792 个传感器文件哈希与元数据检查通过；抽查图像和点云与原算法完全一致。
{summary['regression_tests_passed']} 项测试通过，旧案例场景输入及 19 条结论保持不变。</p>
<h2>试跑结果与已修正的问题</h2><p>KG + BM25 已完成场景选择、条款检索、要求登记和数据可用性规划。
结构检查：{stage3_eval['availability_record_count']}/{stage3_eval['registered_requirement_count']} 条规划记录，
完整工具计划 {stage3_eval['tool_complete_plan_count']}/{stage3_eval['registered_requirement_count']}。
首次试跑有 5 条计划把空的复核框库存误报为可用；已修正数据接口和提交校验，保留首次记录并从 Stage 0 重跑。
当前无此类错误声明。</p>
<div class="note"><strong>仍需复核：</strong>首次布局选择为 {escape(', '.join(summary['prior_primary_layouts']))}，
修正后试跑为 {escape(', '.join(summary['current_primary_layouts']))}。两次试跑并非控制变量重复实验；
不能据此判定哪项正确，需独立核对施工区与交叉口的关系。当前已复核检测框为 0，独立条款参照也未完成。
因此尚未执行 Stage 4–6，没有合规结论，也没有正式精确率／召回率统计。</div>
<h2>当前要求及缺失输入</h2><table><tr><th>要求</th><th>领域</th><th>可用性状态</th><th>待获取输入</th></tr>{''.join(rows)}</table>
<h2>数据概览</h2><img src="{inputs / 'raw_contact_sheet.jpg'}" alt="五路原始相机时序概览">
<img src="{inputs / 'trajectory_audit.png'}" alt="INS 轨迹与行驶距离">
<h2>完整记录</h2><ul>{links}</ul>
<p>完整预处理与复现说明：<a href="{ROOT / 'cases/workzone_18/README.md'}">Case_18 README</a>。
后续需要恢复并核对原检测／聚合处理链，补充人工框复核和独立适用性审核，再运行后续证据获取与判断阶段。</p></html>'''
    (out / 'report.html').write_text(html)
    print(json.dumps({'summary': str(out / 'summary.json'), 'report': str(out / 'report.html'),
                      'registered_requirements': summary['registered_requirements'],
                      'unsupported_input_claims': len(invalid)}, indent=2))


if __name__ == '__main__':
    main()
