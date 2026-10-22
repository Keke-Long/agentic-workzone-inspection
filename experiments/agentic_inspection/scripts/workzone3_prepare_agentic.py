from pathlib import Path
import json,csv,hashlib,shutil
R=Path('/home/klong23/workzone');E=R/'experiments/agentic_inspection';C=E/'cases/workzone_03';B=E/'artifacts/workzone_03/bev_reconstruction/scene_bev';A=E/'artifacts/workzone_03/agentic_final_review81'
def save(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
A.mkdir(exist_ok=True)
p=C/'scene.json';scene=json.loads(p.read_text());backup=A/'scene_before_agentic.json'
if not backup.exists():shutil.copy2(p,backup)
result=json.loads((E/'artifacts/workzone_03/scene_understanding_final_61_85/result.json').read_text());facts=scene['scene_facts'];facts['visual_scene_description']={'facts':result['scene_facts'],'visible_features':result['visible_features'],'corrections':['20 mph is the posted speed, NOT ego vehicle travel speed.','Visible STOP signs do not establish traffic-signal deployment. Intersection control beyond visible signs remains unconfirmed.']};facts['visual_scene_description_provenance']='Model derived from 16 current 61–85 s images; raw request and response in scene_understanding_final_61_85. Explicit user facts take precedence.';facts['layout_uncertainties']=result['unresolved_layout_questions'];facts['user_confirmed_absent_classes']=['barricade','road_barrier','vertical_panel','arrow_board','pcms','worker','work_vehicle'];facts['arrow_board_deployed']=False;facts['pcms_deployed']=False;facts['device_absence_provenance']='Explicit user case-level statement during final review, not inferred from zero detections.';facts['inspection_scope']='Only Case_14 61–85 seconds camera0 and LiDAR. Opposing lane fully closed, ego lane open, actual opposing routing unknown.'
# Correct two wording errors in the model-derived synopsis without modifying its raw response.
for x in facts['visual_scene_description']['facts']:
 x['fact']=x['fact'].replace('sensor-car speed is 20 mph','posted speed limit is 20 mph').replace('signalized/stop-controlled-looking cross street intersection','cross street intersection with visible STOP signs; signalization is not established')
objects=json.loads((B/'objects.json').read_text());byobj={x['object_id']:x for x in objects['objects']};rows={x['observation_id']:x for x in json.loads((B/'observations.json').read_text())}
for obs in scene['accepted_observations']:
 mapping=objects['observation_mapping'].get(obs['observation_id']);obs['geometry_eligible']=False;obs['entity_linkage_eligible']=False
 if mapping:
  obj=byobj[mapping['object_id']];r=rows[obs['observation_id']];obs['refined_element_id']=obj['object_id'];obs['raw_device_id']=obj['object_id'];obs['bev_object_id']=obj['object_id'];obs['location_validation']=obj['position_status'];obs['xyz']=r['world_xyz_m'] if mapping['method']=='world_cluster' else obj['world_xyz_m'];obs['geometry_eligible']=obj['position_status']=='multi_frame_supported' and r['geometry_candidate'];obs['entity_linkage_eligible']=obj['position_status']=='multi_frame_supported'
scene['validated_bev_geometry']={'policy':'Only source-bound BEV; single-frame positions cannot support quantitative findings','files':{name:{'path':str(B/file),'sha256':hashlib.sha256((B/file).read_bytes()).hexdigest()} for name,file in [('observations','observations.json'),('objects','objects.json'),('validation','validation.json'),('reconstruction','reconstruction.json')]}}
scene['data_sources']['validated_bev_objects']=str(B/'objects.json');scene['data_sources']['validated_bev_observations']=str(B/'observations.json');scene['scene_facts']['geometry_evidence_summary']={'candidate_positions':31,'multi_frame_supported':22,'unresolved_observations':75,'source':'validated raw LiDAR reconstruction, not surveyed truth'}
# Current frame set, including enough approach and work-area views.
scene['raw_images']=[x['source'] for x in json.loads((E/'artifacts/workzone_03/scene_understanding_final_61_85/input_manifest.json').read_text())]
save(p,scene);save(C/'input_evidence/reviewed_bboxes.json',scene['accepted_observations']);save(C/'input_evidence/user_adjudications.json',{'review_revision':81,'source':str(R/'data/workzone_03/detections/final_detections.json'),'case_facts':facts,'basis':'user confirmed final reviewed detections and completed bbox correction'})
with (C/'input_evidence/device_inventory.csv').open('w') as f:
 writer=csv.DictWriter(f,fieldnames=['id','class_name','inspection_layer','eligible_for_any_position_plot','x_enu_m','y_enu_m']);writer.writeheader()
 for o in objects['objects']:writer.writerow({'id':o['object_id'],'class_name':'channelizing_device' if o['family']=='channelizer' else o['family'],'inspection_layer':'active_device','eligible_for_any_position_plot':'True','x_enu_m':o['world_xyz_m'][0],'y_enu_m':o['world_xyz_m'][1]})
configs={}
for key in ['stage1_kg_bm25','stage3','stage4','stage5','stage6']:
 p=E/'config/workzone_03'/f'{key}.json';cfg=json.loads(p.read_text());(A/'original_configs').mkdir(exist_ok=True)
 if not (A/'original_configs'/p.name).exists():shutil.copy2(p,A/'original_configs'/p.name)
 cfg['output_directory']=str((A/('stage0_1_2' if key=='stage1_kg_bm25' else key)).relative_to(E));cfg['execution']['lock_reason']='User explicitly requests complete Stage 1–6 after final review and BEV; normal stage checkpoints automatically continued.';configs[key]=cfg
for key,cfg in configs.items():
 if key!='stage1_kg_bm25':
  prev={'stage3':'stage1_kg_bm25','stage4':'stage3','stage5':'stage4','stage6':'stage5'}[key];base=E/configs[prev]['output_directory']
  for field,filename in [('resume_stage0_record','stage_0_layout_selection.json'),('resume_registry_checkpoint','stage_1_to_6_registry.json'),('resume_tool_trace','tool_trace.json')]:cfg['execution'][field]=str(base/filename)
 save(E/'config/workzone_03'/f'{key}.json',cfg)
save(A/'input_binding.json',{'review_revision':81,'scene_sha256':hashlib.sha256((C/'scene.json').read_bytes()).hexdigest(),'final_detections':str(R/'data/workzone_03/detections/final_detections.json'),'scope':[61,85],'manual':'MUTCD 11th Edition (December 2023), same frozen KG+BM25 source as Workzone 1; no Wisconsin manual substitution','authorization':'User requested entire agentic pipeline after final inspection/BEV; preserve six stage records plus Stage 0 layout selection'})
print('Agentic inputs prepared',sum(x['geometry_eligible'] for x in scene['accepted_observations']),'supported geometry observations')
