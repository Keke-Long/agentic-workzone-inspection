from pathlib import Path
import json,shutil,hashlib
R=Path('/home/klong23/workzone'); E=R/'experiments/agentic_inspection'; S=E/'scripts'; D=R/'data/workzone_03'; C=E/'cases/workzone_03'; V=E/'artifacts/workzone_03/detection_verification'; H=E/'artifacts/workzone_03/superseded_before_61_85'; H.mkdir(exist_ok=True)
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
for p in [C/'scene.json',C/'processing_record.json',C/'stage_0_to_6_index.json',D/'selection_manifest.json',D/'detections/run_manifest.json',D/'detections/summary.json',V/'tracklets.json']:
 shutil.copy2(p,H/p.name)
old=json.loads((D/'detections/current_detections.json').read_text()); cache={t['representative']['observation_id']:{'verification':t['verification'],'representative':t['representative']} for t in old['tracks'] if t.get('verification')};save(V/'representative_reuse_cache.json',cache)
if (V/'api_batches').exists():shutil.move(str(V/'api_batches'),str(H/'api_batches'))
save(C/'input_window.json',{'start_s':61.0,'end_s':85.0,'bounds':'inclusive','time_basis':'original Case_14 timestamps, not rebased','camera_channels':['camera0'],'lidar_point_timestamp_filter':True,'authorization':'User explicitly restricts video and point cloud to 61–85 seconds; supersedes all earlier windows.'})
for name in ['prepare_workzone3_selection.py','prepare_workzone3.py','workzone3_build_bev.py','workzone3_detect.py']:
 p=S/name;s=p.read_text();s=s.replace("CUTOFF = 20.0","WINDOW=json.loads((ROOT/'experiments/agentic_inspection/cases/workzone_03/input_window.json').read_text())\nCUTOFF, END = WINDOW['start_s'], WINDOW['end_s']")
 s=s.replace('float(p.stem) >= CUTOFF','CUTOFF <= float(p.stem) <= END').replace("'cutoff_s': CUTOFF,","'cutoff_s': CUTOFF, 'end_s': END,") .replace('User explicitly corrected exclude first 120 seconds to exclude first 20 seconds.','User explicitly selects only 61–85 seconds for images and LiDAR.').replace('sum(ins_t>=CUTOFF)','sum((ins_t>=CUTOFF)&(ins_t<=END))').replace('Downstream reconstruction must also mask point timestamp < 20.0; frame selection alone is insufficient.','Downstream reconstruction must also retain only point timestamps within [61,85]; frame selection alone is insufficient.')
 s=s.replace('and t>=20',"and selection['cutoff_s']<=t<=selection['end_s']").replace('Case_14, exclude t<20 seconds, camera0 only','Case_14, only 61–85 seconds, camera0 only').replace("'cutoff_s':20,","'cutoff_s':selection['cutoff_s'],'end_s':selection['end_s'],").replace('point timestamp>=20 required for geometry','point timestamp in [61,85] required for geometry')
 s=s.replace("original=builder.read_pcd;counts=", "window=json.loads((E/'cases/workzone_03/input_window.json').read_text());start,end=window['start_s'],window['end_s']\n original=builder.read_pcd;counts=")
 s=s.replace("mask=pc['timestamp']>=20.0", "mask=(pc['timestamp']>=start)&(pc['timestamp']<=end)").replace("'excluded_before_cutoff'","'excluded_outside_window'").replace('builder.TIME_RANGE=(20.0,99.6)','builder.TIME_RANGE=(start,end)').replace('point_timestamp_cutoff_s=20.0','point_timestamp_window_s=[start,end]')
 s=s.replace('[59,80,85]','[61.1,80,84.9]').replace('52-94.6 seconds','61-85 seconds').replace('77000000<=ts<=91000000','77000000<=ts<=85000000')
 p.write_text(s)
p=S/'workzone3_detections.html';p.write_text(p.read_text().replace('52–94.6 秒为检测与接近段上下文','图像与点云统一限定为原始时间戳 61–85 秒'))
p=S/'case18_bev_readonly_server.py';p.write_text(p.read_text().replace('52000000','61000000').replace('94600000','85000000'))
p=S/'validate_workzone3_detections_browser.py';p.write_text(p.read_text().replace('==426','==240').replace('frame_count_426','frame_count_240'))
scene=json.loads((C/'scene.json').read_text());scene['metadata_root']=str(D/'processed/CATS_v1.0');scene['raw_images']=[p for p in scene['raw_images'] if 61000000<=int(Path(p).stem.split('__')[-1])<=85000000];f=scene['scene_facts'];f.pop('visual_scene_description',None);f['visual_scene_description_provenance']='Prior wider-window description superseded; fresh scoped scene interpretation pending.';f['inspection_scope']='Only original timestamps 61–85 seconds, camera0 and LiDAR. User-selected later channelized area.';scene['input_window_s']=[61,85];save(C/'scene.json',scene)
# Retain identical per-frame inference, remove outputs outside the newly authorized scope.
rows=[]
for i,p in enumerate(sorted((D/'detections/frames').glob('*.json'))):
 ts=int(p.stem)
 if not 61000000<=ts<=85000000:p.unlink();continue
 d=json.loads(p.read_text());assert hashlib.sha256(Path(d['source_image']).read_bytes()).hexdigest()==d['source_sha256']
 for r in d['detections']:r['frame']=(ts-61099999)//100000;r['context_role']='primary_area' if ts>=77000000 else 'approach_or_exit_context'
 save(p,d);rows.extend(d['detections'])
from collections import Counter
n=len(list((D/'detections/frames').glob('*.json')));summary={'schema':'unreviewed_detection_candidates_v1','workzone_id':'workzone_03','frame_count':n,'candidate_count':len(rows),'class_counts':dict(Counter(x['class'] for x in rows)),'review_status':'unreviewed','input_window_s':[61,85]};save(D/'detections/summary.json',summary);save(D/'detections/candidates.json',{**summary,'detections':rows})
m=json.loads((D/'detections/run_manifest.json').read_text());m.update(scope='61-85 seconds only',frame_count=n,input_window_s=[61,85],reuse_policy='Identical per-frame image hashes verified; inference reused from prior run. Tracklets rebuilt; outside-window results removed.',parent_manifest=str(H/'run_manifest.json'));m.pop('input_frames_sha256',None);save(D/'detections/run_manifest.json',m)
shutil.rmtree(E/'reports/workzone_03/detection_crops');(E/'reports/workzone_03/detection_crops').mkdir()
print(summary)
