#!/usr/bin/env python3
"""Validate sensor conversion, case isolation and parity with reference math."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

from prepare_raw_case import CAMERAS, digest, dump, load_module


def validate(root: Path) -> dict:
    manifest = json.loads((root / 'processing_manifest.json').read_text())
    assert manifest['state'] == 'complete'
    for path, sha in manifest['source_sha256'].items():
        assert digest(path) == sha, path
    assert digest(manifest['raw_root'] + '/extraction_manifest.json') == manifest['raw_manifest_sha256']
    assert digest(manifest['raw_root'] + '/ins/gnss.csv') == manifest['ins_sha256']
    rows = [json.loads(line) for line in (root / 'file_manifest.jsonl').read_text().splitlines()]
    assert len({r['input'] for r in rows}) == len(rows)
    assert len({r['output'] for r in rows}) == len(rows)
    for i, r in enumerate(rows):
        assert digest(r['input']) == r['input_sha256'], r['input']
        assert digest(r['output']) == r['output_sha256'], r['output']
        assert Path(r['output']).is_relative_to(root)
        if i % 1000 == 0:
            print(f'Hash validation {i}/{len(rows)}', flush=True)
    meta = Path(manifest['metadata_root'])
    for path, sha in manifest['metadata_sha256'].items():
        assert digest(path) == sha, path
    tables = {name: json.loads((meta / f'{name}.json').read_text()) for name in
              ['scene', 'log', 'sensor', 'sample', 'sample_data', 'calibrated_sensor', 'ego_pose']}
    indexes = {name: {r['token']: r for r in data} for name, data in tables.items()}
    assert all(len(indexes[name]) == len(data) for name, data in tables.items())
    assert len(tables['scene']) == 1
    assert tables['scene'][0]['name'] == manifest['scene_id']
    assert tables['scene'][0]['nbr_samples'] == len(tables['sample'])
    assert {r['channel'] for r in tables['sensor']} == set(manifest['counts'])
    assert len(tables['sample_data']) == len(rows)
    assert {r['filename'] for r in tables['sample_data']} == {str(Path(r['output']).relative_to(root)) for r in rows}
    for sample in tables['sample']:
        assert sample['scene_token'] in indexes['scene']
        for link in ['prev', 'next']:
            assert not sample[link] or sample[link] in indexes['sample']
    for r in tables['sample_data']:
        assert r['sample_token'] in indexes['sample']
        assert r['calibrated_sensor_token'] in indexes['calibrated_sensor']
        assert r['ego_pose_token'] in indexes['ego_pose']
        pose = indexes['ego_pose'][r['ego_pose_token']]
        assert pose['timestamp'] == r['timestamp']
        assert np.isfinite(pose['translation']).all()
        assert abs(np.linalg.norm(pose['rotation']) - 1) < 1e-10
        for link in ['prev', 'next']:
            if r[link]:
                other = indexes['sample_data'][r[link]]
                assert other['calibrated_sensor_token'] == r['calibrated_sensor_token']
                assert other['next' if link == 'prev' else 'prev'] == r['token']
        p = root / r['filename']
        if r['fileformat'] == 'jpg':
            im = cv2.imread(str(p))
            assert im is not None and im.shape[:2] == (r['height'], r['width'])
        else:
            data = np.fromfile(p, dtype=np.float32)
            assert data.size % 5 == 0 and np.isfinite(data).all()
    uc, dl, ep = [load_module(n) for n in ['undistort_cameras', 'deskew_lidar', 'build_ego_pose']]
    raw = Path(manifest['raw_root'])
    ins = pd.read_csv(raw / 'ins/gnss.csv')
    ts = (ins['_header._stamp._sec'] + ins['_header._stamp._nanosec'] * 1e-9).to_numpy()
    pos = ins[['_east_x_from_longitude', '_north_y_from_latitude', '_up_z_from_height']].to_numpy()
    rot = Rotation.from_euler('xyz', ins[['_roll', '_pitch', '_yaw_from_azimuth']].to_numpy(), degrees=True).as_quat()
    caldir = root / 'provenance'
    t_li = np.array(json.loads((caldir / 'calib_black_ins.json').read_text())['black_ins']['T_lidar_ins'])
    lidar = [r for r in rows if r['input'].endswith('.pcd')]
    for r in [lidar[i] for i in [0, len(lidar)//2, len(lidar)-1]]:
        pts = dl.read_pcd(r['input'])
        xyz = dl.deskew(pts, ts, pos, rot, t_li, float(Path(r['input']).stem)).astype(np.float32)
        actual = np.fromfile(r['output'], dtype=np.float32).reshape(-1, 5)
        assert np.array_equal(xyz, actual[:, :3])
        assert np.array_equal(pts['intensity'], actual[:, 3])
        assert np.array_equal(pts['ring'].astype(np.float32), actual[:, 4])
    for cam in CAMERAS:
        candidates = [r for r in rows if Path(r['input']).parent.name == cam]
        if not candidates:
            continue
        r = candidates[len(candidates)//2]
        im = cv2.imread(r['input'])
        K, D = uc.load_calib(str(caldir), cam)
        m1, m2, _ = uc.compute_undistort_maps(K, D, im.shape[:2])
        ok, encoded = cv2.imencode('.jpg', uc.undistort_frame(im, m1, m2), [cv2.IMWRITE_JPEG_QUALITY, 95])
        assert ok and encoded.tobytes() == Path(r['output']).read_bytes()
    query = np.array([p['timestamp'] for p in tables['ego_pose']]) / 1e6
    expected_pos, expected_rot = ep.interpolate_pose(ts, pos, rot, query)
    assert np.array_equal(expected_pos, np.array([p['translation'] for p in tables['ego_pose']]))
    assert np.allclose(expected_rot[:, [3, 0, 1, 2]], [p['rotation'] for p in tables['ego_pose']], atol=1e-15, rtol=0)
    return {'passed': True, 'scene_id': manifest['scene_id'], 'files_hash_checked': len(rows),
            'raw_files_unmodified': True, 'counts': manifest['counts'], 'point_count': manifest['point_count'],
            'metadata_references_and_dimensions_valid': True, 'all_sensor_outputs_finite': True,
            'reference_parity': {'undistorted_jpeg_bytes': 'exact, one middle frame per camera',
                                 'deskew_float32_points': 'exact, first/middle/last LiDAR frames',
                                 'ego_pose': 'all per-sensor timestamps, linear ENU + SLERP'},
            'limitations': ['Calibration inherited from black vehicle by user confirmation, not a new calibration accuracy audit.',
                            'Human bbox review and independent applicability reference remain pending.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output-root', required=True, type=Path)
    args = p.parse_args()
    result = validate(args.output_root.resolve())
    dump(args.output_root / 'validation.json', result)
    print(json.dumps(result, indent=2))
