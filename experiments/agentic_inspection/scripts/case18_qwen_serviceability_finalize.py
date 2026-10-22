#!/usr/bin/env python3
"""Recheck VLM defect flags individually, retain raw outputs, and summarize image-visible evidence."""
import json,base64,io,urllib.request,collections,html
from PIL import Image
from case18_qwen_serviceability import A,O,MODEL,PROMPT

def main():
 summary=json.loads((O/'summary.json').read_text());scene=json.loads((A/'scene.json').read_text());byid={x['observation_id']:x for x in scene['accepted_observations']};out=[]
 for row in summary['observations']:
  row=dict(row);row['initial_status']=row['status']
  if row['status']=='visible_unserviceable':
   ob=byid[row['observation_id']];im=Image.open(ob['source_image']);b=ob['bbox'];w=b[2]-b[0];h=b[3]-b[1];im=im.crop((max(0,b[0]-.4*w),max(0,b[1]-.2*h),min(im.width,b[2]+.4*w),min(im.height,b[3]+.2*h)));im.thumbnail((600,600));stream=io.BytesIO();im.save(stream,format='JPEG',quality=95)
   prompt= 'Assess the central work-zone device in this single image. Return JSON {"status":"visible_serviceable|visible_unserviceable|uncertain","reason":"concrete evidence"}. visible_unserviceable requires an actual visible functional defect (collapsed, severely broken, missing essential parts, markings obscured by dirt). Blur, small size, glare or occlusion are uncertain, NOT defects. If there is enough visible evidence and no obvious functional defect, use visible_serviceable. Do not invent damage. Do not infer nighttime performance.'
   req=urllib.request.Request('http://localhost:11434/api/chat',data=json.dumps({'model':MODEL,'messages':[{'role':'user','content':prompt,'images':[base64.b64encode(stream.getvalue()).decode()]}],'stream':False,'format':'json','options':{'temperature':0,'num_predict':350,'num_ctx':4096},'keep_alive':'10m'}).encode(),headers={'Content-Type':'application/json'})
   response=json.load(urllib.request.urlopen(req,timeout=180));verdict=json.loads(response['message']['content']);assert verdict['status'] in ['visible_serviceable','visible_unserviceable','uncertain'];row.update(status=verdict['status'],reason=verdict['reason'],recheck=True)
   (O/(row['observation_id']+'_recheck.json')).write_text(json.dumps({'prompt':prompt,'response':response,'verdict':verdict},indent=2,ensure_ascii=False));(O/(row['observation_id']+'_recheck.jpg')).write_bytes(stream.getvalue())
  out.append(row)
 summary['observations']=out;summary['counts']=dict(collections.Counter(x['status'] for x in out));summary['recheck_policy']='All initial unserviceable predictions independently re-read as single images; blur or uncertainty does not establish a functional defect.'
 (O/'final_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False))
 print(summary['counts']);print([(x['observation_id'],x['status'],x['reason']) for x in out if x['initial_status']=='visible_unserviceable'])
if __name__=='__main__':main()
