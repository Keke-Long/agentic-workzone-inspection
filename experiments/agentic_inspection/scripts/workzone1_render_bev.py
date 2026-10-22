#!/usr/bin/env python3
"""Workzone 1 viewer with the same layout as Workzone 2, without importing its conclusions."""
from pathlib import Path
import json,re
import numpy as np
import case18_render_bev as renderer
R=Path('/home/klong23/workzone');E=R/'experiments/agentic_inspection';A=E/'artifacts/workzone_01/bev_reconstruction';O=A/'scene_bev';REPORT=E/'reports/workzone_01/bev'
def main():
 REPORT.mkdir(parents=True,exist_ok=True)
 template=(E/'scripts/case18_bev.html').read_text().replace('Workzone 2','Workzone 1').replace('C18_OBJ_','W1_OBJ_').replace('href="/report"','href="/workzone1/report"')
 template=template.replace("const status={", "const status={not_reassessed:'未重新检查设施状态',")
 template=re.sub(r'<p>Qwen 状态按对象聚合：.*?</p>','<p>本页仅重建 camera0 对象位置，没有重新检查设施状态或规范符合性。旧多相机报告结论没有导入对象；未重新检查不等于合格。当前重建来源为 Case_00，与 scene-CATS-01 的 INS 位置逐帧匹配。</p>',template)
 template=template.replace('对象有清晰且可用的视图时，其他模糊视图不会使对象变为无法判断。','本次只进行位置重建；设施状态和规范符合性尚未重新评判。')
 template=template.replace("C=[360,-4];S=Math.min((W-50)/240,(H-50)/45);draw()", "let ps=D.objects.filter(o=>o.family==='channelizer').map(o=>o.local_xy_m);if(!ps.length){reset();return}let xs=ps.map(p=>p[0]),ys=ps.map(p=>p[1]);C=[(Math.min(...xs)+Math.max(...xs))/2,(Math.min(...ys)+Math.max(...ys))/2];S=Math.min((W-60)/(Math.max(...xs)-Math.min(...xs)+25),(H-60)/(Math.max(...ys)-Math.min(...ys)+25));draw()")
 template=template.replace('导流设施（cone / barricade / barrier）','导流设施（cone / drum / barricade / barrier）')
 tp=O/'viewer_template.html';tp.write_text(template)
 renderer.O=O;renderer.REPORT=REPORT;renderer.TEMPLATE=tp;renderer.PLOT_TITLE='Workzone 1: raw LiDAR reconstruction, camera0 objects and vehicle trajectory'
 objects=json.loads((O/'objects.json').read_text())['objects'];points=np.array([o['local_xy_m'] for o in objects if o['family']=='channelizer'])
 renderer.WORK_BOUNDS=(points[:,0].min()-15,points[:,0].max()+15,points[:,1].min()-15,points[:,1].max()+15) if len(points) else None
 renderer.main()
 (REPORT/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Workzone 1 当前状态</title><h1>Workzone 1 当前状态</h1><p>camera0 点云与对象位置重建已完成；本次没有重新执行规范评判。历史报告曾使用其他相机证据，不能作为当前 camera0-only 结论。</p><p>因此 BEV 对象状态统一注明未重新检查，而非合格。</p><a href="/workzone1/bev">返回 BEV</a>')
if __name__=='__main__':main()
