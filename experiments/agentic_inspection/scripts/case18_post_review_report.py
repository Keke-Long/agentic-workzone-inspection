#!/usr/bin/env python3
"""Evidence reassessment of frozen Case18 requirements, using snapshotted human review.
Not a rerun of requirement retrieval or an independent benchmark accuracy evaluation.
"""
import base64,collections,csv,hashlib,html,io,json,shutil
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image
R=Path(__file__).resolve().parents[1]
A=R/'artifacts/workzone_02/ta22_user_selected/post_review_20261021'
O=R/'reports/workzone_02/ta22_user_selected/post_review_20261021';O.mkdir(exist_ok=True)
s=json.loads((A/'scene.json').read_text());obs=s['accepted_observations'];sem=s['semantic_only_observations'];allobs=obs+sem
source=R/'artifacts/workzone_02/ta22_user_selected/stage3/scene-CATS-19/result.json'
reqs=json.loads(source.read_text())['record']['requirements'];frozen=json.dumps(reqs,sort_keys=True).encode()
assert len(reqs)==13 and len(obs)==238 and len(sem)==32
summary=json.loads((A/'review_summary.json').read_text());geometry=json.loads((A/'geometry_validation.json').read_text())
ids=lambda cls:[x['observation_id'] for x in allobs if x['reviewed_class'] in cls]
signs=ids(['road_work_ahead','right_lane_closed','merging_sign']);cones=ids(['traffic_cone','barricade','road_barrier'])
# Decisions are explicitly bounded to the captured camera0 approach, not all approaches or the full work duration.
spec=[
('封道预告牌在封道前方','supported','帧 62–83 的 RIGHT LANE CLOSED AHEAD 位于帧 375 起可见的交叉口远侧封道之前。此结论限本次行驶方向。',ids(['right_lane_closed']),''),
('单条右车道关闭的标志文字','supported','人工确认的 22 个框中可读到 RIGHT LANE CLOSED AHEAD，与右车道关闭一致。',ids(['right_lane_closed']),''),
('预告标志间距：100 ft（指导值）','indeterminate','已定位到三种标志的图像，但同一静止标志的三维坐标跨帧漂移；不能用当前定位比较 100 ft。',signs,'需要修复/验证三维关联及跨帧稳定性，再测相邻标志距离。'),
('直线段导流设施间距：不超过 50 ft','indeterminate','146 个 cone 类观察已接受（包含 drum、delineator）。间距工具已运行，但可靠三维实体与相邻设施序列为 0，实际比较间距为 0；无超限输出不代表合格。',cones,'需要可靠的设施定位、跨帧去重和直线段相邻关系。'),
('不再适用的导流设施应更换','indeterminate','已检查代表性局部图与场景帧；人工审核确认的是类别和框，没有逐设施的损坏、反光及可用性结论。不能据此证明所有设施均可继续使用。',cones,'需要设备状态证据；这不是要求重新审核检测框。'),
('TA-22 中 W4-2R 的位置与顺序','supported','右侧并道图案可见于帧 138、150、157；位于 RIGHT LANE CLOSED 之后、交叉口及远侧封道之前，支持 TA-22 主行驶方向的图示顺序。此行不判断标志间距。',signs,''),
('设施保持清洁、可见并正确设置','supported','直接按本次图片判断：复核 164 个已接受的导流设施观察及场景上下文，清晰可辨的设施色带可见，未见明显影响识别的污损、倒伏或侵入通行路径的错置。局部倾斜未显示明显丧失导向作用。末段逆光、模糊小图不作为正向证据；综合清晰视图，观察范围内支持符合。',cones,''),
('并道渐变段长度公式','indeterminate','25 mph 已确认，公式为 L=W×25²/60（L、W 均为 ft）。实际横向偏移 W、渐变段起终点及其可靠三维位置尚未建立。',cones,'需要 W 与经验证的渐变段起终点；不假定 12 ft 车道宽。'),
('双向交替单车道渐变段 50–100 ft','not_applicable','原条文 6B.08¶14 继承双向交通交替使用单车道的上下文。当前观察为分隔道路同向右车道关闭，不属于该场景；不能将此长度范围直接用于本处并道渐变段。',[],'已纠正先前抽取后适用性判断的上下文问题，保留原条文以供追溯。'),
('ROAD WORK AHEAD 在工作区之前','supported','帧 0–29 的 ROAD WORK AHEAD 已人工确认，随后才到封道预告、交叉口和施工区。',ids(['road_work_ahead']),''),
('并道渐变段提供足够预告与并道距离','indeterminate','预告标志存在已得到支持；但渐变段长度、起终点及可用并道空间缺少可靠测量，不能仅凭有标志判为满足。',signs+cones,'需要经验证的渐变段几何和并道空间证据。'),
('多块预告牌中 ROAD WORK AHEAD 最先遇到','supported','在记录覆盖的主行驶方向，先遇 ROAD WORK AHEAD（0–29），再遇 RIGHT LANE CLOSED AHEAD（62–83），再遇右侧并道标志（近距 132–160）。不外推到未拍摄的其他入口。',signs,''),
('若设置下游渐变段，其长度及间距','indeterminate','末段可见设施逐渐退出视野，但不能清晰确定是否设置了将车辆导回原车道的下游渐变段及其两端。条文含“若设置”，不能因未知而判违规。',cones,'先确定下游渐变段是否实际设置，再测 50–100 ft 长度及约 20 ft 间距。')]
rows=[]
for i,(r,(title,status,reason,evidence,missing)) in enumerate(zip(reqs,spec),1):
 rows.append({'number':i,'requirement_id':r['discovered_requirement_key'],'title':title,'modality':r['modality'],'source_locator':r['source_locator'],'status':status,'reason':reason,'missing_evidence':missing,'evidence_ids':evidence,'scope':'recorded camera0 main approach','requirement_fingerprint':r['requirement_fingerprint']})
repair=json.loads((A/'sign_geometry_repair/validation_and_measurements.json').read_text())
assert repair['status']=='validated_for_observed_sign_spacing' and all(m['result']=='supported' for m in repair['measurements'])
m1,m2=repair['measurements']
rows[2].update(status='supported',reason=f"已修正 INS 坐标约定、逐点运动补偿及时间配对，并验证三块标志的跨帧稳定性。ROAD WORK AHEAD → RIGHT LANE CLOSED 为 {m1['distance_m']:.2f} m（{m1['distance_ft']:.1f} ft）；RIGHT LANE CLOSED → 并道标志为 {m2['distance_m']:.2f} m（{m2['distance_ft']:.1f} ft）。两段保守敏感性范围的下界均大于 100 ft，观察范围内支持符合该指导值。",missing_evidence='',evidence_ids=sorted(set(m1['evidence_ids']+m2['evidence_ids'])))
geometry={'initial_diagnostic':geometry,'validated_sign_geometry':repair,'reliable_sign_tracks':3,'reliable_sign_spacing_measurements':2,'other_geometry_status':'channelizer and taper geometry not yet reconstructed with corrected convention'}
vlm=json.loads((A/'qwen_serviceability/final_summary.json').read_text())
assert len(vlm['observations'])==164 and vlm['counts'].get('visible_unserviceable',0)==0
rows[4].update(status='no_visible_defect',reason=f"已调用本地 {vlm['model']} 检查全部 164 个已接受的设施观察框：108 个可见状态可用，56 个因模糊、逆光或目标过小而无法判断，复核后无明确不可用观察。初判的 31 个缺陷标记已单图复核为不确定。结论：本次图像检查未发现明确失效；不把不确定图片计为合格，不外推夜间性能或历史更换行为。",missing_evidence='56 个低清晰度观察保留为不确定；它们不构成已损坏证据，也不证明可用。',evidence_ids=[x['observation_id'] for x in vlm['observations']])
bev=json.loads((A/'scene_bev/objects.json').read_text())
bc=bev['counts'];clear_objects=bc['object_condition_counts'].get('supported_serviceable',0)
remaining_uncertain=len([o for o in bev['objects'] if o['position_status']=='multi_frame_supported' and o['condition_status']=='uncertain_no_clear_view'])
rows[4].update(reason=f"已按物理对象候选汇总 Qwen 图像证据：{clear_objects} 个多帧关联可靠的设施对象至少有一张清晰可用视图，且无明确缺陷冲突；原先 56 个不清晰观察中，{bc['uncertain_views_resolved_by_same_object']} 个已由同一对象的清晰视图补足，不再作为该对象无法判断的理由。另有 {remaining_uncertain} 个多帧设施对象尚无模型可判断的清晰视图；单帧及身份未确定者单独保留。未发现明确失效设施。",missing_evidence='仅对没有清晰视图的对象或身份关联不可靠的观察保留不确定，不因同一对象的某一帧模糊而否定其清晰证据。')
assessment=json.loads((A/'full_reassessment/assessment.json').read_text())
gaps=assessment['tangent_spacing'];taper=assessment['taper']
rows[3].update(status='supported',reason=f"已对重建直线段（轨迹里程 319.87–434.22 m）的 17 组相邻设施测距：最大 {gaps['maximum_distance_m']:.2f} m，敏感性范围上界最大 {gaps['maximum_upper_bound_m']:.2f} m，均小于 15.24 m（50 ft）。其中 OBJ_014 为人工确认的单帧设施，位置暂定并采用更宽余量；其余采用多帧实体。结论限已观察直线段。",missing_evidence='',evidence_ids=gaps['evidence_ids'])
rows[7].update(status='measured_borderline',reason=f"已拟合渐变段：长度 L≈{taper['length_m']:.2f} m，横向偏移 W≈{taper['lateral_offset_estimate_m']:.2f} m。25 mph 下公式给出 L≈{taper['required_length_m_at_25mph']:.2f} m。长度敏感性范围 38.02–44.02 m，要求值随 W 变化为 36.75–52.37 m，范围重叠，不能确认符合或不符合。",missing_evidence='W 为相对车辆轨迹的设施横向位移估计；尚非独立测得的道路横向偏移。渐变段端点与 W 的系统误差仍影响临界判断。')
rows[10].update(status='measured_borderline',reason='预告标志的顺序和距离得到支持；渐变段长度约 41.02 m，与按估计横向偏移计算的 44.56 m 接近。结合第 8 条的敏感性范围，目前不能确认并道距离充分，也不能确认不足。',missing_evidence='同第 8 条：需进一步约束渐变段端点与道路横向偏移；有预告标志不等于并道距离必然充足。')
rows[12].update(status='not_applicable',reason='已复核末段帧 500–631，重点查看 560、564、570、575 等清晰视图。设施沿施工边界结束，随后车道开放，未识别到将车辆导回原车道的下游渐变设施序列。该条以“若设置”为前提，在本次拍摄主行驶方向不适用。',missing_evidence='不外推到未拍摄的其他入口或施工时段。')
geometry['other_geometry_status']='channelizer spacing measured; taper estimated with overlapping sensitivity envelopes'
geometry['full_reassessment']=assessment
counts=dict(collections.Counter(x['status'] for x in rows));assert counts=={'supported':8,'measured_borderline':2,'not_applicable':2,'no_visible_defect':1}
result={'schema':'case18_post_review_reassessment_v1','created_at':datetime.now(timezone.utc).isoformat(),'method':'assistant evidence reassessment with deterministic geometry attempts; frozen Stage3 requirements retained; not a new autonomous Stage4–6 model run','authority':'MUTCD 11th Edition December 2023','layout':'TA-22 primary','scene_manifest':str(A/'scene.json'),'source_registry':str(source),'frozen_requirements_sha256':hashlib.sha256(frozen).hexdigest(),'status_counts':counts,'review_summary':summary,'serviceability_vlm':vlm,'object_level_condition':bev,'geometry_validation':geometry,'requirements':rows,'frozen_requirements':reqs,'visual_inspection':{'context_frames':[0,29,62,83,157,210,270,325,375,430,480,540,600,631],'crop_sample':'evidence montage in report','condition_review':{'requirement_number':7,'observation_crops_inspected':164,'contact_sheets':['condition_contact_0.jpg','condition_contact_1.jpg','condition_contact_2.jpg'],'basis':'Visible cleanliness, visibility and placement in captured images; blurry or glare-obscured observations are not affirmative evidence'},'limitation':'Image-visible condition only; no inference of night-time performance or unseen device surfaces'}}
(A/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));shutil.copy2(A/'result.json',O/'result.json')
with (O/'requirements.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
labels={'measured_borderline':'已测量，临界待定','no_visible_defect':'已检查，未发现明确失效','supported':'观察范围内支持符合','indeterminate':'证据不足，暂不能判定','not_applicable':'不适用'}
esc=html.escape
trs=''.join('<tr><td>'+str(x['number'])+'</td><td>'+esc(x['title'])+'<small>'+esc(x['source_locator'])+' · '+('强制 shall' if x['modality']=='shall' else '指导 should')+'</small></td><td class="'+x['status']+'">'+labels[x['status']]+'</td><td>'+esc(x['reason'])+'</td><td>'+esc(x['missing_evidence'] or '—')+'</td></tr>' for x in rows)
imgs=[]
for cl in ['road_work_ahead','right_lane_closed','merging_sign','arrow_board']:
 a=sorted([x for x in allobs if x['reviewed_class']==cl],key=lambda x:x['frame']);x=a[2*len(a)//3];im=Image.open(x['source_image']).crop(x['bbox']);im.thumbnail((440,360));b=io.BytesIO();im.save(b,format='JPEG');imgs.append('<figure><img src="data:image/jpeg;base64,'+base64.b64encode(b.getvalue()).decode()+'"><figcaption>'+esc(cl)+'<br>'+esc(x['observation_id'])+'</figcaption></figure>')
context=base64.b64encode((A/'context_montage.jpg').read_bytes()).decode()
page='''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Case 18 人工审核后规范再评判</title><style>body{font:16px/1.65 system-ui;margin:30px;color:#243447;background:#f6f8fb}h1{font-size:28px}table{width:100%;border-collapse:collapse;background:white}th,td{padding:14px;border:1px solid #dce3eb;text-align:left;vertical-align:top}th{background:#e8eef5;position:sticky;top:0}small{display:block;color:#637181;font-size:12px}.supported{color:#187445}.measured_borderline{color:#996000}.indeterminate{color:#996000}.not_applicable{color:#64748b}.cards{display:flex;flex-wrap:wrap}figure{background:white;padding:18px;margin:8px;max-width:440px}figure img{max-width:100%;height:200px;object-fit:contain}.note{padding:18px;background:#fff5d9;border-left:4px solid #cc9300}a{color:#176bb3}</style><h1>Case 18 · 人工审核后规范再评判</h1><p>TA-22 · 25 mph · 长期施工超过 3 天 · camera0 · 沿用黑车标定</p><p><b>8 条在观察范围内支持符合 · 1 条图像检查未发现明确失效 · 2 条已测量、临界待定 · 2 条不适用 · 0 条已证实不符合</b></p><p>13 条均已逐项检查；第 8、11 条涉及同一渐变段，已有几何估计，但敏感性范围重叠，暂不能明确判定。第 5 条未发现明确失效，仍保留对象级证据范围。沿用已提取的 13 条要求及 <a href="https://mutcd.fhwa.dot.gov/pdfs/11th_Edition/part6.pdf">MUTCD 11th Edition（2023）</a>，本次更新证据与结论，不重新抽取规范。</p><p>已纳入 238 个接受的框：原审核 186 个（含已完成的 23 个修框）＋新增预告牌 52 个；另保留 32 个仅确认类别的观察。框数是多帧观察数，不是物理设施数量。cone / delineator / drum 统一按 cone 分析；已拒绝的候选不作为目标证据。</p><div class="note"><b>测量质量检查：</b>238 次框到 LiDAR 投影均返回了候选点，但同一静止 ROAD WORK AHEAD 的估计位置跨帧相差最大 67.2 m，RIGHT LANE CLOSED 相差 42.5 m；因此不能将 acquired 状态当作可靠定位。当前拒绝使用这些坐标作规范距离比较。原因可能涉及坐标变换、同步或背景点关联，尚未确认根因。图像类别及修框结果继续保留，不需要重做框审核。</div><h2>13 条逐项结果</h2><table><thead><tr><th>#</th><th>要求与来源</th><th>结论</th><th>证据及理由</th><th>尚缺什么</th></tr></thead><tbody>'''+trs+'''</tbody></table><h2>代表性人工确认目标</h2><div class="cards">'''+''.join(imgs)+'''</div><h2>行驶顺序与施工区上下文</h2><p>以下为本次复核的代表性原图，覆盖预告标志、交叉口、远侧施工区与末段；不替代逐设施状态检测。</p><img style="max-width:100%" src="data:image/jpeg;base64,'''+context+'''"><p>本报告为基于人工结果的证据再评判，未宣称重新执行自主模型 Stage 4–6，也不用于独立准确率评分。本次使用最终确认的类别与修正框；检测候选及人工复查数据库已按研究范围清理，Agentic 阶段记录和最终测量证据保留。</p></html>'''
names={'road_work_ahead':'ROAD WORK AHEAD','right_lane_closed':'RIGHT LANE CLOSED','merging_sign':'右侧并道标志'}
measurement_rows=''.join(f"<tr><td>{names[m['from']]} → {names[m['to']]}</td><td>{m['distance_m']:.2f} m / {m['distance_ft']:.1f} ft</td><td>{m['sensitivity_envelope_m'][0]:.2f}–{m['sensitivity_envelope_m'][1]:.2f} m</td><td>支持符合 100 ft 指导值</td></tr>" for m in repair['measurements'])
stability_rows=''.join(f"<tr><td>{names[t['class']]}</td><td>{t['independent_frames']}</td><td>{t['station_peak_to_peak_m']:.3f} m</td><td>{t['world_xy_max_pairwise_distance_m']:.3f} m</td><td>{t['early_late_station_difference_m']:.3f} m</td></tr>" for t in repair['tracks'])
new_note='<div class="note"><b>标志三维关联已修复并验证：</b>原转换混用了 X 朝前的航向与 Y 朝前的 INS 外参，使相机朝向偏转约 90°。现在采用 <a href="https://docs.novatel.com/OEM7/Content/SPAN_Operation/Definition_Reference_Frames.htm">NovAtel Y 朝前坐标约定</a>，从原始点云按点时间重算运动补偿，并按时间选择最近 LiDAR（最大参考时间差 0.256 ms）。保留黑车标定、camera0 图像及人工框。先筛选菱形中心区域和目标深度，再验证同一标志跨帧稳定性。此前失效的定位仅保留为历史诊断，不参与本次距离计算。修复后的统一坐标已用于全场景设施关联、直线段间距测量及渐变段拟合。所有结论只使用本案例的图像、点云与轨迹。</div>'
a=page.index('<div class="note">');b=page.index('</div>',a)+6;page=page[:a]+new_note+page[b:]
section='<h2>相邻标志实测距离</h2><table><tr><th>相邻标志</th><th>沿道路距离</th><th>敏感性范围</th><th>判断</th></tr>'+measurement_rows+'</table><p>距离按车辆轨迹的道路里程差计算。敏感性范围采用各标志完整跨帧范围并为每个端点另加 ±1 m 余量；不是统计置信区间，也不是测绘级精度保证。即使取该范围下界，两段仍明显大于 30.48 m（100 ft）。未评判最后一块标志到渐变段的距离。</p><h2>跨帧稳定性验证</h2><table><tr><th>标志</th><th>独立帧数</th><th>沿道路位置极差</th><th>平面位置最大差</th><th>前/后半段里程中位数差</th></tr>'+stability_rows+'</table><p>排除 RIGHT LANE CLOSED 的 F0062（目标点不足），ROAD WORK AHEAD 的 F0029（图像边缘截断），以及并道标志的 F0078、F0082（超过 60 m 且点数不足）。同帧重复框只计一次。所有标志均通过至少 5 独立帧、平面位置距中位数小于 1 m、前后分组里程差小于 0.5 m 的检查。</p>'
page=page.replace('<h2>代表性人工确认目标</h2>',section+'<h2>代表性人工确认目标</h2>')
evidence_page=(O/'serviceability.html').read_text()
evidence_body=evidence_page[evidence_page.index('<h1>'):evidence_page.rindex('</html>')]
page=page.replace('<h2>代表性人工确认目标</h2>','<details><summary><b>展开：第 5 条 Qwen 逐图检查结果（164 个观察）</b></summary>'+evidence_body+'</details><h2>代表性人工确认目标</h2>')
bev_section=f'<div class="note"><b>新增：<a href="/bev">全场景交互 BEV 与对象级状态</a></b><p>632 帧原始点云、车辆轨迹和 270 个观察已关联到统一坐标。{bc["multi_frame_supported_objects"]} 个对象有多帧位置支持，{bc["objects_with_candidate_position"]-bc["multi_frame_supported_objects"]} 个位置暂定，{bc["unresolved_observations"]} 个观察未可靠定位。点击对象可查看全部关联图片；{bc["uncertain_views_resolved_by_same_object"]} 个模糊观察已由同对象清晰视图补足。</p><p>下方逐图 Qwen 表格保留原始机器判断，不是当前的对象级结论。原来的 56 个“不确定”观察不再等同于 56 个不确定设施。</p></div>'
page=page.replace('<h2>13 条逐项结果</h2>',bev_section+'<h2>13 条逐项结果</h2>')
gap_rows=''.join(f"<tr><td>{g['from']} → {g['to']}</td><td>{g['distance_m']:.2f} m</td><td>{g['sensitivity_envelope_m'][0]:.2f}–{g['sensitivity_envelope_m'][1]:.2f} m</td><td>{'含单帧暂定位置' if g['contains_single_frame_anchor'] else '多帧位置支持'}</td></tr>" for g in gaps['gaps'])
extra='<h2>设施间距与渐变段实测</h2><p>直线段 17 组相邻间距均低于 15.24 m；多帧端点各加 ±0.5 m、单帧端点加 ±1 m 做敏感性检查。这些范围不是统计置信区间。仅使用 Case 18 设施清单，防止将漏关联设施造成的假空隙判为超限。</p><details><summary>展开 17 组相邻间距</summary><table><tr><th>对象</th><th>间距</th><th>敏感性范围</th><th>位置证据</th></tr>'+gap_rows+'</table></details><p>渐变段采用设施序列的线性变化接直线段拟合，L≈41.02 m、W≈4.28 m；W 为相对行驶轨迹的横向偏移估计。拟合误差较小不等于道路边界与端点已得到独立验证，因此第 8、11 条保留为临界待定。</p>'
for filename,mime,caption in [('measurements.png','image/png','渐变段拟合与直线段相邻间距'),('termination_crops.jpg','image/jpeg','末段图像：判断是否存在下游渐变段的可见证据')]:
 path=A/'full_reassessment'/filename
 if path.exists(): extra+='<h3>'+caption+'</h3><img style="max-width:100%" src="data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode()+'">'
page=page.replace('<h2>代表性人工确认目标</h2>',extra+'<h2>代表性人工确认目标</h2>')
end_sign_note='<h2>补充核查：END ROAD WORK（G20-2）是否必须设置</h2><p><b>按本报告采用的 MUTCD 2023 / TA-22，不要求必须设置。</b>6B.07¶02 将终止提示标志列为可选；6H.36¶01 规定的是“若使用”时应设在终止区下游端附近；Figure 6P-22 明确将 G20-2 标为 optional。<a href="https://mutcd.fhwa.dot.gov/pdfs/11th_Edition/part6.pdf">官方条文与图示</a>。</p><p>原 Stage 3 工具日志已经识别 component:sign:G20-2，关系为 depicts_optional_component。因此没有将其列为必须存在的检查项，与上述规范一致。原报告未展示这一可选项的排除说明，现补充追溯；日志没有单独的模型排除理由，不能进一步断言其内部筛选原因。若实际设置，位置仍需按条件性指导条文检查。</p><p>用户指出现场未设置，现有人工接受目标也未确认该标志；本次没有重新做全帧缺失检测。仅凭缺少该标志，不按以上条文判违规。原 13 条要求及其统计保持不变；本结论不代表已核查项目专用交通组织方案或地方附加要求。</p>'
page=page.replace('<h2>代表性人工确认目标</h2>',end_sign_note+'<h2>代表性人工确认目标</h2>')
page=page.replace('Case 18', 'Workzone 2')
(O/'report.html').write_text(page)
current_path=R/'cases/workzone_02/current_run.json';current=json.loads(current_path.read_text());(A/'previous_current_run.json').write_text(json.dumps(current,indent=2,ensure_ascii=False)) if not (A/'previous_current_run.json').exists() else None
current['post_review_reassessment']={'status':'completed_with_evidence_gaps','method':result['method'],'result':str(A/'result.json'),'report':str(O/'report.html'),'status_counts':counts,'human_bbox_repairs_remaining':0,'human_bbox_repairs_saved':23,'accepted_bbox_observations':238,'semantic_only_observations':32,'trusted_numerical_measurements':19,'provisional_taper_estimates':1,'full_reassessment':str(A/'full_reassessment/assessment.json'),'geometry_repair_result':str(A/'sign_geometry_repair/validation_and_measurements.json')}
current['scene_bev']={'report':str(O/'bev.html'),'artifact':str(A/'scene_bev/objects.json'),'counts':bc}
current['numerical_measurements']=20
current['report']=str(O/'report.html');current['status']='post_review_reassessment_complete_with_evidence_gaps';current['inspection_status_counts']=counts
current_path.write_text(json.dumps(current,indent=2,ensure_ascii=False))
print(json.dumps({'counts':counts,'report':str(O/'report.html')},ensure_ascii=False))
