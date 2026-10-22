from pathlib import Path
import json,numpy as np,pandas as pd
from scipy.spatial.transform import Slerp
from PIL import Image,ImageDraw
from case18_sign_geometry import read_pcd,body_to_enu
from scene_data_tools_v5 import SceneDataToolsV5,_rotation
R=Path('/home/klong23/workzone');A=R/'experiments/agentic_inspection/artifacts/workzone_01/bev_reconstruction';RAW=Path('/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_00');t=SceneDataToolsV5(A/'scene.json');df=pd.read_csv(RAW/'ins/gnss.csv');times=(df['_header._stamp._sec']+df['_header._stamp._nanosec']*1e-9).to_numpy();pos=df[['_east_x_from_longitude','_north_y_from_latitude','_up_z_from_height']].to_numpy();rot=Slerp(times,body_to_enu(df['_azimuth'],df['_pitch'],df['_roll']))
lc=next(c for c in t.calibrations.values() if not c['camera_intrinsic']);files=sorted((RAW/'lidar').glob('*.pcd'),key=lambda p:float(p.stem));ft=np.array([float(p.stem) for p in files]);chosen=[]
for cl in ['traffic_drum','traffic_sign','barricade']:
 obs=sorted([x for x in t.observations.values() if x['reviewed_class']==cl],key=lambda x:np.prod(np.array(x['bbox'][2:])-x['bbox'][:2]),reverse=True)
 if obs:chosen.append(obs[len(obs)//4])
canvas=Image.new('RGB',(1500,650),'white')
for k,o in enumerate(chosen):
 cr=t.sample_data_by_filename[Path(o['source_image']).name];ct=cr['timestamp']/1e6;pc=read_pcd(files[np.argmin(abs(ft-ct))]);ts=pc['timestamp'];p=np.column_stack([np.interp(ts,times,pos[:,j]) for j in range(3)]);world=rot(ts).apply(np.column_stack([pc[n] for n in ['x','y','z']])@_rotation(lc['rotation']).T+lc['translation'])+p
 cp=np.array([np.interp(ct,times,pos[:,j]) for j in range(3)]);cal=t.calibrations[cr['calibrated_sensor_token']];cam=(rot(ct).inv().apply(world-cp)-cal['translation'])@_rotation(cal['rotation']);idx=np.where(cam[:,2]>.5)[0];uv=cam[idx]@np.array(cal['camera_intrinsic']).T;uv=uv[:,:2]/uv[:,2:];b=np.array(o['bbox']);ctr=(b[:2]+b[2:])/2;half=(b[2:]-b[:2])/2;central=(abs((uv-ctr)/half)<[.6,.7]).all(axis=1);use=idx[central];v=uv[central]
 if len(use)>=3:
  dep=cam[use,2];lo=np.percentile(dep,10);mask=dep<=lo+max(.45,.015*lo);v=v[mask]
 im=Image.open(o['source_image']);rect=[max(0,int(b[0]-100)),max(0,int(b[1]-100)),min(im.width,int(b[2]+100)),min(im.height,int(b[3]+100))];crop=im.crop(rect);draw=ImageDraw.Draw(crop);draw.rectangle([b[0]-rect[0],b[1]-rect[1],b[2]-rect[0],b[3]-rect[1]],outline='red',width=3)
 for u in v:draw.ellipse((u[0]-rect[0]-2,u[1]-rect[1]-2,u[0]-rect[0]+2,u[1]-rect[1]+2),fill='lime')
 crop.thumbnail((490,580));canvas.paste(crop,(k*500,50));ImageDraw.Draw(canvas).text((k*500+5,5),o['observation_id']+' '+o['reviewed_class'],fill='black')
canvas.save(A/'scene_bev/projection_checks.jpg')
