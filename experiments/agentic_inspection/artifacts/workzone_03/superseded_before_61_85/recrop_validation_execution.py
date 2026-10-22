from pathlib import Path
import json,shutil,hashlib,sys,urllib.request,urllib.error
import numpy as np
R=Path('/home/klong23/workzone');E=R/'experiments/agentic_inspection';D=R/'data/workzone_03';V=E/'artifacts/workzone_03/detection_verification';B=E/'artifacts/workzone_03/bev_reconstruction/scene_bev';O=E/'reports/workzone_03'
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
rows=[]
for i,p in enumerate(sorted((D/'detections/frames').glob('*.json'))):
 d=json.loads(p.read_text())
 for x in d['detections']:x['frame']=i
 rows.extend(d['detections']);save(p,d)
p=D/'detections/candidates.json';d=json.loads(p.read_text());d['detections']=rows;save(p,d);byid={x['observation_id']:x for x in rows}
for p in [V/'tracklets.json',D/'detections/current_detections.json']:
 d=json.loads(p.read_text());d['input_window_s']=[61,85]
 for t in d['tracks']:t['representative']=byid[t['representative']['observation_id']]
 save(p,d)
result=json.loads((D/'detections/current_detections.json').read_text());tracks=result['tracks'];ids=[oid for t in tracks for oid in t['observation_ids']];assert len(ids)==len(set(ids))==len(rows) and set(ids)==set(byid)
assert all(61000000<=r['timestamp_us']<=85000000 for r in rows)
assert all(t['representative']['observation_id']==t['verification']['observation_id'] for t in tracks if t.get('verification'))
assert all((O/'detection_crops'/(t['track_id']+'.jpg')).exists() for t in tracks)
assert len(list((D/'processed/scene-CATS-15/CAM_FRONT').glob('*.jpg')))==240
save(V/'data_validation.json',{'passed':True,'input_window_s':[61,85],'frames':240,'candidates':len(rows),'tracklets':len(tracks),'exact_track_partition':True,'representatives_match_classification':True,'all_images_and_detections_within_window':True,'all_crops_exist':True})
cloud=np.load(B/'pointcloud_display.npz')['xyz'];traj=json.loads((B/'trajectory.json').read_text());recon=json.loads((B/'reconstruction.json').read_text());assert np.isfinite(cloud).all() and all(61e6<=t['timestamp_us']<=85e6 for t in traj)
assert recon['raw_lidar_frames']==240 and recon['point_timestamp_window_s']==[61,85]
sys.path.insert(0,str(E/'scripts'));from case18_sign_geometry import read_pcd
sel=json.loads((D/'selection_manifest.json').read_text());bounds=[]
for r in [sel['streams']['lidar']['frames'][0],sel['streams']['lidar']['frames'][-1]]:
 pc=read_pcd(Path(r['path']));ts=pc['timestamp'];ts=ts[(ts>=61)&(ts<=85)];bounds.append([float(ts.min()),float(ts.max())])
save(B/'validation.json',{'passed':True,'input_window_s':[61,85],'display_points':len(cloud),'trajectory_poses':len(traj),'all_points_finite':True,'all_trajectory_timestamps_in_window':True,'boundary_scan_retained_point_ranges_s':bounds,'per_point_filter':'61 <= timestamp <= 85 applied before INS transformation in workzone3_build_bev.py','scope':'Sensor background only; no object locations or compliance conclusions'})
shutil.copy2(B/'sensor_bev_preview.png',O/'sensor_bev_preview.png')
html=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>Workzone 3</title><style>body{{font:17px system-ui;max-width:1100px;margin:35px auto;padding:15px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:12px;text-align:left}}img{{width:100%}}</style><h1>Workzone 3 · 61–85 秒输入</h1><table><tr><th>输入范围</th><td>Case_14 原始时间戳 61 ≤ t ≤ 85 秒；camera0 与 LiDAR 同一范围，不归零，原始文件不修改</td></tr><tr><th>图像</th><td>240 张 camera0，61.099999–84.999990 秒；保持原采样率和既有去畸变方法</td></tr><tr><th>点云</th><td>240 帧 LiDAR，逐点过滤到 61–85 秒；{recon['raw_points_processed']:,} 点参与处理，{len(cloud):,} 个展示点，{len(traj)} 个轨迹姿态</td></tr><tr><th>场景参数</th><td>黑车标定，20 mph，施工少于 3 天，整条对向车道封闭；实际绕行方式未确认</td></tr><tr><th>目标检测</th><td>5,824 个原始候选框，3,206 个二维组；295 张代表图已分类（286 张复用相同区间内图像，9 张新分类）；默认目标候选 40 组，框需检查 54 组。数量不代表独立设施。<a href="/workzone3/detections">查看检测结果</a></td></tr><tr><th>Stage 0–6</th><td>旧范围场景理解与 Stage 0 已标记过期，待按新输入重新执行；Stage 1–6 未执行，没有规范结论</td></tr></table><h2>同一范围的点云与车辆轨迹</h2><p>尚未关联人工确认对象，无规范结果叠加。</p><img src="sensor_bev_preview.png"><p>原始数据：/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_14/</p></html>''';(O/'preparation_status.html').write_text(html)
save(E/'artifacts/workzone_03/input_recrop_61_85.json',{'authorization':'User restricts all video and LiDAR inputs to 61–85 seconds','input_window_s':[61,85],'raw_modified':False,'camera_frames':240,'lidar_frames':240,'raw_candidates_before':10972,'raw_candidates_after':5824,'reused_classifications':286,'new_classifications':9,'point_filter_counts':recon['point_filter_counts'],'retired_scope_provenance':'superseded_before_61_85','current_validations':[str(V/'data_validation.json'),str(V/'viewer_validation.json'),str(B/'validation.json')],'cleanup':'Removed out-of-window processed camera images, candidate frame JSON, obsolete scoped metadata, old crops and wide-window preview sheets; original raw files unchanged.'})
for path in ['/workzone1/bev','/workzone2/bev','/workzone3/bev','/workzone3/detections']:
 assert urllib.request.urlopen('http://127.0.0.1:8768'+path).status==200
for ts in [59599999,90099999]:
 try:urllib.request.urlopen(f'http://127.0.0.1:8768/workzone3/detections/frame/{ts}.jpg');raise AssertionError('outside frame served')
 except urllib.error.HTTPError as e:assert e.code==404
print('VALIDATED',len(rows),len(cloud),len(traj),bounds)
