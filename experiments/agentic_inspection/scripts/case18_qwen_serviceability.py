#!/usr/bin/env python3
"""Local low-cost VLM inspection of visible channelizer serviceability; auditable model evidence."""
import base64,io,json,time,urllib.request,hashlib
from pathlib import Path
from PIL import Image,ImageDraw
R=Path(__file__).resolve().parents[1];A=R/'artifacts/workzone_18/ta22_user_selected/post_review_20261021';O=A/'qwen_serviceability';O.mkdir(exist_ok=True)
MODEL='qwen3-vl:4b-instruct'
PROMPT='''Inspect the numbered work-zone channelizing-device crops independently. Human-reviewed boxes identify the target; do not reclassify it. Assess ONLY image-visible serviceability: severe breakage, collapse, missing major parts, damaged/missing stripes or heavy dirt that defeats visibility. Ordinary scuffs, mild leaning, perspective distortion and temporary partial occlusion do not by themselves establish loss of serviceability. Do not infer night reflectivity, hidden surfaces, past replacement actions, or compliance beyond the image. Use status visible_serviceable if sufficiently visible and no obvious functional defect; visible_unserviceable only if a specific visible defect clearly prevents function; uncertain if too small, blurred, occluded or glared to judge. Do not guess details from low resolution. Return JSON {"items":[{"id":1,"status":"visible_serviceable|visible_unserviceable|uncertain","reason":"short concrete visual evidence"},...]}, exactly one entry per numbered crop. Never treat the presence of a device alone as proof of serviceability.'''
def main():
 scene=json.loads((A/'scene.json').read_text());rows=sorted([x for x in scene['accepted_observations'] if x['reviewed_class'] in ['traffic_cone','barricade','road_barrier']],key=lambda x:(x['frame'],x['observation_id']))
 tags=json.load(urllib.request.urlopen('http://localhost:11434/api/tags'));meta=next(x for x in tags['models'] if x['name']==MODEL);(O/'model.json').write_text(json.dumps(meta,indent=2));(O/'prompt.txt').write_text(PROMPT)
 for start in range(0,len(rows),6):
  group=rows[start:start+6];path=O/f'batch_{start//6:03d}.json'
  if path.exists():continue
  canvas=Image.new('RGB',(1050,700),'#eeeeee');draw=ImageDraw.Draw(canvas)
  for j,x in enumerate(group):
   im=Image.open(x['source_image']);b=x['bbox'];w=b[2]-b[0];h=b[3]-b[1];im=im.crop((max(0,b[0]-.25*w),max(0,b[1]-.1*h),min(im.width,b[2]+.25*w),min(im.height,b[3]+.12*h)))
   scale=min(325/im.width,300/im.height,3);im=im.resize((max(1,round(im.width*scale)),max(1,round(im.height*scale))))
   xx=j%3*350;yy=j//3*350;canvas.paste(im,(xx+(350-im.width)//2,yy+40));draw.text((xx+10,yy+10),f'{j+1}: Frame {x["frame"]}',fill='black')
  b=io.BytesIO();canvas.save(b,format='JPEG',quality=95);(O/f'batch_{start//6:03d}.jpg').write_bytes(b.getvalue())
  payload={'model':MODEL,'messages':[{'role':'user','content':PROMPT+f' This image contains {len(group)} numbered crops.','images':[base64.b64encode(b.getvalue()).decode()]}],'stream':False,'format':'json','options':{'temperature':0,'num_predict':1000,'num_ctx':6144},'keep_alive':'10m'}
  for attempt in range(3):
   req=urllib.request.Request('http://localhost:11434/api/chat',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
   response=json.load(urllib.request.urlopen(req,timeout=240));content=json.loads(response['message']['content']);items=content['items'];byid={int(x['id']):x for x in items}
   if set(byid)==set(range(1,len(group)+1)) and all(x['status'] in ['visible_serviceable','visible_unserviceable','uncertain'] for x in items):break
  else:raise RuntimeError('Invalid model response')
  data={'model':MODEL,'model_digest':meta['digest'],'image_sha256':hashlib.sha256(b.getvalue()).hexdigest(),'response':response,'observations':[{'observation_id':x['observation_id'],'frame':x['frame'],'native_bbox':x['bbox'],**byid[j+1]} for j,x in enumerate(group)],'human_confirmed_condition':False}
  path.write_text(json.dumps(data,ensure_ascii=False,indent=2));print(f'{start+len(group)}/{len(rows)}',flush=True)
 results=[x for p in sorted(O.glob('batch_*.json')) for x in json.loads(p.read_text())['observations']]
 from collections import Counter
 (O/'summary.json').write_text(json.dumps({'model':MODEL,'model_digest':meta['digest'],'observations':results,'counts':dict(Counter(x['status'] for x in results)),'scope':'image-visible serviceability only, model evidence, not proof of unseen/night condition or historical replacement'},ensure_ascii=False,indent=2));print(Counter(x['status'] for x in results))
if __name__=='__main__':main()
