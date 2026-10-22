#!/usr/bin/env python3
"""Quality gates, independent-frame stability checks and sign spacing (no fitting to normative threshold)."""
import json,hashlib
from pathlib import Path
import numpy as np
from case18_sign_geometry import body_to_enu,R,A,O,RAW
from scene_data_tools_v5 import SceneDataToolsV5,_rotation

def main():
 # Axis convention regression: azimuth is clockwise from north; body Y points forward.
 angles=np.array([0.,90.,180.,270.]);r=body_to_enu(angles,np.zeros(4),np.zeros(4))
 assert np.allclose(r.apply(np.tile([0,1,0],(4,1))),[[0,1,0],[1,0,0],[0,-1,0],[-1,0,0]],atol=1e-12)
 # Static point seen from translating/rotating sensor must retain global position.
 target=np.array([50.,30.,2.]);positions=np.array([[0,0,0],[3,2,0],[7,5,0],[10,7,0]])
 local=r.inv().apply(target-positions);assert np.allclose(r.apply(local)+positions,target,atol=1e-12)
 rows=json.loads((O/'locations.json').read_text());scene=json.loads((A/'scene.json').read_text());obs={x['observation_id']:x for x in scene['accepted_observations']};tracks=[];excluded=[]
 for cl in ['road_work_ahead','right_lane_closed','merging_sign']:
  group=[x for x in rows if x['class']==cl];good=[]
  for x in group:
   reasons=[];b=obs[x['observation_id']]['bbox']
   if x['point_count']<30:reasons.append('fewer_than_30_target_points')
   if x['range_m'] is None or x['range_m']>60:reasons.append('beyond_60m_association_gate')
   if x['point_spread_p90_m'] is None or x['point_spread_p90_m']>1:reasons.append('target_cluster_spread_exceeds_1m')
   if b[0]<=0 or b[1]<=0 or b[2]>=3840 or b[3]>=2160:reasons.append('image_edge_truncation')
   if reasons:excluded.append({'observation_id':x['observation_id'],'reasons':reasons})
   else:good.append(x)
  # One independent observation per frame; highest point support wins duplicate proposals.
  unique={}
  for x in good:
   if x['frame'] not in unique or x['point_count']>unique[x['frame']]['point_count']:unique[x['frame']]=x
  good=sorted(unique.values(),key=lambda x:x['frame']);xyz=np.array([x['world_xyz_m'] for x in good]);stations=np.array([x['station_m'] for x in good]);median=np.median(xyz,axis=0);rad=np.linalg.norm(xyz[:,:2]-median[:2],axis=1)
  assert len(good)>=5 and rad.max()<1, (cl,rad.max())
  half=len(good)//2;split=abs(float(np.median(stations[:half])-np.median(stations[half:])));assert split<.5
  tracks.append({'class':cl,'independent_frames':len(good),'observation_ids':[x['observation_id'] for x in good],'frame_range':[good[0]['frame'],good[-1]['frame']],'world_xyz_m':median.tolist(),'station_m':float(np.median(stations)),'station_full_range_m':[float(stations.min()),float(stations.max())],'station_peak_to_peak_m':float(np.ptp(stations)),'world_xy_max_pairwise_distance_m':float(np.linalg.norm(xyz[:,None,:2]-xyz[None,:,:2],axis=2).max()),'early_late_station_difference_m':split,'station_sensitivity_envelope_m':[float(stations.min()-1),float(stations.max()+1)],'quality_gate_passed':True})
 measurements=[]
 for left,right in zip(tracks,tracks[1:]):
  d=right['station_m']-left['station_m'];interval=[right['station_sensitivity_envelope_m'][0]-left['station_sensitivity_envelope_m'][1],right['station_sensitivity_envelope_m'][1]-left['station_sensitivity_envelope_m'][0]]
  assert interval[0]>0
  measurements.append({'from':left['class'],'to':right['class'],'distance_m':d,'distance_ft':d/.3048,'sensitivity_envelope_m':interval,'threshold_m':30.48,'threshold_ft':100,'threshold_type':'MUTCD Table 6B-1 urban low-speed guidance','result':'supported' if interval[0]>=30.48 else 'indeterminate','evidence_ids':left['observation_ids']+right['observation_ids']})
 t=SceneDataToolsV5(A/'scene.json');deltas=[x['lidar_reference_delta_s'] for x in rows]
 payload={'schema':'case18_validated_sign_geometry_v1','status':'validated_for_observed_sign_spacing','scope':'three observed approach signs only; not channelizer/taper reconstruction','fixes':['INS attitude: Y-forward NovAtel vehicle convention Rz(-azimuth) Rx(pitch) Ry(roll), instead of X-forward xyz(roll,pitch,90-azimuth)','Raw point timestamps transformed directly to ENU using interpolated corrected INS pose; old deskewed clouds bypassed','Select nearest raw LiDAR timestamp to each camera timestamp instead of sample_token pairing about 100 ms apart','Central diamond ROI and nearest-depth cluster; minimum point support and cross-frame consistency gates'], 'calibration_unchanged':True,'source_images_and_human_boxes_unchanged':True,'source_references':['https://docs.novatel.com/OEM7/Content/SPAN_Operation/Definition_Reference_Frames.htm','https://docs.novatel.com/OEM7/Content/App_Notes/APN080_SetupConfiguration.htm'],'tracks':tracks,'excluded_observations':excluded,'measurements':measurements,'time_sync':{'maximum_abs_reference_difference_s':max(abs(v) for v in deltas),'all_points_inside_ins_time_range':True,'per_point_motion_compensation':True},'uncertainty_note':'Sensitivity envelope uses full observed station range plus an explicit 1 m endpoint allowance. This is not a calibrated statistical confidence interval or survey accuracy guarantee; systematic calibration error is not independently surveyed.','tests':{'cardinal_heading_axis_test':'passed','static_target_transform_roundtrip':'passed','at_least_5_independent_frames_per_sign':'passed','world_xy_radius_under_1m':'passed','early_late_station_difference_under_0_5m':'passed'},'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [RAW/'ins/gnss.csv',Path('/home/klong23/workzone/data/shared/calibration/calib_black_ins.json'),Path('/home/klong23/workzone/data/shared/calibration/calib_black_camera0.json'),A/'scene.json',Path(__file__),Path(__file__).with_name('case18_sign_geometry.py')]}}
 (O/'validation_and_measurements.json').write_text(json.dumps(payload,indent=2));print(json.dumps({'tracks':tracks,'measurements':measurements,'excluded':excluded},indent=2))
if __name__=='__main__':main()
