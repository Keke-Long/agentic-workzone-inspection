"""Logged source-grounded Stage 0 review after a detected retrieval omission."""
import json
from pathlib import Path
from api_client import credentials, post_json, output_text
from run_srag_bm25_v5 import stage0_schema, validate_stage0_selection

E=Path(__file__).resolve().parents[1]
A=E/'artifacts/workzone_03/agentic_final_review81'
out=A/'stage0_source_review';out.mkdir(exist_ok=True)
cfg=json.loads((E/'config/workzone_03/stage1_kg_bm25.json').read_text())
scene=json.loads((E/'cases/workzone_03/scene.json').read_text())
units=json.loads((E/cfg['manual_structure_index']).read_text())['source_units']
# All detour and intersection alternatives, selected by title rather than a supplied answer.
candidates=[u for u in units if u.get('unit_type')=='typical_application' and
            any(w in u['title'].lower() for w in ['detour','intersection','minor street','diversion'])]
sources=[{k:u[k] for k in ['source_unit_code','title','raw_text','source_pages']} for u in candidates]
prior=json.loads((A/'stage0_notes_catalogue_ta24_attempt/stage_0_layout_selection.json').read_text())
review={'review_trigger':'Controller audit found the prior selection asserting far-side intersection geometry despite this being explicitly unresolved; earlier searches did not examine all directional-detour alternatives. This is an intervention, not an untouched baseline run.',
        'task':'Re-evaluate primary layout from source evidence. Do not infer near/far side from opposing lane. Distinguish a whole-road closure, a directional detour, and intersection-specific local treatment. Do not require every illustrated device to be present to select a layout: device adequacy is assessed later. Review every supplied alternative. Unknown augmentation facts remain unknown; never invent them. Return the source-grounded corrected selection or indeterminate if genuinely blocked.',
        'scene_id':scene['scene_id'],'scene_facts':scene['scene_facts'],'prior_selection':prior,'source_units':sources}
(out/'tool_trace.json').write_text(json.dumps([{'tool':'read_frozen_manual_source_units','arguments':{'title_contains_any':['detour','intersection','minor street','diversion']},'result':sources}],indent=2)+'\n')
payload={'model':cfg['model'],'reasoning':{'effort':'high'},'input':json.dumps(review),
         'max_output_tokens':6000,'text':{'format':{'type':'json_schema','name':'stage0_layout_selection','strict':True,'schema':stage0_schema()}}}
(out/'request.json').write_text(json.dumps(payload,indent=2)+'\n')
key,base=credentials(cfg);response,elapsed=post_json(base+'/v1/responses',key,payload)
(out/'raw_response.json').write_text(json.dumps(response,indent=2)+'\n')
record=json.loads(output_text(response));validate_stage0_selection(record,{u['source_unit_code'] for u in units})
record['selection_provenance']={'origin':'model_selected','controller_source_review':True,'review_request':str(out/'request.json'),'reason':'Unsupported intersection-side assumption and omitted directional-detour alternative in prior autonomous attempts.'}
(out/'stage_0_layout_selection.json').write_text(json.dumps(record,indent=2)+'\n')
(out/'usage.json').write_text(json.dumps({'elapsed_seconds':elapsed,'usage':response.get('usage')},indent=2)+'\n')
print(json.dumps(record,ensure_ascii=False,indent=2))
