"""Publish reviewed Workzone 3 geometry with the same BEV layout as other cases."""
from pathlib import Path
import json,re
import numpy as np
import case18_render_bev as renderer
R=Path('/home/klong23/workzone');E=R/'experiments/agentic_inspection';O=E/'artifacts/workzone_03/bev_reconstruction/scene_bev';REPORT=E/'reports/workzone_03'
def main():
 template=(E/'scripts/case18_bev.html').read_text().replace('Workzone 2','Workzone 3').replace('C18_OBJ_','W3_OBJ_').replace('href="/report"','href="/workzone3/report"')
 template=template.replace("const status={","const status={not_reassessed:'设施状态尚未评判',")
 template=re.sub(r'<p>Qwen 状态按对象聚合：.*?</p>','<p>本次仅生成对象位置 BEV，没有运行设施清洁、损坏状态或规范符合性评判。图像和点云均限原始时间戳 61–85 秒。仅使用人工保留的代表框与修正坐标，没有将同组其他未审核帧自动接纳。</p>',template)
 template=template.replace('对象有清晰且可用的视图时，其他模糊视图不会使对象变为无法判断。','点击对象查看人工确认框及跨帧几何证据。本次不生成规范符合性结论。')
 template=template.replace('导流设施（cone / barricade / barrier）','Cone（含 drum / delineator）').replace('全场景原始 LiDAR','61–85 秒内的原始 LiDAR')
 template=template.replace("C=[360,-4];S=Math.min((W-50)/240,(H-50)/45);draw()", "let ps=D.objects.map(o=>o.local_xy_m);if(!ps.length){reset();return}let xs=ps.map(p=>p[0]),ys=ps.map(p=>p[1]);C=[(Math.min(...xs)+Math.max(...xs))/2,(Math.min(...ys)+Math.max(...ys))/2];S=Math.min((W-60)/(Math.max(...xs)-Math.min(...xs)+20),(H-60)/(Math.max(...ys)-Math.min(...ys)+20));draw()")
 template=template.replace(' · ${D.counts.uncertain_views_resolved_by_same_object} 个模糊观察由同对象清晰视图补足','')
 template=template.replace('<br>清晰可用观察：${o.clear_serviceable_observation_ids.length}<br>模糊观察由清晰视图补足：${o.uncertain_views_resolved_by_same_object.length}','')
 tp=O/'viewer_template.html';tp.write_text(template)
 objects=json.loads((O/'objects.json').read_text())['objects'];points=np.array([o['local_xy_m'] for o in objects]);renderer.O=O;renderer.REPORT=REPORT;renderer.TEMPLATE=tp;renderer.PLOT_TITLE='Workzone 3: 61-85 s raw LiDAR, reviewed objects and INS trajectory'
 renderer.WORK_BOUNDS=(points[:,0].min()-10,points[:,0].max()+10,points[:,1].min()-10,points[:,1].max()+10) if len(points) else None
 renderer.main()
if __name__=='__main__':main()
