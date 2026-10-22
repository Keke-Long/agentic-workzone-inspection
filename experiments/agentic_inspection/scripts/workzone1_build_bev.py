#!/usr/bin/env python3
"""Reconstruct camera0 Workzone 1 using Case_00, reusing corrected BEV algorithms.
No old multi-camera condition or compliance conclusions are imported.
"""
from pathlib import Path
import json,hashlib
import numpy as np,pandas as pd
import case18_build_bev as builder
import case18_bev_objects as associate
from scene_data_tools_v5 import SceneDataToolsV5
R=Path('/home/klong23/workzone');E=R/'experiments/agentic_inspection'
A=E/'artifacts/workzone_01/bev_reconstruction';O=A/'scene_bev'
RAW=Path('/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_00')
def main():
 O.mkdir(parents=True,exist_ok=True)
 scene=json.loads((E/'cases/workzone_01/scene.json').read_text());scene['semantic_only_observations']=[]
 scene['dataset_root']=str(R/'data/workzone_01/processed');scene['metadata_root']=str(R/'data/workzone_01/processed/CATS_v1.0');scene['source_raw_root']=str(RAW)
 scene['raw_source_verification']='Case_00 INS translation matches all retained LiDAR metadata poses; Case_01 is not this scene.'
 (A/'scene.json').write_text(json.dumps(scene,ensure_ascii=False,indent=2))
 t=SceneDataToolsV5(A/'scene.json');df=pd.read_csv(RAW/'ins/gnss.csv');times=df['_header._stamp._sec']+df['_header._stamp._nanosec']*1e-9
 errors=[]
 for pose in t._trajectory:
  ts=pose['timestamp_us']/1e6
  pred=np.array([np.interp(ts,times,df[k]) for k in ['_east_x_from_longitude','_north_y_from_latitude','_up_z_from_height']]);errors.append(float(np.linalg.norm(pred-np.array(pose['translation']))))
 assert max(errors)<1e-5
 source={'raw_root':str(RAW),'metadata_pose_count':len(errors),'max_INS_translation_difference_m':max(errors),'camera_scope':['CAM_FRONT'],'accepted_observations':len(t.observations),'historical_mislabeled_raw_root':'/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_01','condition_and_compliance':'not reassessed in this BEV task'}
 (O/'source_validation.json').write_text(json.dumps(source,indent=2))
 builder.A=A;builder.O=O;builder.RAW=RAW
 builder.TIME_RANGE=(min(p['timestamp_us'] for p in t._trajectory)/1e6-.00001,max(p['timestamp_us'] for p in t._trajectory)/1e6+.00001)
 builder.main()
 associate.A=A;associate.O=O;associate.RAW=RAW
 associate.family=lambda cl:'channelizer' if cl in ['traffic_cone','traffic_drum','delineator','channelizing_device','barricade','road_barrier'] else cl
 associate.main()
 p=O/'objects.json';s=p.read_text().replace('C18_OBJ_','W1_OBJ_').replace('case18_bev_objects_v1','workzone1_bev_objects_v1');data=json.loads(s)
 for obj in data['objects']:obj['condition_status']='not_reassessed'
 data['counts']['object_condition_counts']={'not_reassessed':len(data['objects'])};data['condition_policy']='No object condition reassessment performed; old multi-camera judgments are not imported.'
 p.write_text(json.dumps(data,ensure_ascii=False,indent=2))
 print('WORKZONE1 COMPLETE',data['counts'],flush=True)
if __name__=='__main__':main()
