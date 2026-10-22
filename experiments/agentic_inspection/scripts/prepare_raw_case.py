#!/usr/bin/env python3
"""Adapt an extracted CATS case using the reference camera/deskew algorithms.

Raw inputs are read-only. The legacy 30 Hz camera phase filter is bypassed only
for inputs verified to already be 10 Hz. Frame grouping remains index-aligned;
every sensor retains its own timestamp and interpolated ego pose.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import uuid

import cv2
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

REFERENCE = Path('/home/klong23/workzone/dependencies/preprocess/nuScenes')
CAMERAS = {'camera0': 'CAM_FRONT', 'camera2': 'CAM_BACK',
           'camera5': 'CAM_FRONT_LEFT', 'camera7': 'CAM_FRONT_RIGHT',
           'camera4': 'CAM_BACK_LEFT', 'camera6': 'CAM_BACK_RIGHT'}


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, REFERENCE / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def timestamp_us(path):
    return int(Decimal(path.stem) * 1000000)


def token(scene, *parts):
    return uuid.uuid5(uuid.NAMESPACE_URL, '/'.join([scene, *map(str, parts)])).hex


def audit_raw(root):
    files, counts, times, dimensions = {}, {}, {}, {}
    for folder in [*CAMERAS, 'lidar']:
        ext = 'pcd' if folder == 'lidar' else 'png'
        rows = sorted((root / folder).glob(f'*.{ext}'), key=lambda p: Decimal(p.stem))
        if not rows:
            continue
        files[folder] = rows
        t = np.array([float(p.stem) for p in rows])
        if np.any(np.diff(t) <= 0):
            raise ValueError(f'{folder}: non-increasing timestamps')
        counts[folder] = len(rows)
        times[folder] = {'first_s': float(t[0]), 'last_s': float(t[-1]),
                         'interval_min_s': float(np.diff(t).min()),
                         'interval_max_s': float(np.diff(t).max())}
        if folder != 'lidar':
            # Check the entire input timeline, not just its median frequency.
            if not np.all(np.abs(np.diff(t) - .1) < .002):
                raise ValueError(f'{folder}: not a complete 10 Hz stream; use legacy phase selection')
            im = cv2.imread(str(rows[0]))
            if im is None:
                raise ValueError(f'unreadable image: {rows[0]}')
            dimensions[folder] = [int(im.shape[1]), int(im.shape[0])]
    if 'lidar' not in files or 'camera0' not in files:
        raise ValueError('LiDAR and front camera are required')
    if len(set(counts.values())) != 1:
        raise ValueError(f'Index alignment requires equal counts: {counts}')
    ins = pd.read_csv(root / 'ins/gnss.csv')
    t = (ins['_header._stamp._sec'] + ins['_header._stamp._nanosec'] * 1e-9).to_numpy()
    cols = ['_east_x_from_longitude', '_north_y_from_latitude', '_up_z_from_height',
            '_roll', '_pitch', '_yaw_from_azimuth']
    if not np.all(np.diff(t) > 0) or not np.isfinite(ins[cols].to_numpy()).all():
        raise ValueError('Invalid INS timeline or pose')
    for folder, rows in files.items():
        if float(rows[0].stem) < t[0] or float(rows[-1].stem) > t[-1]:
            raise ValueError(f'{folder}: timestamps outside INS support')
    report = {'schema': 'raw_case_audit_v1', 'source_root': str(root),
              'actual_counts': counts, 'timestamp_ranges': times, 'image_dimensions': dimensions,
              'missing_camera_channels': [v for k, v in CAMERAS.items() if k not in files],
              'ins': {'rows': len(t), 'first_s': float(t[0]), 'last_s': float(t[-1]),
                      'unique_strictly_increasing_timestamps': True, 'pose_values_finite': True},
              'input_manifest_sha256': digest(root / 'extraction_manifest.json'),
              'ins_sha256': digest(root / 'ins/gnss.csv'),
              'camera_selection': 'all existing frames; complete 10 Hz timeline verified',
              'pairing': 'legacy sorted-index pairing, individual sensor timestamps/poses retained',
              'raw_input_policy': 'read_only; no image rotation, recropping, ENU rebasing or timestamp rebasing'}
    return report, files, ins, t


def convert(args):
    cv2.setNumThreads(1)
    root, dst, calib = args.raw_root.resolve(), args.output_root.resolve(), args.calibration.resolve()
    if root == dst or root in dst.parents:
        raise ValueError('Output must be outside raw input')
    audit, files, ins, ins_times = audit_raw(root)
    if args.audit_only:
        dump(dst / 'raw_audit.json', audit)
        print(json.dumps(audit, indent=2))
        return
    if (dst / 'processing_manifest.json').exists():
        raise FileExistsError('Completed output already exists; refusing overwrite')
    dst.mkdir(parents=True, exist_ok=True)
    dump(dst / 'raw_audit.json', audit)
    modules = {n: load_module(n) for n in ['undistort_cameras', 'deskew_lidar', 'build_ego_pose']}
    source_files = [REFERENCE / f'{n}.py' for n in modules]
    cal_files = [calib / f'calib_black_{cam}.json' for cam in files if cam != 'lidar']
    cal_files += [calib / 'calib_black_ins.json']
    source_hashes = {str(p): digest(p) for p in source_files + cal_files}
    settings = {'raw_root': str(root), 'scene_id': args.scene_id, 'source_sha256': source_hashes,
                'raw_manifest_sha256': audit['input_manifest_sha256'],
                'ins_sha256': audit['ins_sha256'], 'adapter_sha256': digest(__file__)}
    settings_path = dst / 'processing_settings.json'
    if settings_path.exists() and json.loads(settings_path.read_text()) != settings:
        raise ValueError('Partial output belongs to different inputs/settings')
    dump(settings_path, settings)
    for p in source_files + cal_files:
        copy = dst / 'provenance' / p.name
        copy.parent.mkdir(exist_ok=True)
        shutil.copy2(p, copy)
    scene = dst / args.scene_id
    scene.mkdir(exist_ok=True)
    uc, dl, ep = [modules[n] for n in modules]
    poses = ins[['_east_x_from_longitude', '_north_y_from_latitude', '_up_z_from_height']].to_numpy()
    rotations = Rotation.from_euler('xyz', ins[['_roll', '_pitch', '_yaw_from_azimuth']].to_numpy(), degrees=True).as_quat()
    intrinsics, converted = {}, {}
    provenance = []
    # Bounded per-camera worker pool avoids retaining thousands of full-size images.
    for cam, rows in files.items():
        if cam == 'lidar':
            continue
        channel = CAMERAS[cam]
        folder = scene / channel
        folder.mkdir(exist_ok=True)
        K, D = uc.load_calib(str(calib), cam)
        width, height = audit['image_dimensions'][cam]
        map1, map2, new_k = uc.compute_undistort_maps(K, D, (height, width))
        intrinsics[channel] = {'camera_intrinsic': new_k.tolist(), 'width': width, 'height': height}

        def convert_image(p):
            target = folder / f'{args.log_id}__{channel}__{timestamp_us(p)}.jpg'
            source_sha = digest(p)
            im = cv2.imread(str(p))
            if im is None or im.shape[:2] != (height, width):
                raise ValueError(f'Unreadable or inconsistent image dimensions: {p}')
            und = uc.undistort_frame(im, map1, map2)
            ok, encoded = cv2.imencode('.jpg', und, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                raise ValueError(f'JPEG encoding failed: {p}')
            target.write_bytes(encoded.tobytes())
            return target, {'input': str(p), 'input_sha256': source_sha,
                            'output': str(target), 'output_sha256': digest(target),
                            'timestamp_us': timestamp_us(p)}

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            result = list(executor.map(convert_image, rows))
        converted[channel] = [p for p, _ in result]
        provenance.extend(row for _, row in result)
        print(f'{channel}: undistorted {len(result)} images', flush=True)
    dump(scene / 'CALIBRATION/undistorted_intrinsics.json', intrinsics)
    t_li = np.array(json.loads((calib / 'calib_black_ins.json').read_text())['black_ins']['T_lidar_ins'])
    folder = scene / 'LIDAR_TOP'
    folder.mkdir(exist_ok=True)
    converted['LIDAR_TOP'] = []
    lidar_quality = []
    for i, p in enumerate(files['lidar']):
        target = folder / f'{args.log_id}__LIDAR_TOP__{timestamp_us(p)}.pcd.bin'
        pts = dl.read_pcd(p)
        if not len(pts):
            raise ValueError(f'Empty PCD: {p}')
        finite = np.isfinite(np.column_stack([pts[n] for n in ['x', 'y', 'z', 'timestamp']])).all()
        t_min, t_max = float(pts['timestamp'].min()), float(pts['timestamp'].max())
        if not finite or t_min < ins_times[0] or t_max > ins_times[-1]:
            raise ValueError(f'Invalid points or point timestamps outside INS support: {p}')
        xyz = dl.deskew(pts, ins_times, poses, rotations, t_li, float(p.stem))
        if not np.isfinite(xyz).all():
            raise ValueError(f'Invalid deskew output: {p}')
        dl.write_bin(target, xyz, pts['intensity'], pts['ring'])
        converted['LIDAR_TOP'].append(target)
        provenance.append({'input': str(p), 'input_sha256': digest(p), 'output': str(target),
                           'output_sha256': digest(target), 'timestamp_us': timestamp_us(p)})
        lidar_quality.append({'frame': i, 'points': len(pts), 'scan_start_s': t_min, 'scan_end_s': t_max})
        if i % 50 == 0 or i == len(files['lidar']) - 1:
            print(f'LIDAR_TOP: deskewed {i+1}/{len(files["lidar"])} frames', flush=True)
    n = len(files['lidar'])
    channels = ['LIDAR_TOP', *intrinsics]
    meta = dst / 'CATS_v1.0'
    scene_token, log_token = token(args.scene_id, 'scene'), token(args.scene_id, 'log')
    sensors = [{'token': token(args.scene_id, ch, 'sensor'), 'channel': ch,
                'modality': 'lidar' if ch == 'LIDAR_TOP' else 'camera'} for ch in channels]
    calibrations = []
    for sensor in sensors:
        ch = sensor['channel']
        if ch == 'LIDAR_TOP':
            tr, rot, K = t_li[:3], Rotation.from_quat(t_li[3:]), []
        else:
            cam = next(k for k, v in CAMERAS.items() if v == ch)
            tc = np.array(json.loads((calib / f'calib_black_{cam}.json').read_text())[f'black_{cam}']['T_lidar_camera'])
            rl = Rotation.from_quat(t_li[3:])
            tr, rot, K = t_li[:3] + rl.apply(tc[:3]), rl * Rotation.from_quat(tc[3:]), intrinsics[ch]['camera_intrinsic']
        calibrations.append({'token': token(args.scene_id, ch, 'calibration'), 'sensor_token': sensor['token'],
                             'translation': tr.tolist(), 'rotation': ep.quat_to_nuscenes(rot.as_quat()), 'camera_intrinsic': K})
    samples = [{'token': token(args.scene_id, 'sample', i), 'timestamp': timestamp_us(p), 'scene_token': scene_token,
                'prev': token(args.scene_id, 'sample', i-1) if i else '',
                'next': token(args.scene_id, 'sample', i+1) if i+1 < n else ''} for i, p in enumerate(files['lidar'])]
    sd, ego = [], []
    offsets = {}
    for ch in channels:
        raw = files['lidar' if ch == 'LIDAR_TOP' else next(k for k, v in CAMERAS.items() if v == ch)]
        ts = np.array([timestamp_us(p) for p in raw], dtype=np.int64)
        pos, rot = ep.interpolate_pose(ins_times, poses, rotations, ts / 1e6)
        if ch != 'LIDAR_TOP':
            offsets[ch] = {'camera_minus_lidar_reference_ms': np.percentile(
                (ts - np.array([s['timestamp'] for s in samples])) / 1000., [0, 50, 95, 100]).tolist(),
                'camera_minus_scan_end_ms': np.percentile((ts / 1e6 - np.array([q['scan_end_s'] for q in lidar_quality])) * 1000,
                                                         [0, 50, 95, 100]).tolist(),
                'percentiles': [0, 50, 95, 100]}
        for i, p in enumerate(converted[ch]):
            tok = token(args.scene_id, ch, i)
            sd.append({'token': tok, 'sample_token': samples[i]['token'], 'ego_pose_token': tok,
                       'calibrated_sensor_token': token(args.scene_id, ch, 'calibration'),
                       'timestamp': int(ts[i]), 'fileformat': 'pcd' if ch == 'LIDAR_TOP' else 'jpg',
                       'is_key_frame': True, 'height': intrinsics.get(ch, {}).get('height', 0),
                       'width': intrinsics.get(ch, {}).get('width', 0), 'filename': str(p.relative_to(dst)),
                       'prev': token(args.scene_id, ch, i-1) if i else '',
                       'next': token(args.scene_id, ch, i+1) if i+1 < n else ''})
            ego.append({'token': tok, 'timestamp': int(ts[i]), 'translation': pos[i].tolist(),
                        'rotation': ep.quat_to_nuscenes(rot[i])})
    tables = {'sensor': sensors, 'calibrated_sensor': calibrations, 'sample': samples,
              'sample_data': sd, 'ego_pose': ego,
              'scene': [{'token': scene_token, 'log_token': log_token, 'nbr_samples': n,
                         'first_sample_token': samples[0]['token'], 'last_sample_token': samples[-1]['token'],
                         'name': args.scene_id, 'description': f'{root.name}; raw sensor preparation; perception review pending'}],
              'log': [{'token': log_token, 'logfile': args.log_id, 'vehicle': 'black',
                       'date_captured': args.date_captured, 'location': 'madison-wi-usa'}]}
    for name, rows in tables.items():
        dump(meta / f'{name}.json', rows)
    with (dst / 'file_manifest.jsonl').open('w') as f:
        for row in provenance:
            f.write(json.dumps(row) + '\n')
    dump(dst / 'synchronization_audit.json', offsets)
    dump(dst / 'lidar_quality.json', lidar_quality)
    total_points = sum(q['points'] for q in lidar_quality)
    manifest = {**settings, 'state': 'complete', 'counts': {ch: len(v) for ch, v in converted.items()},
                'point_count': total_points, 'metadata_root': str(meta),
                'calibration_authorization': args.calibration_authorization,
                'reference_algorithms': ['OpenCV getOptimalNewCameraMatrix alpha=0; INTER_LINEAR; JPEG quality=95',
                                         'deskew_lidar.deskew; reference timestamp=PCD filename',
                                         'ENU linear interpolation + quaternion SLERP',
                                         'Camera->LiDAR->INS composition; nuScenes wxyz quaternion'],
                'input_adaptations': ['Keep all pre-extracted 10 Hz camera frames; old phase filter is inapplicable',
                                      'Discover present channels; CAM_BACK absent',
                                      'Case-specific paths and deterministic tokens; original per-sensor timestamps preserved'],
                'human_review_status': 'pending; no observations promoted to human-reviewed',
                'metadata_sha256': {str(meta / f'{name}.json'): digest(meta / f'{name}.json') for name in tables}}
    dump(dst / 'processing_manifest.json', manifest)
    print(json.dumps({'state': 'complete', 'output_root': str(dst), 'counts': manifest['counts'], 'point_count': total_points}), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw-root', type=Path, required=True)
    ap.add_argument('--output-root', type=Path, required=True)
    ap.add_argument('--calibration', type=Path, required=True)
    ap.add_argument('--calibration-authorization', required=True)
    ap.add_argument('--scene-id', required=True)
    ap.add_argument('--log-id', required=True)
    ap.add_argument('--date-captured', required=True)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--audit-only', action='store_true')
    convert(ap.parse_args())
