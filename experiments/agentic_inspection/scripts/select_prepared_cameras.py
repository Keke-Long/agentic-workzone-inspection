#!/usr/bin/env python3
"""Create an isolated sensor subset without changing validated sensor bytes."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil

from prepare_raw_case import CAMERAS, digest, dump


def select(source, target, cameras, reason):
    source, target = source.resolve(), target.resolve()
    if target.exists():
        raise FileExistsError(f'Refusing to overwrite {target}')
    manifest = json.loads((source / 'processing_manifest.json').read_text())
    validation = json.loads((source / 'validation.json').read_text())
    if manifest['state'] != 'complete' or not validation['passed']:
        raise ValueError('Source must be complete and validated')
    selected = {CAMERAS[camera] for camera in cameras} | {'LIDAR_TOP'}
    if not selected <= set(manifest['counts']):
        raise ValueError('Requested sensor is absent from prepared source')
    metadata = Path(manifest['metadata_root'])
    for name, expected in manifest['metadata_sha256'].items():
        if digest(name) != expected:
            raise ValueError(f'Source metadata changed: {name}')
    tables = {p.stem: json.loads(p.read_text()) for p in metadata.glob('*.json')}
    tables['sensor'] = [r for r in tables['sensor'] if r['channel'] in selected]
    sensor_ids = {r['token'] for r in tables['sensor']}
    tables['calibrated_sensor'] = [r for r in tables['calibrated_sensor'] if r['sensor_token'] in sensor_ids]
    calibration_ids = {r['token'] for r in tables['calibrated_sensor']}
    tables['sample_data'] = [r for r in tables['sample_data'] if r['calibrated_sensor_token'] in calibration_ids]
    pose_ids = {r['ego_pose_token'] for r in tables['sample_data']}
    tables['ego_pose'] = [r for r in tables['ego_pose'] if r['token'] in pose_ids]
    # Samples retain their LiDAR reference timestamp and temporal links.
    filenames = {r['filename'] for r in tables['sample_data']}
    rows = [json.loads(line) for line in (source / 'file_manifest.jsonl').read_text().splitlines()]
    rows = [r for r in rows if str(Path(r['output']).relative_to(source)) in filenames]
    if len(rows) != len(filenames):
        raise ValueError('Selected metadata and file manifest disagree')
    target.mkdir(parents=True)
    for index, row in enumerate(rows):
        old = Path(row['output'])
        new = target / old.relative_to(source)
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old, new)
        if digest(new) != row['output_sha256']:
            raise ValueError(f'Selected sensor bytes changed: {old}')
        row['output'] = str(new)
        if index % 500 == 0:
            print(f'Copied and verified {index}/{len(rows)} sensor files', flush=True)
    (target / 'file_manifest.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    for name, table in tables.items():
        dump(target / 'CATS_v1.0' / f'{name}.json', table)
    scene = manifest['scene_id']
    intrinsics = json.loads((source / scene / 'CALIBRATION/undistorted_intrinsics.json').read_text())
    dump(target / scene / 'CALIBRATION/undistorted_intrinsics.json',
         {k: v for k, v in intrinsics.items() if k in selected})
    sync = json.loads((source / 'synchronization_audit.json').read_text())
    dump(target / 'synchronization_audit.json', {k: v for k, v in sync.items() if k in selected})
    shutil.copy2(source / 'lidar_quality.json', target / 'lidar_quality.json')
    calibration_names = {f'calib_black_{camera}.json' for camera in cameras} | {'calib_black_ins.json'}
    manifest['source_sha256'] = {
        p: sha for p, sha in manifest['source_sha256'].items()
        if not Path(p).name.startswith('calib_black_') or Path(p).name in calibration_names
    }
    (target / 'provenance').mkdir()
    for name in manifest['source_sha256']:
        shutil.copy2(source / 'provenance' / Path(name).name, target / 'provenance' / Path(name).name)
    shutil.copy2(__file__, target / 'provenance' / Path(__file__).name)
    selection = {
        'camera_channels': sorted(selected - {'LIDAR_TOP'}), 'raw_cameras': cameras,
        'excluded_camera_channels': sorted(set(manifest['counts']) - selected),
        'reason': reason, 'source_prepared_root': str(source),
        'source_processing_manifest_sha256': digest(source / 'processing_manifest.json'),
        'source_validation_sha256': digest(source / 'validation.json'),
        'selector_sha256': digest(__file__), 'sensor_bytes_preserved': True,
    }
    counts = Counter(Path(r['output']).parent.name for r in rows)
    manifest.update(counts=dict(counts), metadata_root=str(target / 'CATS_v1.0'),
                    camera_selection=selection)
    manifest['input_adaptations'].append('User-selected camera subset; all retained sensor bytes and per-sensor poses unchanged')
    manifest['metadata_sha256'] = {str(p): digest(p) for p in (target / 'CATS_v1.0').glob('*.json')}
    dump(target / 'camera_selection.json', selection)
    dump(target / 'processing_manifest.json', manifest)
    print(json.dumps({'output_root': str(target), 'counts': dict(counts)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--cameras', required=True, nargs='+', choices=list(CAMERAS))
    parser.add_argument('--reason', required=True)
    args = parser.parse_args()
    select(args.source_root, args.output_root, args.cameras, args.reason)
