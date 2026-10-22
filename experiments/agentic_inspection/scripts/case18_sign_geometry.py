#!/usr/bin/env python3
"""Reassociate reviewed signs using NovAtel Y-forward attitude and raw per-point timing.
Original inputs and calibrations are read-only. R_ENU_vehicle = Rz(-azimuth) Rx(pitch) Ry(roll).
"""
import json,sys,hashlib
from pathlib import Path
import numpy as np,pandas as pd
from scipy.spatial.transform import Rotation,Slerp
from PIL import Image,ImageDraw
from scene_data_tools_v5 import SceneDataToolsV5,_rotation
R=Path(__file__).resolve().parents[1];A=R/'artifacts/workzone_18/ta22_user_selected/post_review_20261021';O=A/'sign_geometry_repair';O.mkdir(exist_ok=True)
RAW=Path('/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_18')
DT=np.dtype([('x','<f4'),('y','<f4'),('z','<f4'),('intensity','<f4'),('ring','<u2'),('timestamp','<f8')])
def read_pcd(p):
 with p.open('rb') as f:
  while f.readline().strip()!=b'DATA binary':pass
  return np.frombuffer(f.read(),dtype=DT)
def body_to_enu(azimuth, pitch, roll):
 return Rotation.from_euler('ZXY',np.column_stack([-np.asarray(azimuth),pitch,roll]),degrees=True)

def main():
 t=SceneDataToolsV5(A/'scene.json');df=pd.read_csv(RAW/'ins/gnss.csv');times=(df['_header._stamp._sec']+df['_header._stamp._nanosec']*1e-9).to_numpy();pos=df[['_east_x_from_longitude','_north_y_from_latitude','_up_z_from_height']].to_numpy()
 rot=body_to_enu(df['_azimuth'],df['_pitch'],df['_roll']);sl=Slerp(times,rot)
 def poses(ts):
  assert np.min(ts)>=times[0] and np.max(ts)<=times[-1]
  return np.column_stack([np.interp(ts,times,pos[:,j]) for j in range(3)]),sl(ts)
 lc=next(c for c in t.calibrations.values() if not c['camera_intrinsic']);Rc=_rotation(lc['rotation']);tc=np.array(lc['translation'])
 files=sorted(RAW.joinpath('lidar').glob('*.pcd'),key=lambda p:float(p.stem));ft=np.array([float(p.stem) for p in files]);rows=[]
 obs=sorted([x for x in t.observations.values() if x['reviewed_class'] in ['road_work_ahead','right_lane_closed','merging_sign']],key=lambda x:x['frame'])
 for i,x in enumerate(obs):
  cr=t.sample_data_by_filename[Path(x['source_image']).name];ct=cr['timestamp']/1e6;file=files[np.argmin(abs(ft-ct))];pc=read_pcd(file);xyz=np.column_stack([pc[k] for k in ['x','y','z']]);pt=pc['timestamp'];p,r=poses(pt)
  world=r.apply(xyz@Rc.T+tc)+p
  cp,rr=poses(np.array([ct]));cal=t.calibrations[cr['calibrated_sensor_token']];cam=(rr[0].inv().apply(world-cp[0])-cal['translation'])@_rotation(cal['rotation']);depth=cam[:,2];valid=np.flatnonzero(depth>.5);uvh=cam[valid]@np.array(cal['camera_intrinsic']).T;uv=uvh[:,:2]/uvh[:,2:]
  b=np.array(x['bbox']);inside=(uv[:,0]>=b[0])&(uv[:,0]<=b[2])&(uv[:,1]>=b[1])&(uv[:,1]<=b[3]);idx=valid[inside];u=uv[inside];dep=depth[idx]
  # Restrict to center of diamond to avoid background in bbox corners.
  center=(b[:2]+b[2:])/2;half=(b[2:]-b[:2])/2;diamond=np.sum(abs((u-center)/half),axis=1)<.65
  use=idx[diamond];d=depth[use]
  if len(use)>=3:
   floor=np.percentile(d,10);use=use[d<=floor+max(.5,.015*floor)]
  w=world[use];med=np.median(w,axis=0) if len(w) else np.full(3,np.nan);proj=t._project_points_to_trajectory(w[:,:2]) if len(w) else None
  row={'observation_id':x['observation_id'],'class':x['reviewed_class'],'frame':x['frame'],'point_count':len(use),'world_xyz_m':med.tolist(),'station_m':float(np.median(proj['station_m'])) if proj else None,'lateral_m':float(np.median(proj['signed_lateral_offset_m'])) if proj else None,'range_m':float(np.median(depth[use])) if len(use) else None,'raw_lidar':str(file),'camera_timestamp_s':ct,'lidar_reference_delta_s':float(file.stem)-ct,'point_time_range_s':[float(pt.min()),float(pt.max())],'point_spread_p90_m':float(np.percentile(np.linalg.norm(w-med,axis=1),90)) if len(w) else None}
  rows.append(row)
  np.savez_compressed(O/(x['observation_id']+'.npz'),world=w,uv=u,depth=dep)
  if x['frame'] in [0,10,20,28,62,70,76,82,132,141,152,157]:
   im=Image.open(x['source_image']);draw=ImageDraw.Draw(im);draw.rectangle(b.tolist(),outline='lime',width=3)
   for v in u:draw.ellipse((v[0]-2,v[1]-2,v[0]+2,v[1]+2),fill='red')
   pad=50;im=im.crop((max(0,b[0]-pad),max(0,b[1]-pad),min(im.width,b[2]+pad),min(im.height,b[3]+pad)));im.save(O/(x['observation_id']+'_overlay.jpg'))
  if (i+1)%10==0:print(i+1,flush=True)
 (O/'locations.json').write_text(json.dumps(rows,indent=2))
 for cl in sorted(set(x['class'] for x in rows)):
  a=[x for x in rows if x['class']==cl];print(cl,[(x['frame'],x['point_count'],round(x['station_m'],2) if x['station_m'] else None,round(x['lateral_m'],2) if x['lateral_m'] else None) for x in a])
if __name__=='__main__':main()
