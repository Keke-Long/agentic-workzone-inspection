"""Check final human boxes, geometry partition, time scope, and object support."""
from pathlib import Path
import json,sqlite3,hashlib,collections
import numpy as np
R=Path('/home/klong23/workzone');E=R/'experiments/agentic_inspection';D=R/'data/workzone_03/detections';O=E/'artifacts/workzone_03/bev_reconstruction/scene_bev'
def main():
 final=json.loads((D/'final_detections.json').read_text());accepted={x['observation_id']:x for x in final['observations']};rows=json.loads((O/'observations.json').read_text());objects=json.loads((O/'objects.json').read_text());recon=json.loads((O/'reconstruction.json').read_text());trajectory=json.loads((O/'trajectory.json').read_text());cloud=np.load(O/'pointcloud_display.npz')['xyz']
 with sqlite3.connect(D/'human_review.sqlite3') as c:rev,encoded=c.execute('select revision,decisions from state where id=1').fetchone()
 review=json.loads(encoded);assert rev==final['review_revision'] and hashlib.sha256(encoded.encode()).hexdigest()==final['review_decisions_sha256']
 assert len(rows)==len(accepted) and set(x['observation_id'] for x in rows)==set(accepted)
 assert sum(x.get('bbox_review_status')=='human_corrected' for x in review.values())==41
 assert all(x['status']!='fix_box' for x in review.values())
 for row in rows:
  a=accepted[row['observation_id']];d=review[a['track_id']]
  assert row['bbox']==a['bbox']==d['bbox'] and row['class']==d['reviewed_class'] and row['bbox_human_accepted']
  assert 61<=float(row['raw_lidar'][:-4])<=85 and abs(row['time_difference_s'])<=.101
  if row['geometry_candidate']:assert not row['quality_flags'] and np.isfinite(row['world_xyz_m']).all()
 mapped=objects['observation_mapping'];unresolved={x['observation_id'] for x in objects['unresolved_observations']};assert set(mapped).isdisjoint(unresolved) and set(mapped)|unresolved==set(accepted)
 byid={x['observation_id']:x for x in rows}
 for obj in objects['objects']:
  good=[byid[i] for i in obj['geometry_observation_ids']];xyz=np.array([x['world_xyz_m'] for x in good]);assert np.isfinite(xyz).all()
  if len(xyz)>1:assert np.max(np.linalg.norm(xyz[:,None,:2]-xyz[None,:,:2],axis=2))<=1.000001
  if obj['position_status']=='multi_frame_supported':assert len({accepted[x['observation_id']]['timestamp_us'] for x in good})>=2
  assert obj['condition_status']=='not_reassessed' and all(i in accepted for i in obj['observation_ids'])
 assert recon['raw_lidar_frames']==240 and recon['point_timestamp_window_s']==[61,85] and len(trajectory)==240
 assert all(61e6<=x['timestamp_us']<=85e6 for x in trajectory) and np.isfinite(cloud).all()
 out={'passed':True,'review_revision':rev,'observations':len(rows),'class_counts':final['counts'],'corrected_boxes_used':41,'counts':objects['counts'],'object_families':dict(collections.Counter(x['family'] for x in objects['objects'])),'geometry_flags':dict(collections.Counter(flag for x in rows for flag in x['quality_flags'])),'input_window_s':[61,85],'raw_lidar_frames':240,'display_points':len(cloud),'reviewed_boxes_match_exactly':True,'object_mapping_partition_complete':True,'max_clustering_diameter_m':1,'multi_frame_support_uses_distinct_image_timestamps':True,'compliance_assessed':False}
 (O/'validation.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
if __name__=='__main__':main()
