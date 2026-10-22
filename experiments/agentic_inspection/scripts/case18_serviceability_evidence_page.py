#!/usr/bin/env python3
import json,base64,io,html
from PIL import Image
from case18_qwen_serviceability import A,O,R
s=json.loads((O/'final_summary.json').read_text());scene=json.loads((A/'scene.json').read_text());obs={x['observation_id']:x for x in scene['accepted_observations']};items=[]
for x in s['observations']:
 o=obs[x['observation_id']];im=Image.open(o['source_image']).crop(o['bbox']);im.thumbnail((180,180));b=io.BytesIO();im.save(b,format='JPEG');uri=base64.b64encode(b.getvalue()).decode();items.append('<tr><td>'+html.escape(x['observation_id'])+'</td><td><img src="data:image/jpeg;base64,'+uri+'"></td><td>'+html.escape(x['initial_status'])+'</td><td>'+html.escape(x['status'])+'</td><td>'+html.escape(x['reason'])+'</td></tr>')
page='<html lang="zh"><meta charset="utf-8"><title>Qwen 设施可用性图像检查</title><style>body{font:15px/1.6 system-ui;margin:30px}td,th{border:1px solid #ddd;padding:12px;text-align:left}table{border-collapse:collapse;width:100%}img{max-width:180px;max-height:180px}</style><h1>Qwen3-VL 4B · 设施可用性图像检查</h1><p>164 个观察框，不是 164 个独立设施。仅检查图片中可见的功能性缺陷；uncertain 不算合格，也不算损坏。模型初判缺陷均单图复核，原输出留存。</p><p>'+html.escape(str(s['counts']))+'</p><table><tr><th>观察 ID</th><th>原图局部</th><th>初判</th><th>复核后模型判断</th><th>依据</th></tr>'+''.join(items)+'</table></html>'
(R/'reports/workzone_18/ta22_user_selected/post_review_20261021/serviceability.html').write_text(page)
print('Evidence page created')
