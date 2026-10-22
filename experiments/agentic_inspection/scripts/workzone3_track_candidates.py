#!/usr/bin/env python3
"""Conservative image-overlap tracklets for representative crop verification only.
These are not 3D object identities; all original detections remain traceable.
"""
from pathlib import Path
import json
import numpy as np
from scipy.optimize import linear_sum_assignment
R=Path('/home/klong23/workzone');D=R/'data/workzone_03/detections';O=R/'experiments/agentic_inspection/artifacts/workzone_03/detection_verification'
def ious(a,b):
 a=np.array(a);b=np.array(b);lo=np.maximum(a[:,None,:2],b[None,:,:2]);hi=np.minimum(a[:,None,2:],b[None,:,2:]);inter=np.maximum(0,hi-lo).prod(2);aa=(a[:,2:]-a[:,:2]).prod(1);bb=(b[:,2:]-b[:,:2]).prod(1);return inter/np.maximum(aa[:,None]+bb[None,:]-inter,1e-9)
def build(files):
 tracks=[]
 for frame,p in enumerate(files):
  rows=json.loads(p.read_text())['detections']
  if not rows:continue
  active=[i for i,t in enumerate(tracks) if frame-t['last_frame']<=2]
  matched=set()
  if active:
   ov=ious([tracks[i]['observations'][-1]['bbox'] for i in active],[x['bbox'] for x in rows]);a,b=linear_sum_assignment(1-ov)
   for ia,ib in zip(a,b):
    # Class compatibility prevents a cone from matching an adjacent sign.
    t=tracks[active[ia]]
    if ov[ia,ib]>=.5 and t['observations'][-1]['class']==rows[ib]['class']:
     t['observations'].append(rows[ib]);t['last_frame']=frame;matched.add(ib)
  for j,row in enumerate(rows):
   if j not in matched:tracks.append({'track_id':f'W3_TRACK_{len(tracks):05d}','last_frame':frame,'observations':[row]})
 return tracks
if __name__=='__main__':
 files=sorted((D/'frames').glob('*.json'));tracks=build(files);O.mkdir(parents=True,exist_ok=True)
 result=[]
 for t in tracks:
  rows=t['observations'];best=max(rows,key=lambda x:x['confidence']*(max(1,(x['bbox'][2]-x['bbox'][0])*(x['bbox'][3]-x['bbox'][1])))**.25)
  result.append({'track_id':t['track_id'],'observation_ids':[x['observation_id'] for x in rows],'representative':best,'observation_count':len(rows),'class':best['class']})
 (O/'tracklets.json').write_text(json.dumps({'schema':'provisional_2d_tracklets_v1','policy':'same-class adjacent-frame bbox IoU >= .5, max 1 missing frame; not 3D identity or human verification','tracks':result},indent=2));print('Frames',len(files),'tracks',len(tracks),'multi-frame',sum(len(x['observations'])>1 for x in tracks))
