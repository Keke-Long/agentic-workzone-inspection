"""
Generate seq_1.pkl using raw (non-undistorted) camera images.
Images are selected at 0.1s grid from the raw camera directory.
Point clouds are deskewed npz files from undistort_pcs.py.
Intrinsics and distortion coefficients are stored as-is from calibration.

Usage:
    python meta_infos_raw.py \
        --raw_cam_dir  /home/data/workzone/workzone_data_processed/Case_01/camera0 \
        --npz_dir      /home/data/workzone/workzone_dataset/Case_01/pcds/seq_1 \
        --cam_calib    /home/data/workzone/workzone_data_processed/Case_01/calibration/calib_black_camera0.json \
        --ins_calib    /home/data/workzone/workzone_data_processed/Case_01/calibration/calib_black_ins.json \
        --gnss_csv     /home/data/workzone/workzone_data_processed/Case_01/ins/gnss.csv \
        --output_dir   /home/data/workzone/workzone_dataset/Case_01/meta_infos \
        --cam_start    1.9333 \
        --lidar_start  1.900164366
"""

import os
import json
import math
import pickle
import argparse
import numpy as np
import pandas as pd
from decimal import Decimal
from pathlib import Path
from scipy.spatial.transform import Rotation, Slerp

INTERVAL = 0.1   # seconds
SEQ_NAME = "seq_1"


# ─────────────────────────────────────────────
# Image selection (same logic as undistort_images.py)
# ─────────────────────────────────────────────
def trunc4_to_int(t: float) -> int:
    return int(math.floor(t * 10000.0 + 1e-9))

def select_raw_images(cam_dir: str, start: float, interval: float):
    """Return list of (idx, path) selected at `interval` grid starting from `start`."""
    cam_path = Path(cam_dir)
    imgs = sorted(cam_path.glob("*.png"), key=lambda p: float(p.stem))
    imgs += sorted(cam_path.glob("*.jpg"), key=lambda p: float(p.stem))

    key_to_path = {}
    for p in imgs:
        k = trunc4_to_int(float(p.stem))
        if k not in key_to_path:
            key_to_path[k] = p

    if not key_to_path:
        raise FileNotFoundError(f"No images found in {cam_dir}")

    max_k  = max(key_to_path)
    base_k = int(Decimal(str(start)) * 10000)
    step   = int(round(interval * 10000))
    targets = range(base_k, max_k + 1, step)

    selected = [(idx, key_to_path[k]) for idx, k in enumerate(targets) if k in key_to_path]
    return selected


# ─────────────────────────────────────────────
# INS pose
# ─────────────────────────────────────────────
def load_ins_pose(gnss_path):
    ins = pd.read_csv(gnss_path)
    times = ins["_header._stamp._sec"] + ins["_header._stamp._nanosec"] * 1e-9
    positions = np.stack([
        ins["_east_x_from_longitude"].to_numpy(),
        ins["_north_y_from_latitude"].to_numpy(),
        ins["_up_z_from_height"].to_numpy()
    ], axis=1)
    roll  = ins["_roll"].to_numpy()
    pitch = ins["_pitch"].to_numpy()
    yaw   = ins["_yaw_from_azimuth"].to_numpy()
    rotations = Rotation.from_euler("xyz", np.vstack([roll, pitch, yaw]).T, degrees=True)
    return times.to_numpy(), positions, rotations

def interpolate_pose(times, positions, rotations, t_query):
    t_clamped = np.clip(t_query, times[0], times[-1])
    p = np.stack([
        np.interp(t_query, times, positions[:, i]) for i in range(3)
    ], axis=0).T
    r = Slerp(times, rotations)([t_clamped])[0].as_matrix()
    return p.squeeze(), r

def make_lidar2world(pos, rot_mat, T_lidar_ins):
    R_i   = rot_mat
    p_i   = pos.reshape(3, 1)
    R_L_I = Rotation.from_quat(T_lidar_ins[3:]).as_matrix()
    p_L_I = T_lidar_ins[:3].reshape(3, 1)
    R_fix = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]], dtype=float)
    R_W_L = R_i @ R_L_I @ R_fix
    p_W_L = R_i @ p_L_I + p_i
    T = np.eye(4)
    T[:3, :3] = R_W_L
    T[:3, 3]  = p_W_L[:, 0]
    return T


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw_cam_dir", required=True, help="Raw camera image directory")
    parser.add_argument("--npz_dir",     required=True, help="Deskewed npz directory (from undistort_pcs.py)")
    parser.add_argument("--cam_calib",   required=True, help="Camera calibration JSON")
    parser.add_argument("--ins_calib",   required=True, help="INS calibration JSON")
    parser.add_argument("--gnss_csv",    required=True, help="GNSS/INS CSV file")
    parser.add_argument("--output_dir",  required=True, help="Output directory for seq_1.pkl")
    parser.add_argument("--cam_start",   type=float, required=True,
                        help="Camera image selection start time (e.g. 1.9333)")
    parser.add_argument("--lidar_start", type=float, required=True,
                        help="LiDAR t_ref start time matching undistort_pcs.py output (e.g. 1.900164366)")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # Load camera calibration
    with open(args.cam_calib) as f:
        cam_calib = json.load(f)
    cam_data = list(cam_calib.values())[0]

    fx, fy, cx, cy = cam_data["intrinsics"]
    K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)
    dist = np.array(cam_data["distortion_coeffs"], dtype=np.float64)

    T_lc = cam_data["T_lidar_camera"]
    R_lc = Rotation.from_quat(T_lc[3:]).as_matrix()
    cam2lidar = np.eye(4)
    cam2lidar[:3, :3] = R_lc
    cam2lidar[:3, 3]  = np.array(T_lc[:3])

    # Load INS calibration
    with open(args.ins_calib) as f:
        ins_calib = json.load(f)
    T_lidar_ins = np.array(ins_calib["black_ins"]["T_lidar_ins"])

    ins_times, ins_pos, ins_rots = load_ins_pose(args.gnss_csv)

    # Select camera images
    selected_imgs = select_raw_images(args.raw_cam_dir, args.cam_start, INTERVAL)
    print(f"Selected {len(selected_imgs)} images from {args.raw_cam_dir}")

    frames = []
    for img_idx, (_, img_path) in enumerate(selected_imgs):
        npz_path = Path(args.npz_dir) / f"{img_idx:03d}.npz"
        if not npz_path.exists():
            print(f"  [skip] npz not found: {npz_path}")
            continue

        # t_ref matches undistort_pcs.py: lidar_start + img_idx * 0.1
        t_ref = args.lidar_start + img_idx * INTERVAL
        try:
            pos, rot = interpolate_pose(ins_times, ins_pos, ins_rots, t_ref)
        except Exception as e:
            print(f"  [skip] interpolation failed at idx={img_idx} t={t_ref:.4f}s: {e}")
            continue

        lidar2world = make_lidar2world(pos, rot, T_lidar_ins)

        frame = {
            "cams_info": {
                "FRONT": {
                    "data_path":         str(img_path),
                    "camera_intrinsics": K.tolist(),
                    "distortion_coeffs": dist.tolist(),
                    "camera2lidar":      cam2lidar.tolist(),
                }
            },
            "path": {
                "pcd": str(npz_path),
            },
            "lidar2world": lidar2world.tolist(),
        }
        frames.append(frame)

    output = {"seq_name": SEQ_NAME, "frames": frames}

    out_pkl = Path(args.output_dir) / f"{SEQ_NAME}.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump(output, f)
    print(f"Saved {len(frames)} frames → {out_pkl}")

    out_json = Path(args.output_dir) / f"{SEQ_NAME}.json"
    with open(out_json, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Saved {len(frames)} frames → {out_json}")


if __name__ == "__main__":
    main()
