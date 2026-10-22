"""Portable case discovery and a common read API over preserved final inputs."""
from pathlib import Path
import json
ROOT = Path(__file__).resolve().parents[1]
def load_cases(root=ROOT):
    root=Path(root); cases={}
    for file in sorted((root/'workzones').glob('workzone_*/case.json')):
        case=json.loads(file.read_text())
        if case['schema']!='workzone_case_v1':raise ValueError(f'Unsupported case schema: {file}')
        number=case['number']
        if number in cases:raise ValueError(f'Duplicate case number {number}')
        case['resolved_paths']={key:root/value for key,value in case['paths'].items()}
        cases[number]=case
    if not cases:raise ValueError('No workzones registered')
    return cases

def load_detections(case, root=ROOT):
    """Normalize field names without changing accepted boxes/classes or source files."""
    root=Path(root);data=json.loads((root/case['paths']['detections']).read_text())
    accepted=data.get('accepted_observations',data.get('observations',[]))
    def normalize(obs, box_required):
        image=obs.get('image',obs.get('source_image'))
        if image and '/data/' in image:
            image='data/'+image.split('/data/',1)[1]
        return {'observation_id':obs['observation_id'],'frame':obs.get('frame'),'camera':obs.get('camera','CAM_FRONT'),'image':image,'bbox_xyxy':obs.get('bbox_xyxy',obs.get('bbox')) if box_required else None,'class':obs.get('class',obs.get('reviewed_class')),'source':obs}
    return {'schema':'workzone_detections_view_v1','case_id':case['case_id'],'accepted_observations':[normalize(o,True) for o in accepted],'semantic_only_observations':[normalize(o,False) for o in data.get('semantic_only_observations',[])]}
