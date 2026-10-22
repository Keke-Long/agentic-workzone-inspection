#!/usr/bin/env python3
"""Reconstruct only the selected Workzone 3 raw LiDAR window, point-time cropped."""
from pathlib import Path
import json, shutil
import numpy as np
import case18_build_bev as builder
import case18_bev_objects as associate
R=Path('/home/klong23/workzone');E=R/'experiments/agentic_inspection';A=E/'artifacts/workzone_03/bev_reconstruction'
def main():
 A.mkdir(parents=True,exist_ok=True);O=A/'scene_bev';O.mkdir(exist_ok=True)
 shutil.copy2(E/'cases/workzone_03/scene.json',A/'scene.json')
 window=json.loads((E/'cases/workzone_03/input_window.json').read_text());start,end=window['start_s'],window['end_s']
 original=builder.read_pcd;counts={'excluded_outside_window':0,'excluded_invalid':0}
 def read_selected(path):
  pc=original(path);mask=(pc['timestamp']>=start)&(pc['timestamp']<=end);counts['excluded_outside_window']+=int((~mask).sum())
  finite=np.isfinite(np.column_stack([pc[x] for x in ['x','y','z','timestamp']])).all(axis=1);counts['excluded_invalid']+=int((~finite).sum())
  return pc[mask&finite]
 builder.A=A;builder.O=O;builder.RAW=Path('/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_14');builder.TIME_RANGE=(start,end);builder.read_pcd=read_selected
 builder.main()
 p=O/'reconstruction.json';d=json.loads(p.read_text());d.update(workzone_id='workzone_03',point_timestamp_window_s=[start,end],point_filter_counts=counts,status='reviewed_objects_reconstruction_complete');p.write_text(json.dumps(d,indent=2)+'\n')
 associate.A=A;associate.O=O;associate.RAW=builder.RAW;associate.main()
 p=O/'objects.json';objects=json.loads(p.read_text().replace('C18_OBJ_','W3_OBJ_').replace('case18_bev_objects_v1','workzone3_bev_objects_v1'))
 for obj in objects['objects']:obj['condition_status']='not_reassessed'
 objects['counts']['object_condition_counts']={'not_reassessed':len(objects['objects'])};objects['condition_policy']='This task reconstructs positions only; no serviceability or compliance assessment.';p.write_text(json.dumps(objects,indent=2)+'\n')
 import matplotlib;matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 cloud=np.load(O/'pointcloud_display.npz')['xyz'];tr=json.loads((O/'trajectory.json').read_text());xy=np.array([x['local_xy_m'] for x in tr])
 fig,ax=plt.subplots(figsize=(14,7));ax.scatter(cloud[:,0],cloud[:,1],s=.15,c=cloud[:,2],cmap='gray',vmin=-2,vmax=5);ax.plot(xy[:,0],xy[:,1],color='red',lw=1,label='Survey vehicle trajectory');ax.set_aspect('equal');ax.set_xlabel('Local forward (m)');ax.set_ylabel('Local left (m)');ax.set_title('Workzone 3: cropped raw LiDAR + INS; reviewed objects reconstructed separately');ax.legend();fig.tight_layout();fig.savefig(O/'sensor_bev_preview.png',dpi=180);plt.close(fig)
 print(json.dumps(counts),flush=True)
if __name__=='__main__':main()
