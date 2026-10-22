#!/usr/bin/env python3
"""Prepare camera0 and corrected INS metadata; keep raw LiDAR external."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import cv2
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation, Slerp
from prepare_raw_case import load_module, token, dump, digest

ROOT=Path('/home/klong23/workzone'); E=ROOT/'experiments/agentic_inspection'
BASE=ROOT/'data/workzone_03'; OUT=BASE/'processed'; SCENE='scene-CATS-15'
CAL=ROOT/'data/shared/calibration'; RAW=Path('/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_14')
def main():
 selection=json.loads((BASE/'selection_manifest.json').read_text())
 uc=load_module('undistort_cameras'); cv2.setNumThreads(1)
 files=selection['streams']; cams=files['camera0']['frames']; lasers=files['lidar']['frames']
 im=cv2.imread(cams[0]['path']);h,w=im.shape[:2]
 K,D=uc.load_calib(str(CAL),'camera0');m1,m2,nk=uc.compute_undistort_maps(K,D,(h,w))
 folder=OUT/SCENE/'CAM_FRONT';folder.mkdir(parents=True,exist_ok=True)
 def image(row):
  p=Path(row['path']); ts=int(Decimal(p.stem)*1000000);target=folder/f'workzone3__CAM_FRONT__{ts}.jpg'
  a=cv2.imread(str(p)); assert a.shape[:2]==(h,w)
  if not target.exists():
   assert cv2.imwrite(str(target),uc.undistort_frame(a,m1,m2),[cv2.IMWRITE_JPEG_QUALITY,95])
  return {'input':str(p),'input_sha256':digest(p),'output':str(target),'output_sha256':digest(target),'timestamp_us':ts}
 with ThreadPoolExecutor(max_workers=4) as pool:
  images=[]
  for i,row in enumerate(pool.map(image,cams)):
   images.append(row)
   if i%100==0:print('camera0',i+1,'/',len(cams),flush=True)
 (OUT/'file_manifest.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in images))
 df=pd.read_csv(RAW/'ins/gnss.csv');times=(df['_header._stamp._sec']+df['_header._stamp._nanosec']*1e-9).to_numpy()
 positions=df[['_east_x_from_longitude','_north_y_from_latitude','_up_z_from_height']].to_numpy()
 rot=Rotation.from_euler('ZXY',np.column_stack([-df['_azimuth'],df['_pitch'],df['_roll']]),degrees=True);sl=Slerp(times,rot)
 def quat(r):
  q=r.as_quat();return [float(q[3]),float(q[0]),float(q[1]),float(q[2])]
 li=np.array(json.loads((CAL/'calib_black_ins.json').read_text())['black_ins']['T_lidar_ins']);lr=Rotation.from_quat(li[3:])
 ca=np.array(json.loads((CAL/'calib_black_camera0.json').read_text())['black_camera0']['T_lidar_camera'])
 channels=['LIDAR_TOP','CAM_FRONT'];sensors=[];cal=[];sd=[];ego=[]
 st=token(SCENE,'scene');lt=token(SCENE,'log')
 samples=[{'token':token(SCENE,'sample',i),'timestamp':int(Decimal(Path(x['path']).stem)*1000000),'scene_token':st,'prev':token(SCENE,'sample',i-1) if i else '', 'next':token(SCENE,'sample',i+1) if i+1<len(lasers) else ''} for i,x in enumerate(lasers)]
 laser_t=np.array([x['timestamp_s'] for x in lasers])
 for ch in channels:
  sensors.append({'token':token(SCENE,ch,'sensor'),'channel':ch,'modality':'lidar' if ch=='LIDAR_TOP' else 'camera'})
  cal.append({'token':token(SCENE,ch,'calibration'),'sensor_token':token(SCENE,ch,'sensor'),'translation':(li[:3] if ch=='LIDAR_TOP' else li[:3]+lr.apply(ca[:3])).tolist(),'rotation':quat(lr if ch=='LIDAR_TOP' else lr*Rotation.from_quat(ca[3:])), 'camera_intrinsic':[] if ch=='LIDAR_TOP' else nk.tolist()})
  rows=lasers if ch=='LIDAR_TOP' else cams
  for i,row in enumerate(rows):
   ts=int(Decimal(Path(row['path']).stem)*1000000);t=ts/1e6;tok=token(SCENE,ch,i)
   assert times[0]<=t<=times[-1] and selection['cutoff_s']<=t<=selection['end_s']
   j=i if ch=='LIDAR_TOP' else int(np.argmin(abs(laser_t-t)))
   filename=f'{SCENE}/LIDAR_TOP/workzone3__LIDAR_TOP__{ts}.pcd.bin' if ch=='LIDAR_TOP' else str(Path(images[i]['output']).relative_to(OUT))
   sd.append({'token':tok,'sample_token':samples[j]['token'],'ego_pose_token':tok,'calibrated_sensor_token':token(SCENE,ch,'calibration'),'timestamp':ts,'fileformat':'pcd' if ch=='LIDAR_TOP' else 'jpg','is_key_frame':True,'height':0 if ch=='LIDAR_TOP' else h,'width':0 if ch=='LIDAR_TOP' else w,'filename':filename,'raw_source':row['path'],'processed_file_available':ch!='LIDAR_TOP','prev':token(SCENE,ch,i-1) if i else '','next':token(SCENE,ch,i+1) if i+1<len(rows) else ''})
   ego.append({'token':tok,'timestamp':ts,'translation':[float(np.interp(t,times,positions[:,k])) for k in range(3)],'rotation':quat(sl(t))})
 tables={'sensor':sensors,'calibrated_sensor':cal,'sample':samples,'sample_data':sd,'ego_pose':ego,'scene':[{'token':st,'log_token':lt,'nbr_samples':len(samples),'first_sample_token':samples[0]['token'],'last_sample_token':samples[-1]['token'],'name':SCENE,'description':'Case_14, only 61–85 seconds, camera0 only'}],'log':[{'token':lt,'vehicle':'black','logfile':'RecordBlk_20261006_171718','date_captured':'2026-10-06','location':'madison-wi-usa'}]}
 for name,rows in tables.items():dump(OUT/'CATS_v1.0'/f'{name}.json',rows)
 dump(OUT/SCENE/'CALIBRATION/undistorted_intrinsics.json',{'CAM_FRONT':{'camera_intrinsic':nk.tolist(),'width':w,'height':h}})
 dump(OUT/'processing_manifest.json',{'state':'complete','scene_id':SCENE,'raw_root':str(RAW),'cutoff_s':selection['cutoff_s'],'end_s':selection['end_s'],'camera_images':len(images),'lidar_metadata_rows':len(lasers),'calibration_authorization':'explicit user confirmation: Workzone 3 black vehicle','calibration_sha256':{p.name:digest(p) for p in [CAL/'calib_black_ins.json',CAL/'calib_black_camera0.json']},'script_sha256':digest(__file__),'pose_convention':'NovAtel Y-forward: Rz(-azimuth) Rx(pitch) Ry(roll); position linear + attitude SLERP','images':'same reference OpenCV alpha=0 INTER_LINEAR JPEG95; no extra rotation/crop','lidar':'raw PCD external; no legacy processed bins; point timestamp in [61,85] required for geometry','metadata_sha256':{name:digest(OUT/'CATS_v1.0'/f'{name}.json') for name in tables}})
 print('complete',len(images),len(lasers),flush=True)
if __name__=='__main__':main()
