#!/usr/bin/env python3
"""Index the user-approved Case_14 crop without modifying raw sensor files."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT = Path('/home/klong23/workzone')
RAW = Path('/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_14')
OUT = ROOT / 'data/workzone_03'
WINDOW=json.loads((ROOT/'experiments/agentic_inspection/cases/workzone_03/input_window.json').read_text())
CUTOFF, END = WINDOW['start_s'], WINDOW['end_s']

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(RAW / 'ins/gnss.csv')
    ins_t = (df['_header._stamp._sec'] + df['_header._stamp._nanosec'] * 1e-9).to_numpy()
    assert np.all(np.diff(ins_t) > 0)
    streams = {}
    for name, ext in [('camera0', 'png'), ('lidar', 'pcd')]:
        paths = sorted((RAW/name).glob('*.'+ext), key=lambda p: float(p.stem))
        keep = [p for p in paths if CUTOFF <= float(p.stem) <= END]
        assert keep and min(float(p.stem) for p in keep) >= CUTOFF
        assert all(ins_t[0] <= float(p.stem) <= ins_t[-1] for p in keep)
        streams[name] = {'original_count': len(paths), 'excluded_count': len(paths)-len(keep),
                         'selected_count': len(keep), 'selected_range_s': [float(keep[0].stem), float(keep[-1].stem)],
                         'frames': [{'path': str(p), 'timestamp_s': float(p.stem)} for p in keep]}
    lidar_t = np.array([r['timestamp_s'] for r in streams['lidar']['frames']])
    pairs = []
    for i, cam in enumerate(streams['camera0']['frames']):
        j = int(np.argmin(abs(lidar_t-cam['timestamp_s'])))
        delta = float(lidar_t[j]-cam['timestamp_s'])
        pairs.append({'frame': i, 'camera': cam['path'], 'camera_timestamp_s': cam['timestamp_s'],
                      'lidar': streams['lidar']['frames'][j]['path'], 'lidar_timestamp_s': float(lidar_t[j]),
                      'lidar_minus_camera_s': delta, 'within_100ms': abs(delta) <= .1})
    manifest = {'schema': 'raw_time_selection_v1', 'workzone_id': 'workzone_03', 'scene_id': 'scene-CATS-15',
                'raw_root': str(RAW), 'cutoff_s': CUTOFF, 'end_s': END, 'cutoff_time_basis': 'existing extracted filename and INS timestamps; no rebasing',
                'authorization': 'User explicitly selects only 61–85 seconds for images and LiDAR.',
                'raw_modified': False, 'camera_channels': ['camera0'], 'streams': streams,
                'ins': {'source': str(RAW/'ins/gnss.csv'), 'selected_rows': int(sum((ins_t>=CUTOFF)&(ins_t<=END))),
                        'support_policy': 'INS outside crop may only support boundary interpolation; not inspection evidence'},
                'lidar_point_policy': 'Downstream reconstruction must also retain only point timestamps within [61,85]; frame selection alone is insufficient.',
                'pairing_policy': 'Nearest remaining LiDAR timestamp, per-sensor capture pose; do not pair by sorted index.',
                'pairs': pairs, 'max_abs_pair_delta_s': max(abs(x['lidar_minus_camera_s']) for x in pairs),
                'pairs_outside_100ms': sum(not x['within_100ms'] for x in pairs),
                'source_manifest_sha256': hashlib.sha256((RAW/'extraction_manifest.json').read_bytes()).hexdigest(),
                'ins_sha256': hashlib.sha256((RAW/'ins/gnss.csv').read_bytes()).hexdigest(),
                'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (OUT/'selection_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps({k: {a:b for a,b in v.items() if a!='frames'} for k,v in streams.items()},indent=2))
    print('Maximum pairing delta:',manifest['max_abs_pair_delta_s'],'outside 100 ms:',manifest['pairs_outside_100ms'])
if __name__ == '__main__': main()
