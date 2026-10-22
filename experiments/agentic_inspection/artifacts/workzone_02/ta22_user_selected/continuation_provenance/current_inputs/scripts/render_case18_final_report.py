#!/usr/bin/env python3
"""Render the completed Case_18 continuation with explicit evidence limitations."""
from collections import Counter
from html import escape
import json
from pathlib import Path

from project_common import ROOT


def read(path):
    return json.loads(Path(path).read_text())


def main():
    base = ROOT / 'artifacts/workzone_18/ta22_user_selected'
    output = ROOT / 'reports/workzone_18/ta22_user_selected/final'
    output.mkdir(parents=True, exist_ok=True)
    final_dir = base / 'stage6/scene-CATS-19'
    result = read(final_dir / 'result.json')
    record = result['record']
    assert result['status']=='completed' and record['phase']=='finalized'
    evaluations = {f'stage{s}':read(base / f'stage{s}/scene-CATS-19/continuation_evaluation.json')
                   for s in [4,5,6]}
    assert all(e['passed'] for e in evaluations.values())
    requirements = record['requirements']
    evidence = record['evidence_records']
    counts = dict(Counter(r['inspection_status'] for r in requirements))
    images = sorted({s for b in record['inspection_bundles'].values() for s in b['source_ids']},
                    key=lambda s:int(s.rsplit('__',1)[1]))
    scene_path = ROOT / 'cases/workzone_18/scene_ta22_camera0_final.json'
    scene = read(scene_path)
    frames = Path(scene['dataset_root']) / scene['scene_id'] / 'CAM_FRONT'
    image_paths = [frames / (s+'.jpg') for s in images]
    assert all(p.is_file() for p in image_paths)
    source = ROOT / 'inputs/case_18/ta22_user_selected/continuation'
    summary = {
        'schema':'case18_ta22_camera0_final_v1', 'status':'pipeline_complete_with_evidence_gaps',
        'scene_id':scene['scene_id'], 'primary_layout':'TA-22',
        'layout_selection_origin':'user_directed', 'context_only_layouts':['TA-33'],
        'camera_channels':['CAM_FRONT'], 'camera_frames_available':632,
        'camera_frames_inspected':len(images), 'inspected_timestamp_range_us':[
            int(images[0].rsplit('__',1)[1]),int(images[-1].rsplit('__',1)[1])],
        'accepted_bbox_observations':0, 'registered_requirements':len(requirements),
        'inspection_status_counts':counts,
        'numerical_measurements':len(record['measurement_records']),
        'blocked_measurement_jobs':evaluations['stage4']['blocked_measurement_jobs'],
        'scope_reviews':scene['inspection_scope_reviews'],
        'validations':evaluations, 'final_copy_evaluation':read(final_dir/'stage6_final_evaluation.json'),
        'scoring_against_independent_reference_performed':False,
        'manual':'MUTCD 11th Edition (December 2023)',
        'limitations':['No human-reviewed detection inventory is available.',
                       'Eight temporal camera0 frames are a route sample, not exhaustive per-device inspection.',
                       'No valid numerical geometry measurements were obtained; six registered measurement jobs are blocked with reasons.',
                       'Original items 9 and 13 have indeterminate applicability in this continuation.',
                       'Two Stage 4 attempts hit readiness/sealing bugs; their raw responses and evidence were retained, and recovery resumed without changing inspected findings.'],
        'artifacts':{'stage4':str(base/'stage4/scene-CATS-19/result.json'),
                     'stage5':str(base/'stage5/scene-CATS-19/result.json'),
                     'stage6':str(final_dir/'result.json'), 'scene':str(scene_path),
                     'scope_review':str(source/'applicability_review.json'),
                     'failed_stage4_attempt':str(base/'stage4_failed_missing_provenance_guard/scene-CATS-19/result.json'),
                     'failed_stage4_sealing_attempt':str(base/'stage4_failed_blocked_measurement_seal/scene-CATS-19/result.json'),
                     'stage4_recovery':str(ROOT/'config/workzone_18/ta22_user_selected/stage4.json')},
    }
    labels = ['封道预告标志设置','右侧单车道封闭标志文字','预告标志间距','直线段导流设施间距',
              '导流设施是否仍可使用','TA-22 的 W4-2R 标志位置与顺序','导流设施清洁、可见性与位置',
              '渐变段长度公式及实际长度','单车道双向交替通行渐变段','W20-1 施工预告标志位置',
              '并道渐变段是否提供足够距离','多块预告标志的排列顺序','下游恢复渐变段（如果设置）']
    gaps = ['未获得清晰可辨认的封道预告标志证据。','未获得足以确认 RIGHT LANE CLOSED 文字的证据。',
            '未确认连续预告标志的位置，无法测量间距。','虽能看到桶和锥，但缺少已复核的相邻设施及其位置，无法测量间距。',
            '抽样图像能看到设施，但未逐个完成可用性检查；未见明显损坏不等于全部合格。',
            '未清晰识别 W4-2R，无法确认图示位置和顺序。','抽样中可见部分设施直立，但无法确认全部设施始终清洁、可见且位置正确。',
            '缺少横向偏移宽度和经复核的渐变段端点。','条款针对两个方向交替使用一条车道；当前场景未确认该条件，暂不用于合规判断。',
            '未取得可确认 W20-1 位于施工区域之前的证据。','未确认并道渐变段端点，无法评价实际并道距离。',
            '未确认多块预告标志的身份及沿行驶方向的先后顺序。','尚未确认设置了下游恢复渐变段；保留“如果设置”的适用前提。']
    statuses = {'satisfied':'满足','deficient':'不满足','not_assessed':'未评估'}
    rows = []
    for i,r in enumerate(requirements):
        reason = gaps[i] if r['inspection_status']=='not_assessed' else r['inspection_reason']
        details = '<details><summary>原始判断与证据</summary><p>'+escape(r['inspection_reason'])+'</p>'
        for evidence_id in r.get('evidence_ids',[]):
            e=evidence[evidence_id]
            details += '<p>'+escape(e.get('finding',''))+'<br><small>'+escape(e.get('limitations',''))+'</small></p>'
        details += '</details>'
        values=[str(i+1),labels[i], '强制' if r['modality']=='shall' else '指导',
                statuses[r['inspection_status']],r['source_locator'],reason]
        rows.append('<tr>'+''.join('<td>'+escape(v)+'</td>' for v in values[:-1])+
                    '<td>'+escape(values[-1])+details+'</td></tr>')
    figures=''.join(f'<figure><img src="{p}" alt="camera0 已检查帧"><figcaption>{escape(p.name)}</figcaption></figure>'
                    for p in image_paths)
    links=''.join(f'<li><a href="{escape(path)}">{escape(label)}</a></li>' for label,path in summary['artifacts'].items())
    html=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Case_18 最终检查报告：TA-22 / camera0</title>
<style>body{{font:16px/1.7 system-ui,sans-serif;max-width:1250px;margin:36px auto;padding:0 24px;color:#23303b}}
h1,h2{{line-height:1.3}}.note{{background:#fff4df;border-left:4px solid #bc7d20;padding:18px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:10px;border:1px solid #dce3e7;text-align:left;vertical-align:top}}
.images{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}figure{{margin:0}}img{{width:100%}}figcaption{{font-size:11px;overflow-wrap:anywhere}}
a{{color:#176b82}}details{{margin-top:8px}}small{{color:#52616c}}@media(max-width:700px){{.images{{grid-template-columns:1fr}}}}</style>
<h1>Case_18：TA-22 / camera0 最终检查报告</h1>
<p>Stage 4 证据获取、Stage 5 判断、Stage 6 最终记录已完成。
登记项目 {len(requirements)} 项：满足 <strong>{counts.get('satisfied',0)}</strong>，
不满足 <strong>{counts.get('deficient',0)}</strong>，未评估 <strong>{counts.get('not_assessed',0)}</strong>。</p>
<div class="note">“未评估”表示证据或适用条件未解决，不代表符合要求，也不代表发现违规。
本次完成的是带证据缺口的检查流程，尚未形成完整的现场合规结论。</div>
<h2>本轮范围</h2><p>主布局按用户意见固定为 TA-22，TA-33 作为现场背景；规范来源为 MUTCD 第11版（2023）。
仅使用 camera0 / CAM_FRONT 的 632 张图像，保留 632 帧 LiDAR 与 INS。
沿用黑车标定与原预处理算法，限速 25 mph，施工持续超过 3 天。</p>
<p>Stage 4 实际检查了 <strong>{len(images)} 张</strong>沿路线分布的 camera0 图像。
当前人工复核框为 <strong>0</strong>，因此 <strong>{summary['blocked_measurement_jobs']} 项几何测量任务</strong>
均记录了无法执行的原因，未生成距离或长度数值。没有把看过图像等同于获得了人工复核框。</p>
<h2>13 项最终记录</h2><table><tr><th>#</th><th>检查项</th><th>性质</th><th>结果</th><th>规范来源</th><th>依据与缺口</th></tr>{''.join(rows)}</table>
<h2>适用性复核</h2><p>第9项保留在历史登记中，但不把单车道双向交替通行的 50–100 ft 标准套用于当前并道渐变段。
第13项只在确有下游恢复渐变段时适用。两项本轮均保留为适用性未确定。</p>
<h2>实际检查的 camera0 图像</h2><div class="images">{figures}</div>
<h2>校验与运行记录</h2><p>阶段边界、输入记账、图像来源、未测量项目的判断限制，以及 Stage 5 到 Stage 6 的复制一致性均通过检查。
这些检查不代表条款适用性或现场判断已经通过独立专家审核；未进行正式精确率／召回率评分。</p>
<p>Stage 4 先后遇到两处结束检查问题：缺失标志证据仍被要求提供复核框，以及有据可查的受阻测量仍被要求实际调用工具。
两处均已修复，保留了两次失败记录，并从已保存的图像观察和证据记录继续完成，未改写此前的 13 项登记。</p>
<ul>{links}</ul><p>下一步需要在 camera0 中完成标志、导流设施和渐变段端点的检测与人工复核，
再重新执行相应几何测量和结论阶段。图像覆盖不到或无法辨认的项目仍需补充现场证据。</p></html>'''
    (output/'report.html').write_text(html)
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    pointer=read(ROOT/'cases/workzone_18/current_run.json')
    pointer.update(status=summary['status'],scene_manifest=str(scene_path.relative_to(ROOT)),
                   report=str((output/'report.html').relative_to(ROOT)),
                   completed_stages=[0,1,2,3,4,5,6],inspection_status_counts=counts,
                   numerical_measurements=summary['numerical_measurements'])
    (ROOT/'cases/workzone_18/current_run.json').write_text(json.dumps(pointer,indent=2)+'\n')
    print(json.dumps({'report':str(output/'report.html'),'outcomes':counts},indent=2))


if __name__=='__main__':
    main()
