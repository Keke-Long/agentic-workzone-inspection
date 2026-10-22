"""Validate common case layout, stage provenance, final inputs and report counts."""
from project_layout import ROOT, load_cases, load_detections
from collections import Counter
import json

def validate(root=ROOT):
    for number,case in load_cases(root).items():
        for key,path in case['resolved_paths'].items():assert path.exists(), (case['case_id'],key,str(path))
        detections=load_detections(case,root)
        ids=[]
        for obs in detections['accepted_observations']:
            ids.append(obs['observation_id']);assert (root/obs['image']).is_file(),obs['image']
            x1,y1,x2,y2=obs['bbox_xyxy'];assert x1<x2 and y1<y2
        assert len(ids)==len(set(ids))
        for stage in range(7):
            row=json.loads((case['resolved_paths']['stages']/f'stage_{stage}.json').read_text())
            assert row['stage']==stage
            for field in ['config','request','model_response','tool_trace','result']:
                if row[field] is not None:assert (root/row[field]).is_file(),row[field]
                else:assert row['record_status']=='partial_record'
        report=json.loads(case['resolved_paths']['report'].read_text())
        assert dict(Counter(r['status'] for r in report['requirements']))==report['counts']
        assert 'const D=' in case['resolved_paths']['viewer'].read_text()
        print(case['case_id'],len(ids),'accepted boxes;',report['counts'],'; stages 0–6 linked')
if __name__=='__main__':validate()
