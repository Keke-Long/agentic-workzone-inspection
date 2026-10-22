#!/usr/bin/env python3
"""Grounding DINO candidates, full camera timeline within user-selected context.
Predictions are never automatically promoted to accepted/human-reviewed evidence.
"""
import argparse,json,time,hashlib
from pathlib import Path
from collections import Counter
import torch
from PIL import Image,ImageDraw
from transformers import AutoProcessor,AutoModelForZeroShotObjectDetection
from torchvision.ops import nms
R=Path('/home/klong23/workzone');E=R/'experiments/agentic_inspection';D=R/'data/workzone_03';O=D/'detections';M=R/'dependencies/models/grounding-dino-tiny'
PHRASES={
 'traffic cone':'traffic_cone','orange traffic drum':'traffic_cone','orange delineator post':'traffic_cone',
 'orange diamond construction warning sign':'traffic_sign','road work ahead sign':'traffic_sign','road closed ahead sign':'traffic_sign',
 'lane closed sign':'traffic_sign','road closed barricade':'barricade','striped traffic barricade':'barricade',
 'concrete road barrier':'road_barrier','electronic LED flashing arrow board':'arrow_board',
 'portable electronic message board':'pcms','orange striped vertical panel':'vertical_panel',
 'construction worker':'worker','construction vehicle':'work_vehicle'}
SIGN_PHRASES={k:v for k,v in PHRASES.items() if v in ['traffic_sign','arrow_board','pcms','barricade']}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def label(raw):
 if raw in PHRASES:return PHRASES[raw]
 raw=raw.lower().replace('##','')
 if any(x in raw for x in ['cone','drum','delineator','ineator']):return 'traffic_cone'
 if 'arrow' in raw and 'board' in raw:return 'arrow_board'
 if 'message' in raw and 'board' in raw:return 'pcms'
 if 'barricade' in raw:return 'barricade'
 if 'barrier' in raw:return 'road_barrier'
 if 'panel' in raw:return 'vertical_panel'
 if 'worker' in raw:return 'worker'
 if 'vehicle' in raw:return 'work_vehicle'
 if any(x in raw for x in ['sign','diamond','warning']):return 'traffic_sign'
 return 'unclassified'
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--smoke',action='store_true');args=ap.parse_args()
 torch.set_num_threads(4);device='cuda:1' if torch.cuda.device_count()>1 else ('cuda:0' if torch.cuda.is_available() else 'cpu')
 proc=AutoProcessor.from_pretrained(M,local_files_only=True);model=AutoModelForZeroShotObjectDetection.from_pretrained(M,local_files_only=True).to(device).eval()
 scene=json.loads((E/'cases/workzone_03/scene.json').read_text());sd=json.loads((Path(scene['metadata_root'])/'sample_data.json').read_text());frames=sorted([x for x in sd if x['fileformat']=='jpg'],key=lambda x:x['timestamp'])
 if args.smoke:frames=[min(frames,key=lambda x:abs(x['timestamp']/1e6-t)) for t in [61.1,80,84.9]]
 out=O/'smoke' if args.smoke else O;out.mkdir(parents=True,exist_ok=True);(out/'frames').mkdir(exist_ok=True)
 config={'schema':'workzone_detection_run_v1','model':'IDEA-Research/grounding-dino-tiny','weights_sha256':sha(M/'model.safetensors'),'script_sha256':sha(Path(__file__)),'scope':'later channelized area and approach context only; 61-85 seconds','frame_count':len(frames),'input_frames_sha256':hashlib.sha256(json.dumps(frames,sort_keys=True).encode()).hexdigest(),'camera':'CAM_FRONT','phrases':PHRASES,'box_threshold':.25,'text_threshold':.25,'nms_iou_per_class':.5,'views':'full image plus two overlapping sign-focused crops covering x=[0,2304] and [1536,3840], y=[540,1836] at native 3840x2160 size','normalization':'cone, drum and delineator -> traffic_cone per user policy','policy':'all outputs unreviewed predictions; not accepted evidence or proof of absence','device':device}
 p=out/'run_manifest.json'
 if p.exists():
  old=json.loads(p.read_text())
  for k in ['model','weights_sha256','phrases','box_threshold','text_threshold','nms_iou_per_class','views']:assert old[k]==config[k], 'Detector settings changed: '+k
  config['reuse_policy']=old.get('reuse_policy','Identical per-frame cache only')
 p.write_text(json.dumps(config,indent=2));start=time.time();allrows=[]
 for index,row in enumerate(frames):
  ts=row['timestamp'];target=out/'frames'/f'{ts}.json';source=Path(scene['dataset_root'])/row['filename']
  if target.exists():
   cached=json.loads(target.read_text());assert cached['source_sha256']==sha(source);allrows.extend(cached['detections']);continue
  image=Image.open(source).convert('RGB');w,h=image.size
  views=[('full',(0,0,w,h),PHRASES),('sign_left',(0,int(h*.25),int(w*.60),int(h*.85)),SIGN_PHRASES),('sign_right',(int(w*.40),int(h*.25),w,int(h*.85)),SIGN_PHRASES)]
  found=[]
  for view,bounds,phrases in views:
   crop=image.crop(bounds);prompt='. '.join(phrases)+'.';inputs=proc(images=crop,text=prompt,return_tensors='pt').to(device)
   with torch.inference_mode():outputs=model(**inputs)
   result=proc.post_process_grounded_object_detection(outputs,inputs.input_ids,threshold=.25,text_threshold=.25,target_sizes=[(crop.height,crop.width)])[0]
   labels=result.get('text_labels',result.get('labels'))
   for box,score,raw in zip(result['boxes'].cpu().tolist(),result['scores'].cpu().tolist(),labels):
    b=[max(0,min(w,box[0]+bounds[0])),max(0,min(h,box[1]+bounds[1])),max(0,min(w,box[2]+bounds[0])),max(0,min(h,box[3]+bounds[1]))]
    if b[2]-b[0]<3 or b[3]-b[1]<3:continue
    found.append({'bbox':[round(v,2) for v in b],'confidence':round(score,6),'raw_label':str(raw),'class':label(str(raw)),'view':view})
  keep=[]
  for cl in sorted({x['class'] for x in found}):
   ids=[i for i,x in enumerate(found) if x['class']==cl];selected=nms(torch.tensor([found[i]['bbox'] for i in ids]),torch.tensor([found[i]['confidence'] for i in ids]),.5).tolist();keep.extend(ids[i] for i in selected)
  rows=[]
  for j,i in enumerate(sorted(keep,key=lambda i:(found[i]['class'],found[i]['bbox'][0],found[i]['bbox'][1]))):
   rows.append({'observation_id':f'W3_T{ts}_Q{j:03d}','timestamp_us':ts,'frame':index,'camera':'CAM_FRONT','source_image':str(source),'review_status':'unreviewed','context_role':'primary_area' if 77000000<=ts<=85000000 else 'approach_or_exit_context',**found[i]})
  target.write_text(json.dumps({'source_image':str(source),'source_sha256':sha(source),'timestamp_us':ts,'detections':rows},indent=2));allrows.extend(rows)
  if args.smoke:
   preview=image.copy();draw=ImageDraw.Draw(preview)
   for x in rows:draw.rectangle(x['bbox'],outline='lime',width=5);draw.text(x['bbox'][:2],x['class']+' '+str(x['confidence']),fill='red',stroke_width=1)
   preview.thumbnail((1920,1080));preview.save(out/f'{ts}.jpg')
  if (index+1)%10==0 or args.smoke:print(f'{index+1}/{len(frames)} frames; {len(allrows)} candidates; {time.time()-start:.1f}s',flush=True)
 summary={'schema':'unreviewed_detection_candidates_v1','workzone_id':'workzone_03','frame_count':len(frames),'candidate_count':len(allrows),'class_counts':dict(Counter(x['class'] for x in allrows)),'review_status':'unreviewed','detections':allrows}
 (out/'candidates.json').write_text(json.dumps(summary,indent=2));(out/'summary.json').write_text(json.dumps({k:v for k,v in summary.items() if k!='detections'},indent=2));print('COMPLETE',summary['class_counts'],flush=True)
if __name__=='__main__':main()
