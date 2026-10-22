#!/usr/bin/env python3
"""Validate reconstructed case scope, source matching, coordinates, and viewer data."""
from pathlib import Path
import json,numpy as np,hashlib
R=Path('/home/klong23/workzone');E=R/'experiments/agentic_inspection';O=E/'artifacts/workzone_01/bev_reconstruction/scene_bev'
def main():
 src=json.loads((O/'source_validation.json').read_text());rec=json.loads((O/'reconstruction.json').read_text());obs=json.loads((O/'observations.json').read_text());data=json.loads((O/'objects.json').read_text());tr=json.loads((O/'trajectory.json').read_text());cloud=np.load(O/'pointcloud_display.npz')['xyz'];fixed=json.loads((R/'data/workzone_01/detections/final_detections.json').read_text())
 assert src['max_INS_translation_difference_m']<1e-5 and src['metadata_pose_count']==1027
 assert rec['raw_lidar_frames']==1027 and len(obs)==930
 assert np.isfinite(cloud).all() and len(cloud)>1000 and len(tr)==1027
 assert {o['observation_id'] for o in obs}=={o['observation_id'] for o in fixed['accepted_observations']}
 fixedby={o['observation_id']:o for o in fixed['accepted_observations']}
 for o in obs:
  x=fixedby[o['observation_id']];assert o['bbox']==x['bbox_xyxy'] and o['class']==x['class']
  assert '/CAM_FRONT/' in o['source_image'] and Path(o['source_image']).is_file()
  assert abs(o['time_difference_s'])<.1
 for o in data['objects']:
  assert o['condition_status']=='not_reassessed' and np.isfinite(o['world_xyz_m']).all()
  if o['position_status']=='multi_frame_supported':assert o['independent_geometry_frames']>=2 and o['world_xy_max_radius_m']<=1.000001
 assert data['counts']['mapped_observations']+data['counts']['unresolved_observations']==930
 result={'passed':True,'raw_source_verified_all_poses':True,'raw_lidar_frames':1027,'camera0_observations':930,'display_points':len(cloud),'object_counts':data['counts'],'maximum_abs_camera_lidar_reference_difference_s':max(abs(o['time_difference_s']) for o in obs),'classes_and_boxes_unchanged':True,'condition_not_reassessed':True,'limitations':'Identity and geometry are inferred candidates; no survey accuracy or revised compliance claimed.'}
 (O/'data_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 prov={'raw_root':src['raw_root'],'raw_ins_sha256':hashlib.sha256((Path(src['raw_root'])/'ins/gnss.csv').read_bytes()).hexdigest(),'used_metadata_and_detection_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [R/'data/workzone_01/detections/final_detections.json',R/'data/workzone_01/processed/CATS_v1.0/calibrated_sensor.json',R/'data/workzone_01/processed/CATS_v1.0/ego_pose.json']},'scripts_sha256':{n:hashlib.sha256((E/'scripts'/n).read_bytes()).hexdigest() for n in ['workzone1_build_bev.py','case18_build_bev.py','case18_sign_geometry.py','case18_bev_objects.py','workzone1_render_bev.py','case18_render_bev.py']}}
 (O/'provenance.json').write_text(json.dumps(prov,indent=2));print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
