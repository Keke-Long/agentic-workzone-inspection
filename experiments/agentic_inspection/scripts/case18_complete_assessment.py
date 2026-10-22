#!/usr/bin/env python3
"""Recheck remaining frozen requirements from corrected Case18-only geometry.
Diagnostic fits are not survey measurements; threshold-overlap stays indeterminate.
"""
import json,csv,hashlib,shutil
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scene_data_tools_v5 import SceneDataToolsV5
from case18_sign_geometry import A,R
O=A/'full_reassessment';O.mkdir(exist_ok=True)
def main():
 objects=json.loads((A/'scene_bev/objects.json').read_text())['objects'];obs={x['observation_id']:x for x in json.loads((A/'scene_bev/observations.json').read_text())};scene=json.loads((A/'scene.json').read_text());accepted={x['observation_id']:x for x in scene['accepted_observations']};t=SceneDataToolsV5(A/'scene.json');byid={x['object_id']:x for x in objects}
 # Explicit Case18 inventory: tentative candidates may veto false gap claims, never establish them.
 inventory=O/'device_inventory.csv';fields=['id','class_name','inspection_layer','eligible_for_any_position_plot','x_enu_m','y_enu_m']
 with inventory.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
  for o in objects:
   if o['family']=='channelizer':w.writerow(dict(zip(fields,[o['object_id'],'channelizing_device','active_device','True',*o['world_xyz_m'][:2]])))
 rows=[]
 for o in objects:
  if o['position_status']!='multi_frame_supported' or o['family']!='channelizer':continue
  for id in o['geometry_observation_ids']:
   if id not in accepted:continue
   x=dict(accepted[id]);x.update(xyz=obs[id]['world_xyz_m'],geometry_eligible=True,refined_element_id=o['object_id'],reviewed_class='channelizing_device');rows.append(x)
 scene['accepted_observations']=rows;scene['accepted_observation_ids']=[x['observation_id'] for x in rows];scene['data_sources']={'device_inventory':str(inventory)};scene_path=O/'geometry_scene.json';scene_path.write_text(json.dumps(scene,indent=2));tool=SceneDataToolsV5(scene_path);audit=tool.audit_channelizer_spacing({'taper':{'value':25,'unit':'ft','violation_when':'above_maximum'},'tangent':{'value':50,'unit':'ft','violation_when':'above_maximum'}},minimum_consecutive_exceedances=1);(O/'channelizer_spacing.json').write_text(json.dumps(audit,indent=2));assert not audit['deficiency_supported']
 # Clearly straight deployed run, away from transition and stored barricades.
 straight=sorted([o for o in objects if o['family']=='channelizer' and o['position_status']=='multi_frame_supported' and 319<o['station_m']<435 and o['local_xy_m'][1]>-3],key=lambda o:o['station_m'])
 # Accepted frame509 shows an actual intervening post; retain its provisional position and wider allowance.
 split=byid['C18_OBJ_014'];assert split['geometry_observation_ids']==['C18_F0509_CAM_FRONT_Q009'];assert obs['C18_F0509_CAM_FRONT_Q009']['point_count']>=30
 straight.append(split);straight.sort(key=lambda o:o['station_m']);gaps=[]
 for a,b in zip(straight,straight[1:]):
  d=float(np.linalg.norm(np.array(b['world_xyz_m'][:2])-a['world_xyz_m'][:2]));ua=.5 if a['position_status']=='multi_frame_supported' else 1.;ub=.5 if b['position_status']=='multi_frame_supported' else 1.
  gaps.append({'from':a['object_id'],'to':b['object_id'],'distance_m':d,'sensitivity_envelope_m':[max(0,d-ua-ub),d+ua+ub],'threshold_m':15.24,'supported_below_maximum':d+ua+ub<15.24,'contains_single_frame_anchor':a is split or b is split})
 assert all(x['supported_below_maximum'] for x in gaps)
 # Continuous two-segment taper fit in recorded trajectory-relative coordinates.
 line=sorted([o for o in objects if o['family']=='channelizer' and o['position_status']=='multi_frame_supported' and 260<o['station_m']<410 and o['local_xy_m'][1]>-8],key=lambda o:o['station_m']);x=np.array([o['station_m'] for o in line]);y=np.array([t._project_to_trajectory(np.array(o['world_xyz_m'][:2]))['signed_lateral_offset_m'] for o in line]);knots=np.arange(285,330,.25)
 def fit(xx,yy):
  best=None
  for k in knots:
   X=np.column_stack([np.ones(len(xx)),np.minimum(xx-k,0)]);coef=np.linalg.lstsq(X,yy,rcond=None)[0];e=float(np.mean((X@coef-yy)**2));r=(e,float(k),float(coef[0]),float(coef[1]))
   if best is None or r[0]<best[0]:best=r
  return best
 best=fit(x,y);start=float(x.min());length=best[1]-start;width=length*best[3];required=width*25**2/60
 # Sensitivity to which repeated object is present, plus explicit localization/endpoint allowances.
 leave=[fit(np.delete(x,i),np.delete(y,i)) for i in range(len(x))];klo=min(z[1] for z in leave)-1;khi=max(z[1] for z in leave)+1;Li=[klo-start-1,khi-start+1];Wi=[max(0,width-.75),width+.75];reqi=[v*25**2/60 for v in Wi];decision='supported' if Li[0]>=reqi[1] else 'noncompliant' if Li[1]<reqi[0] else 'measured_borderline'
 # The model supplies an estimated transition, not a manually certified lane-edge offset.
 assert decision=='measured_borderline'
 taper={'model':'continuous linear taper followed by constant lateral channelizer line in trajectory coordinates','objects':[o['object_id'] for o in line],'start_station_m':start,'change_station_m':best[1],'length_m':length,'lateral_offset_estimate_m':width,'required_length_m_at_25mph':required,'length_sensitivity_envelope_m':Li,'offset_sensitivity_envelope_m':Wi,'required_length_sensitivity_envelope_m':reqi,'fit_rmse_m':best[0]**.5,'status':decision,'note':'W is the estimated channelizer lateral shift relative to driven trajectory, not an independently surveyed lane width. L uses fitted transition endpoint; full lane-edge/endpoint semantics and systematic uncertainty prevent a definitive pass/fail when envelopes overlap. Sensitivity ranges are not calibrated confidence intervals.'}
 fig,axs=plt.subplots(2,1,figsize=(12,8));axs[0].scatter(x,y,label='Multi-frame channelizers');xx=np.linspace(x.min(),x.max(),400);axs[0].plot(xx,best[2]+best[3]*np.minimum(xx-best[1],0),label='Continuous taper + tangent fit');axs[0].axvline(best[1],ls='--',color='gray');axs[0].set(xlabel='Trajectory station / m',ylabel='Lateral offset / m',title=f'Taper estimate: L={length:.2f} m, W={width:.2f} m, formula Lmin={required:.2f} m');axs[0].legend();axs[1].bar(range(1,len(gaps)+1),[g['distance_m'] for g in gaps],color='#4487ae');axs[1].errorbar(range(1,len(gaps)+1),[g['distance_m'] for g in gaps],yerr=[g['sensitivity_envelope_m'][1]-g['distance_m'] for g in gaps],fmt='none',ecolor='#333');axs[1].axhline(15.24,c='red',ls='--',label='50 ft = 15.24 m');axs[1].set(xlabel='Observed tangent gap',ylabel='Distance / m');axs[1].legend();fig.tight_layout();fig.savefig(O/'measurements.png',dpi=150);plt.close(fig)
 result={'schema':'case18_remaining_requirements_reassessment_v1','osm_used':False,'tool_attempt':{'measurement_id':audit['measurement_id'],'scanned_observations':audit['accepted_channelizer_observations_scanned'],'evaluated_gaps':audit['gaps_evaluated'],'false_gap_claims_vetoed':audit['gaps_vetoed_by_possible_intervener'],'deficiency_supported':audit['deficiency_supported'],'inventory':str(inventory)},'tangent_spacing':{'status':'supported','scope_station_m':[straight[0]['station_m'],straight[-1]['station_m']],'gaps':gaps,'maximum_distance_m':max(g['distance_m'] for g in gaps),'maximum_upper_bound_m':max(g['sensitivity_envelope_m'][1] for g in gaps),'single_frame_intervener':split['object_id'],'evidence_ids':sorted({k for o in straight for k in o['observation_ids']}),'limitation':'Observed straight run only; provisional interior anchor explicit. No extrapolation to unseen facilities or transition spacing.'},'taper':taper,'termination_visual_review':{'frames':[500,520,530,540,550,560,564,570,575,580,600,620,631],'finding':'Observed posts end alongside the work-space boundary; later clear frames show the lane reopened without a channelizer sequence guiding traffic back to its original lane. No downstream taper identified in captured termination.','status':'not_applicable','scope':'captured main approach only; no claim about other approaches'},'remaining_requirements_all_attempted':True}
 (O/'assessment.json').write_text(json.dumps(result,indent=2));print(json.dumps({'tangent_max_m':result['tangent_spacing']['maximum_distance_m'],'tangent_max_upper_m':result['tangent_spacing']['maximum_upper_bound_m'],'gaps':len(gaps),'taper':taper},indent=2))
if __name__=='__main__':main()
