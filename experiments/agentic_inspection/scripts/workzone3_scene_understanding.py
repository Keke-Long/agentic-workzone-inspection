#!/usr/bin/env python3
"""Record factual visual scene understanding before normative retrieval."""
from pathlib import Path
import json,time,hashlib,sys
from PIL import Image
from api_client import credentials,post_json,image_data_url,output_text
R=Path('/home/klong23/workzone');E=R/'experiments/agentic_inspection';O=E/'artifacts/workzone_03/scene_understanding'
def main():
 global O
 final='--final-scope' in sys.argv
 scoped='--later-area' in sys.argv
 if scoped:O=E/'artifacts/workzone_03/scene_understanding_later_area'
 if final:O=E/'artifacts/workzone_03/scene_understanding_final_61_85'
 O.mkdir(parents=True,exist_ok=True)
 paths=sorted((R/'data/workzone_03/processed/scene-CATS-15/CAM_FRONT').glob('*.jpg'),key=lambda p:int(p.stem.split('__')[-1]))
 if scoped:paths=[p for p in paths if int(p.stem.split('__')[-1])>=52000000]
 selected=[paths[round(i*(len(paths)-1)/15)] for i in range(16)]
 prompt='''Describe this work zone using the chronological front-camera images. Do not select a regulatory layout or assess compliance. User-confirmed facts: black data-recording ego vehicle (calibration identity only; not construction or surveying activity), posted speed 20 mph, work duration strictly less than three days (more precise duration unknown), first 20 seconds excluded. Return JSON with scene_facts, visible_features (each with image timestamps and uncertainty), and unresolved_layout_questions. Identify road geometry, traffic directions, lane closure versus localized obstruction, intersection relationship, apparent work vehicles and workers, signs with legible exact legends only, channelizers, flagger evidence vs ordinary workers. Do not invent lane counts or flagger traffic-control activity from high-visibility clothing alone. A missing device is unknown, not absent. Do not extrapolate across changing road segments. Distinguish separately encountered work areas if supported. This is model-derived evidence, not human-confirmed ground truth.'''
 if scoped:prompt+=' USER SCOPE: inspect ONLY the later channelized work area around 78-90 seconds. Earlier construction vehicles/workers are explicitly excluded. Included approach images from 52 seconds can establish relevant warning signs, but their association is not assumed. Describe only this scoped area. Be precise about centerline, opposing-direction lane, bicycle lane, closed or occupied part, usable travel lanes, and intersection location.'
 if final:
  prompt='''Describe only the work zone in these chronological camera0 images, original timestamps 61–85 seconds. Do not choose a regulatory layout or assess compliance. Explicit user facts: sensor car is black (NOT construction/surveying activity), speed 20 mph, duration <3 days, full opposing-direction lane closure, ego direction remains open, opposing traffic is expected to detour but actual route/control is unconfirmed. User inspection confirms no barricade, concrete/plastic road barrier, vertical panel, electronic LED arrow board, portable message board, worker, or work vehicle in this scoped scene. Final reviewed objects: 227 observations of cones/drums/delineators merged as traffic_cone; 14 ROAD WORK AHEAD observations. These are observations, not independent objects. Do not contradict these reviewed labels; describe the arrangement. Return JSON with scene_facts (observational descriptions, not speculation), visible_features with timestamp/image references, unresolved_layout_questions. Describe lanes, intersection relationship, centerline, apparent channelizer alignment and traffic routing. Do not infer alternating traffic, temporary road, or confirmed detour route from absence of observed vehicles. Distinguish inferred geometry from explicit user facts. Do not use observations outside 61–85 seconds.'''
 content=[{'type':'input_text','text':prompt}];assets=[]
 for p in selected:
  dest=O/(p.stem+'.jpg');im=Image.open(p);im.thumbnail((1600,900));im.save(dest,quality=92)
  assets.append({'source':str(p),'image':str(dest),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
  content.extend([{'type':'input_text','text':f"timestamp seconds: {int(p.stem.split('__')[-1])/1e6}"},{'type':'input_image','image_url':image_data_url(dest),'detail':'high'}])
 cfg=json.loads((E/'config/workzone_03/stage1_kg_bm25.json').read_text());key,url=credentials(cfg)
 payload={'model':cfg['model'],'reasoning':{'effort':'medium'},'input':[{'role':'user','content':content}],'max_output_tokens':5000,'text':{'format':{'type':'json_object'}}}
 (O/'request.json').write_text(json.dumps(payload));(O/'input_manifest.json').write_text(json.dumps(assets,indent=2))
 try:
  response,seconds=post_json(url+'/v1/responses',key,payload)
  (O/'raw_response.json').write_text(json.dumps(response,ensure_ascii=False,indent=2))
  result=json.loads(output_text(response));(O/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
  (O/'usage.json').write_text(json.dumps({'seconds':seconds,'usage':response.get('usage'),'model':response.get('model')},indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
 except Exception as exc:
  (O/'failure.json').write_text(json.dumps({'error':str(exc)}));raise
if __name__=='__main__':main()
