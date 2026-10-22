"""Read source-bound raw-LiDAR BEV geometry through the staged scene tool API."""
from pathlib import Path
import json,hashlib
import numpy as np

def locate_from_bev(scene, observation_id):
 config=scene.scene_record.get('validated_bev_geometry')
 if not config:return None
 obs=scene.observations.get(observation_id)
 if not obs:return {'status':'failure','failure_reason':'unknown accepted observation_id'}
 cache=getattr(scene,'_validated_bev_cache',None)
 if cache is None:
  for name,info in config['files'].items():
   p=Path(info['path'])
   if hashlib.sha256(p.read_bytes()).hexdigest()!=info['sha256']:raise ValueError('Frozen BEV source changed: '+name)
  rows=json.loads(Path(config['files']['observations']['path']).read_text());objects=json.loads(Path(config['files']['objects']['path']).read_text())
  cache=({x['observation_id']:x for x in rows},objects,{x['object_id']:x for x in objects['objects']});scene._validated_bev_cache=cache
 rows,objects,byid=cache;r=rows.get(observation_id)
 if r is None or r['bbox']!=obs['bbox'] or r['class']!=obs['reviewed_class']:return {'status':'failure','failure_reason':'BEV observation does not match accepted class and bbox'}
 mapping=objects['observation_mapping'].get(observation_id)
 if not mapping:return {'status':'unavailable_after_attempt','observation_id':observation_id,'failure_reason':'No validated raw-LiDAR location or unique multi-frame identity','quality_flags':r['quality_flags'],'associated_lidar_frames':[r['raw_lidar']]}
 obj=byid[mapping['object_id']];xyz=obj['world_xyz_m'];road=scene._project_to_trajectory(xyz[:2]);support=[rows[i] for i in obj['geometry_observation_ids']];coords=np.array([x['world_xyz_m'] for x in support]);stations=[scene._project_to_trajectory(x[:2])['station_m'] for x in coords];lat=[scene._project_to_trajectory(x[:2])['signed_lateral_offset_m'] for x in coords];stable=obj['position_status']=='multi_frame_supported'
 station=road['station_m'];lateral=road['signed_lateral_offset_m'];interval=[min(stations+[station])-.5,max(stations+[station])+.5];lat_interval=[min(lat+[lateral])-.5,max(lat+[lateral])+.5];unc=max(station-interval[0],interval[1]-station);spatial=max(.5,obj['world_xy_max_radius_m']+.5);usable=stable and abs(lateral)<=scene.geometry_policy['lateral_residual_reject_m']
 return {'status':'acquired','location_id':'bev_'+obj['object_id']+'_'+observation_id,'observation_id':observation_id,'global_xyz_m':xyz,'uncertainty_m':spatial,'spatial_uncertainty_m':spatial,'road_station_m':station,'station_confidence_interval_m':interval,'station_uncertainty_m':unc,'station_sample_count':len(support),'trajectory_lateral_offset_m':lateral,'lateral_confidence_interval_m':lat_interval,'trajectory_lateral_residual_m':abs(lateral),'trajectory_lateral_residual_p95_m':max(abs(x) for x in lat_interval),'longitudinal_geometry_usable':usable,'trajectory_local_tangent_xy':road['tangent_xy'],'trajectory_local_normal_xy':road['normal_xy'],'projected_points_in_bbox':r['point_count'],'depth_cluster_points':r['point_count'],'associated_image_ids':[Path(obs['source_image']).stem],'associated_bbox_ids':[observation_id],'associated_lidar_frames':sorted({x['raw_lidar'] for x in support}),'trajectory_pose_source':str(scene.meta_root/'ego_pose.json'),'calibration_source':str(scene.meta_root/'calibrated_sensor.json'),'measurement_method':'Previously validated per-point raw-LiDAR + INS reconstruction, complete-link multi-frame object; conservative support range expanded by 0.5 m (not calibrated statistical CI)','quality_flags':['not_survey_grade','conservative_support_range_not_statistical_confidence_interval']+([] if stable else ['single_frame_or_ambiguous_position'])+([] if usable else ['longitudinal_geometry_not_usable']),'failure_reason':None,'object_id':obj['object_id'],'independent_geometry_frames':obj['independent_geometry_frames'],'source_files':config['files']}
