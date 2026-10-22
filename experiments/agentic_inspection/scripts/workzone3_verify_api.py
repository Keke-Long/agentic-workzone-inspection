#!/usr/bin/env python3
"""Independent visual classification of tracklet representatives with recorded API IO."""
from pathlib import Path
import json,io,base64,hashlib
from concurrent.futures import ThreadPoolExecutor,as_completed
from collections import Counter
from PIL import Image,ImageDraw
from api_client import credentials,post_json,output_text
R=Path('/home/klong23/workzone');E=R/'experiments/agentic_inspection';D=R/'data/workzone_03/detections';O=E/'artifacts/workzone_03/detection_verification';C=E/'reports/workzone_03/detection_crops'
CLASSES=['traffic_cone','traffic_sign','stop_sign','parking_sign','other_sign','arrow_board','barricade','road_barrier','vertical_panel','pcms','worker','work_vehicle','background','uncertain']
PROMPT='''Classify the actual object INSIDE each numbered yellow bounding rectangle. Detector proposals are often wrong. Do NOT infer construction role from an ordinary vehicle or person. Class choices: traffic_cone (includes orange traffic drum and delineator post; NEVER fire hydrants), traffic_sign (construction warning, closure or detour sign only, including a sign on the ground), stop_sign (includes STOP/ALL WAY plaques), parking_sign, other_sign (green street-name, speed-limit, and unrelated signs), arrow_board (ONLY actual electronic work-zone LED arrow lamp array, NEVER poles, printed arrows, flags or signs), barricade (striped temporary traffic barricade), road_barrier (concrete/plastic traffic barrier, NOT sidewalk/curb), vertical_panel (flat striped channelizing panel, NOT cylindrical delineator post), pcms (actual portable electronic text display), worker (visible work-related high-visibility clothing/activity, not an ordinary pedestrian), work_vehicle (clearly construction equipment; U-Haul, ordinary cars, vans, trucks are background), background (fire hydrants, utility poles, flags, trees, curbs, grates, ordinary vehicles, etc), uncertain. Distinguish a tall striped cylindrical delineator from a fire hydrant with side outlets. Use uncertain if the object cannot be identified; never guess a traffic sign legend. If a box spans a group of objects, set bbox_quality=multiple_objects rather than accepting it as one object. A partly cut/occluded object is truncated_or_occluded. Report concise visible evidence, not compliance. Return one JSON item per tile with id, class, certainty (clear or uncertain), bbox_quality (single_object, multiple_objects, truncated_or_occluded, uncertain), legend (readable sign text or null), reason (at most 15 words).'''
def batch(index,group,cfg,key,url):
 out=O/'api_batches';out.mkdir(exist_ok=True);p=out/f'batch_{index:04d}.json'
 if p.exists():
  d=json.loads(p.read_text());assert [(x['track_id'],x['observation_id']) for x in d['observations']]==[(t['track_id'],t['representative']['observation_id']) for t in group];return d
 canvas=Image.new('RGB',(1360,320*((len(group)+3)//4)),'#e8edf2');dr=ImageDraw.Draw(canvas)
 for j,t in enumerate(group):
  crop=Image.open(C/(t['track_id']+'.jpg'));crop.thumbnail((330,275));x=j%4*340;y=j//4*320;canvas.paste(crop,(x+(340-crop.width)//2,y+30));dr.text((x+10,y+7),str(j+1),fill='black')
 buff=io.BytesIO();canvas.save(buff,format='JPEG',quality=93);im=buff.getvalue();p.with_suffix('.jpg').write_bytes(im)
 payload={'model':cfg['model'],'reasoning':{'effort':'medium'},'max_output_tokens':5000,'text':{'format':{'type':'json_object'}},'input':[{'role':'user','content':[{'type':'input_text','text':PROMPT+f' There are {len(group)} tiles. Return {{"items":[...]}}.'},{'type':'input_image','image_url':'data:image/jpeg;base64,'+base64.b64encode(im).decode(),'detail':'high'}]}]}
 p.with_suffix('.request.json').write_text(json.dumps(payload));resp,secs=post_json(url+'/v1/responses',key,payload);p.with_suffix('.response.json').write_text(json.dumps(resp,ensure_ascii=False,indent=2));items=json.loads(output_text(resp))['items'];byid={int(x['id']):x for x in items};assert len(items)==len(group) and set(byid)==set(range(1,len(group)+1));assert all(x['class'] in CLASSES for x in items)
 d={'model':resp.get('model',cfg['model']),'latency_seconds':secs,'usage':resp.get('usage'),'image_sha256':hashlib.sha256(im).hexdigest(),'observations':[{'track_id':t['track_id'],'observation_id':t['representative']['observation_id'],**byid[j+1]} for j,t in enumerate(group)]};p.write_text(json.dumps(d,ensure_ascii=False,indent=2));return d

def main():
 cfg=json.loads((E/'config/workzone_03/stage1_kg_bm25.json').read_text());key,url=credentials(cfg);tracks=json.loads((O/'tracklets.json').read_text())['tracks'];stable=[t for t in tracks if t['observation_count']>=3];(O/'api_verification_settings.json').write_text(json.dumps({'model':cfg['model'],'reasoning_effort':'medium','prompt':PROMPT,'batch_size':16,'representative_policy':'one representative per same-class 2D tracklet with >=3 observations; not all frames independently verified','script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2));reviews={};usage=[]
 cache_path=O/'representative_reuse_cache.json';cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}; pending=[]
 for t in stable:
  old=cache.get(t['representative']['observation_id'])
  if old and old['representative']['bbox']==t['representative']['bbox'] and old['representative']['source_image']==t['representative']['source_image']:
   reviews[t['track_id']]={**old['verification'],'track_id':t['track_id'],'reuse_provenance':'identical in-window representative observation and bbox; source image SHA verified during recrop'}
  else:pending.append(t)
 print('Reused',len(reviews),'representatives; new classifications',len(pending),flush=True)
 with ThreadPoolExecutor(max_workers=4) as pool:
  jobs=[pool.submit(batch,i,pending[start:start+16],cfg,key,url) for i,start in enumerate(range(0,len(pending),16))]
  for job in as_completed(jobs):
   d=job.result();usage.append(d['usage']);reviews.update({x['track_id']:x for x in d['observations']});print(f'Verified {len(reviews)}/{len(stable)} representative crops',flush=True)
 out=[]
 for t in tracks:
  r=reviews.get(t['track_id']);t['verification']=r;t['review_status']='model_classified_representative' if r else 'unverified_short_tracklet';t['human_reviewed']=False;t['display_class']=r['class'] if r and r['class']!='uncertain' and r.get('certainty')=='clear' else t['class'];t['filter_group']='unverified'
  if r:t['filter_group']='background' if r['class']=='background' and r.get('certainty')=='clear' else ('uncertain' if r['class']=='uncertain' or r.get('certainty')!='clear' else 'target')
  if t['display_class'] in ['stop_sign','parking_sign','other_sign']:t['filter_group']='other_sign'
  out.append(t)
 summary=json.loads((D/'summary.json').read_text());result={'schema':'workzone_model_reviewed_tracklet_candidates_v1','workzone_id':'workzone_03','frame_count':summary['frame_count'],'raw_candidate_count':summary['candidate_count'],'tracklet_count':len(out),'classification_model':cfg['model'],'model_classified_representatives':len(reviews),'filter_group_counts':dict(Counter(t['filter_group'] for t in out)),'target_class_counts':dict(Counter(t['display_class'] for t in out if t['filter_group']=='target')),'policy':'Provisional 2D tracklets, not physical object counts. One representative classified for tracklets with >=3 observations; other frames remain inferred/unreviewed. Raw/background/uncertain candidates retained. No human acceptance, 3D verification, or normative findings. Earlier Qwen classification failed spot-check and is not used.','tracks':out};(D/'current_detections.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));(D/'verification_summary.json').write_text(json.dumps({k:v for k,v in result.items() if k!='tracks'},ensure_ascii=False,indent=2));print('COMPLETE',result['filter_group_counts'],result['target_class_counts'],flush=True)
if __name__=='__main__':main()
