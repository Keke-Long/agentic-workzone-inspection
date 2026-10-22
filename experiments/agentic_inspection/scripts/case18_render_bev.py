#!/usr/bin/env python3
import json,base64,io
from pathlib import Path
import numpy as np
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from case18_sign_geometry import A,R
O=A/'scene_bev';REPORT=R/'reports/workzone_18/ta22_user_selected/post_review_20261021'
def main():
 result=json.loads((O/'objects.json').read_text());rows=json.loads((O/'observations.json').read_text());trajectory=json.loads((O/'trajectory.json').read_text());cloud=np.load(O/'pointcloud_display.npz')['xyz'];rec=json.loads((O/'reconstruction.json').read_text());objects=result['objects'];data={'objects':objects,'counts':result['counts'],'unresolved':result['unresolved_observations'],'trajectory':[x['local_xy_m'] for x in trajectory],'reconstruction':rec,'observations':{}}
 for x in rows:
  pic=Image.open(x['source_image']).crop(x['bbox']);pic.thumbnail((280,240));b=io.BytesIO();pic.save(b,format='JPEG',quality=82)
  data['observations'][x['observation_id']]={**x,'image':'data:image/jpeg;base64,'+base64.b64encode(b.getvalue()).decode()}
 # Preserve occupancy at .5m planar cells for interactive overview; full display cloud saved separately.
 _,ix=np.unique(np.floor(cloud[:,:2]/.5).astype(int),axis=0,return_index=True);c=cloud[ix];data['cloud']=np.round(c,2).tolist()
 colors={'channelizer':'#e89113','road_work_ahead':'#d94d45','right_lane_closed':'#a832a8','merging_sign':'#2f9c5f','arrow_board':'#217cde','traffic_sign':'#7257b5'}
 fig,ax=plt.subplots(figsize=(17,5));ax.scatter(c[:,0],c[:,1],s=.4,c='#b8c0c8',alpha=.5,rasterized=True);tr=np.array(data['trajectory']);ax.plot(tr[:,0],tr[:,1],c='#237c9c',lw=1.5,label='Vehicle trajectory')
 for fam in sorted(set(x['family'] for x in objects)):
  g=[x for x in objects if x['family']==fam];xy=np.array([x['local_xy_m'] for x in g]);ax.scatter(xy[:,0],xy[:,1],s=28,facecolors=[colors.get(fam,'black') if x['position_status']=='multi_frame_supported' else 'none' for x in g],label=fam,edgecolors=colors.get(fam,'black'),linewidth=.8)
 ax.set_xlim(float(c[:,0].min())-10,float(c[:,0].max())+10);ax.set_ylim(float(c[:,1].min())-10,float(c[:,1].max())+10)
 ax.set(xlabel='Local x / m (initial forward)',ylabel='Local y / m (left)',title=globals().get('PLOT_TITLE','Workzone 2: corrected LiDAR, trajectory and reviewed-object position candidates'));ax.set_aspect('equal');ax.grid(alpha=.2);ax.legend(loc='upper left',ncol=3,fontsize=8);fig.tight_layout();fig.savefig(REPORT/'bev_overview.png',dpi=180);bounds=globals().get('WORK_BOUNDS') or (230,500,-25,25);ax.set_xlim(bounds[0],bounds[1]);ax.set_ylim(bounds[2],bounds[3]);fig.savefig(REPORT/'bev_work_area.png',dpi=180);plt.close(fig)
 template=globals().get('TEMPLATE',R/'scripts/case18_bev.html').read_text();page=template.replace('__BEV_DATA__',json.dumps(data,separators=(',',':')).replace('</','<\\/'));(REPORT/'bev.html').write_text(page);print('BEV page',len(page),'bytes;',len(c),'map points')
if __name__=='__main__':main()
