#!/usr/bin/env python3
"""Full-scene corrected raw-LiDAR accumulation and reviewed observation associations.
Read-only sources; original human boxes/classes preserved. No surveyed-accuracy claims.
"""
import json,collections
import numpy as np,pandas as pd
from scipy.spatial.transform import Slerp
from case18_sign_geometry import A,RAW,DT,read_pcd,body_to_enu
from scene_data_tools_v5 import SceneDataToolsV5,_rotation
O=A/'scene_bev';O.mkdir(exist_ok=True)
def main():
 t=SceneDataToolsV5(A/'scene.json');scene=t.scene_record;obs=scene['accepted_observations']+scene['semantic_only_observations'];df=pd.read_csv(RAW/'ins/gnss.csv');times=(df['_header._stamp._sec']+df['_header._stamp._nanosec']*1e-9).to_numpy();pos=df[['_east_x_from_longitude','_north_y_from_latitude','_up_z_from_height']].to_numpy();sl=Slerp(times,body_to_enu(df['_azimuth'],df['_pitch'],df['_roll']))
 def poses(ts):
  assert np.min(ts)>=times[0] and np.max(ts)<=times[-1]
  return np.column_stack([np.interp(ts,times,pos[:,j]) for j in range(3)]),sl(ts)
 lc=next(c for c in t.calibrations.values() if not c['camera_intrinsic']);rl=_rotation(lc['rotation']);tl=np.array(lc['translation']);files=sorted(RAW.joinpath('lidar').glob('*.pcd'),key=lambda p:float(p.stem));window=globals().get('TIME_RANGE')
 if window is not None:files=[f for f in files if window[0]<=float(f.stem)<=window[1]]
 ft=np.array([float(p.stem) for p in files]);byfile=collections.defaultdict(list)
 for x in obs:
  cr=t.sample_data_by_filename[__import__('pathlib').Path(x['source_image']).name];ct=cr['timestamp']/1e6;byfile[int(np.argmin(abs(ft-ct)))].append((x,cr,ct))
 rows=[];cloud=[];totalpoints=0;origin=np.array(t._trajectory[0]['translation']);forward=np.array(t._trajectory[10]['translation'])[:2]-origin[:2];forward/=np.linalg.norm(forward);basis=np.array([forward,[-forward[1],forward[0]]]).T
 for fi,file in enumerate(files):
  pc=read_pcd(file);xyz=np.column_stack([pc[k] for k in ['x','y','z']]);totalpoints+=len(pc);p,r=poses(pc['timestamp']);world=r.apply(xyz@rl.T+tl)+p
  # Display background only: sampled, not a static-object segmentation.
  inds=np.arange(0,len(world),150);near=(np.linalg.norm(xyz[inds,:2],axis=1)<60)&np.isfinite(world[inds]).all(axis=1);selected=world[inds[near]];local=(selected[:,:2]-origin[:2])@basis;cloud.append(np.column_stack([local,selected[:,2]-origin[2]]).astype('f4'))
  for x,cr,ct in byfile.get(fi,[]):
   cp,rr=poses(np.array([ct]));cal=t.calibrations[cr['calibrated_sensor_token']];cam=(rr[0].inv().apply(world-cp[0])-cal['translation'])@_rotation(cal['rotation']);depth=cam[:,2];valid=np.flatnonzero(depth>.5);uvh=cam[valid]@np.array(cal['camera_intrinsic']).T;uv=uvh[:,:2]/uvh[:,2:];b=np.array(x['bbox']);ctr=(b[:2]+b[2:])/2;half=(b[2:]-b[:2])/2
   delta=abs((uv-ctr)/half);is_sign=x['reviewed_class'] in ['road_work_ahead','right_lane_closed','merging_sign'];central=(delta.sum(axis=1)<.65) if is_sign else ((delta[:,0]<.6)&(delta[:,1]<.7));use=valid[central];d=depth[use]
   if len(use)>=3:
    lo=np.percentile(d,10);use=use[d<=lo+max(.45,.015*lo)]
   w=world[use];reasons=[]
   if len(w)<(30 if is_sign else 8):reasons.append('insufficient_target_points')
   if len(w):
    med=np.median(w,axis=0);spread=float(np.percentile(np.linalg.norm(w-med,axis=1),90));dist=float(np.median(depth[use]));station=t._project_to_trajectory(med[:2]);local=(med[:2]-origin[:2])@basis
    if dist>60:reasons.append('range_over_60m')
    if spread>1:reasons.append('cluster_spread_over_1m')
   else:med=np.full(3,np.nan);spread=dist=None;station={};local=np.full(2,np.nan)
   if min(b[:2])<=0 or b[2]>=3840 or b[3]>=2160:reasons.append('image_edge_truncation')
   rows.append({'observation_id':x['observation_id'],'class':x['reviewed_class'],'frame':x['frame'],'bbox':x['bbox'],'source_image':x['source_image'],'bbox_human_accepted':x in scene['accepted_observations'],'world_xyz_m':med.tolist() if len(w) else None,'local_xy_m':local.tolist() if len(w) else None,'station_m':station.get('station_m'),'lateral_m':station.get('signed_lateral_offset_m'),'range_m':dist,'point_count':len(w),'spread_p90_m':spread,'geometry_candidate':not reasons,'quality_flags':reasons,'raw_lidar':file.name,'time_difference_s':float(file.stem)-ct})
  if (fi+1)%40==0:print(f'{fi+1}/{len(files)} raw frames; {len(rows)}/{len(obs)} observations',flush=True)
 cloud=np.concatenate(cloud);voxel=np.floor(cloud/.35).astype(np.int32);_,ix=np.unique(voxel,axis=0,return_index=True);cloud=cloud[ix];np.savez_compressed(O/'pointcloud_display.npz',xyz=cloud)
 trajectory=[{'timestamp_us':x['timestamp_us'],'world_xyz_m':x['translation'],'local_xy_m':((np.array(x['translation'][:2])-origin[:2])@basis).tolist(),'station_m':x['station_m']} for x in t._trajectory]
 (O/'observations.json').write_text(json.dumps(rows,indent=2));(O/'trajectory.json').write_text(json.dumps(trajectory,indent=2));(O/'reconstruction.json').write_text(json.dumps({'raw_lidar_frames':len(files),'raw_points_processed':totalpoints,'display_voxel_points':len(cloud),'observations':len(rows),'origin_enu_m':origin.tolist(),'display_basis_columns_enu':basis.tolist(),'coordinates':'rigid local metric view: x initial forward, y left; not a flattened station-lateral plot','point_cloud_warning':'Downsampled accumulation includes moving traffic and occlusion artifacts; not an exclusively static semantic map.','pose_convention':'Rz(-azimuth) Rx(pitch) Ry(roll), Y forward','geometry_policy':'Each raw point transformed with interpolated INS pose at its timestamp; camera nearest cloud and full pose time compensation; human classes unchanged.'},indent=2));print('COMPLETE',len(rows),len(cloud))
if __name__=='__main__':main()
