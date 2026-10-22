#!/usr/bin/env python3
"""Conservative spatial identity candidates and object-level condition propagation."""
import json,collections
from pathlib import Path
import numpy as np
from scipy.cluster.hierarchy import linkage,fcluster
from scipy.spatial.distance import pdist,squareform
from scene_data_tools_v5 import SceneDataToolsV5,_rotation
from case18_sign_geometry import A,RAW,body_to_enu
from scipy.spatial.transform import Slerp
import pandas as pd
O=A/'scene_bev'
def family(cl):
 return 'channelizer' if cl in ['traffic_cone','barricade','road_barrier'] else cl

def iou(a,b):
 lo=np.maximum(a[:2],b[:2]);hi=np.minimum(a[2:],b[2:]);v=np.prod(np.maximum(0,hi-lo));return float(v/(np.prod(np.array(a[2:])-a[:2])+np.prod(np.array(b[2:])-b[:2])-v))
def main():
 rows=json.loads((O/'observations.json').read_text());byid={x['observation_id']:x for x in rows};vlm=json.loads((A/'qwen_serviceability/final_summary.json').read_text()) if (A/'qwen_serviceability/final_summary.json').exists() else {'observations':[]};conditions={x['observation_id']:x for x in vlm['observations']};objects=[];mapping={};conflicts=[]
 for fam in sorted(set(family(x['class']) for x in rows)):
  good=[x for x in rows if family(x['class'])==fam and x['geometry_candidate']];xy=np.array([x['world_xyz_m'][:2] for x in good])
  if len(good)>1:
   distances=squareform(pdist(xy))
   for j,a in enumerate(good):
    for k in range(j+1,len(good)):
     b=good[k]
     if a['frame']==b['frame'] and iou(a['bbox'],b['bbox'])<.15:
      if distances[j,k]<1:conflicts.append([a['observation_id'],b['observation_id']])
      distances[j,k]=distances[k,j]=1e6
   labels=fcluster(linkage(squareform(distances),method='complete'),t=1.0,criterion='distance')
  else:labels=np.ones(len(good),int)
  for label in sorted(set(labels)):
   group=[x for x,l in zip(good,labels) if l==label];same_frame_conflict=any(a['frame']==b['frame'] and iou(a['bbox'],b['bbox'])<.15 for j,a in enumerate(group) for b in group[j+1:])
   # Conflicting same-frame detections can represent two close objects. Do not silently merge them.
   groups=[[x] for x in group] if same_frame_conflict else [group]
   if same_frame_conflict:conflicts.append([x['observation_id'] for x in group])
   for group in groups:
    xyz=np.array([x['world_xyz_m'] for x in group]);loc=np.median(xyz,axis=0);frames=sorted(set(x['frame'] for x in group));stable=len(frames)>=2 and any(x['bbox_human_accepted'] for x in group) and not same_frame_conflict
    obj={'object_id':f'C18_OBJ_{len(objects)+1:03d}','family':fam,'classes':sorted(set(x['class'] for x in group)),'world_xyz_m':loc.tolist(),'local_xy_m':np.median([x['local_xy_m'] for x in group],axis=0).tolist(),'station_m':float(np.median([x['station_m'] for x in group])),'independent_geometry_frames':len(frames),'world_xy_max_radius_m':float(np.linalg.norm(xyz[:,:2]-loc[:2],axis=1).max()),'position_status':'multi_frame_supported' if stable else 'single_frame_or_ambiguous','geometry_observation_ids':[x['observation_id'] for x in group],'observation_ids':[x['observation_id'] for x in group],'same_frame_identity_conflict':same_frame_conflict}
    objects.append(obj)
    for x in group:mapping[x['observation_id']]={'object_id':obj['object_id'],'method':'world_cluster'}
 # Reproject established multi-frame object locations to associate low-quality views.
 t=SceneDataToolsV5(A/'scene.json');df=pd.read_csv(RAW/'ins/gnss.csv');times=(df['_header._stamp._sec']+df['_header._stamp._nanosec']*1e-9).to_numpy();pos=df[['_east_x_from_longitude','_north_y_from_latitude','_up_z_from_height']].to_numpy();sl=Slerp(times,body_to_enu(df['_azimuth'],df['_pitch'],df['_roll']))
 unresolved=[]
 for x in rows:
  if x['observation_id'] in mapping:continue
  cr=t.sample_data_by_filename[Path(x['source_image']).name];ct=cr['timestamp']/1e6;cp=np.array([np.interp(ct,times,pos[:,j]) for j in range(3)]);r=sl(ct);cal=t.calibrations[cr['calibrated_sensor_token']];candidates=[];b=np.array(x['bbox']);ctr=(b[:2]+b[2:])/2;half=(b[2:]-b[:2])/2
  for obj in objects:
   if obj['family']!=family(x['class']) or obj['position_status']!='multi_frame_supported':continue
   v=(r.inv().apply(np.array(obj['world_xyz_m'])-cp)-cal['translation'])@_rotation(cal['rotation'])
   if v[2]<=.5 or v[2]>100:continue
   uv=np.array(cal['camera_intrinsic'])@v;uv=uv[:2]/uv[2];offset=abs((uv-ctr)/half)
   if max(offset)<.9:candidates.append(obj)
  if len(candidates)==1:
   obj=candidates[0];obj['observation_ids'].append(x['observation_id']);mapping[x['observation_id']]={'object_id':obj['object_id'],'method':'unique_reprojection_of_multiframe_object'}
  else:unresolved.append({'observation_id':x['observation_id'],'class':x['class'],'frame':x['frame'],'reason':'ambiguous_reprojection' if candidates else 'no_reliable_3d_or_unique_identity','candidate_objects':[o['object_id'] for o in candidates]})
 for obj in objects:
  evidence=[conditions[k] for k in obj['observation_ids'] if k in conditions];usable=[x['observation_id'] for x in evidence if x['status']=='visible_serviceable'];bad=[x['observation_id'] for x in evidence if x['status']=='visible_unserviceable'];uncertain=[x['observation_id'] for x in evidence if x['status']=='uncertain']
  reliable=obj['position_status']=='multi_frame_supported'
  if usable and bad:condition='conflicting_clear_views'
  elif bad:condition='visible_defect'
  elif usable:condition='supported_serviceable' if reliable else 'serviceable_view_identity_provisional'
  elif evidence:condition='uncertain_no_clear_view'
  else:condition='not_condition_target'
  obj.update(condition_status=condition,clear_serviceable_observation_ids=usable,uncertain_observation_ids=uncertain,defect_observation_ids=bad,uncertain_views_resolved_by_same_object=uncertain if usable and not bad and reliable else [],observation_count=len(obj['observation_ids']))
 result={'schema':'case18_bev_objects_v1','objects':objects,'observation_mapping':mapping,'unresolved_observations':unresolved,'identity_conflicts':conflicts,'counts':{'observations':len(rows),'objects_with_candidate_position':len(objects),'multi_frame_supported_objects':sum(o['position_status']=='multi_frame_supported' for o in objects),'mapped_observations':len(mapping),'unresolved_observations':len(unresolved),'object_condition_counts':dict(collections.Counter(o['condition_status'] for o in objects)),'uncertain_views_resolved_by_same_object':sum(len(o['uncertain_views_resolved_by_same_object']) for o in objects)},'identity_policy':'Complete-link XY clustering maximum 1m diameter, class family compatible; same-frame disjoint boxes prevent merge; at least 2 independent frames and an accepted bbox required for stable location. Weak views attach only through unique reprojection into their box. These are inferred identities, not manually verified physical IDs.','condition_policy':'At least one clear serviceable observation plus no conflicting clear defect supports object-level visible serviceability; uncertain images do not negate that. Propagation requires multiframe-supported identity.'}
 assert len(mapping)+len(unresolved)==len(rows);assert len(mapping)==len(set(mapping));assert sum(len(o['observation_ids']) for o in objects)==len(mapping)
 (O/'objects.json').write_text(json.dumps(result,indent=2));print(json.dumps(result['counts'],indent=2))
if __name__=='__main__':main()
