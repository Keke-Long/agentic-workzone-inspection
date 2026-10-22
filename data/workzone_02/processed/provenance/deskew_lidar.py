"""
deskew_lidar.py  —  RS-LiDAR-128 deskew → nuScenes .pcd.bin

Algorithm (same as waymo/undistort_pcs.py):
  For each point p captured at time t_i:
    1. Interpolate ego pose (ENU + RPY) at t_i  →  T_world_LiDAR(t_i)
    2. Transform p  LiDAR(t_i) → world
    3. Transform world → LiDAR(t_ref)   (t_ref = frame file timestamp)

Output format (nuScenes .pcd.bin):
  float32 binary, N×5: [x, y, z, intensity, ring]

Run:
  python3 deskew_lidar.py \
    --src  /home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_05/lidar \
    --dst  /home/data/workzone/work_zone_dataset/work_zone_data_nuScenes/scene-CATS-01/LIDAR_TOP \
    --ins  /home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_05/ins/gnss.csv \
    --calib /home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_05/calibration/calib_black_ins.json \
    --t_start 10.0
"""

import os
import glob
import json
import argparse
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation, Slerp


# ── I/O ──────────────────────────────────────────────────────────────────────

PCD_DTYPE = np.dtype([
    ("x",          np.float32),
    ("y",          np.float32),
    ("z",          np.float32),
    ("intensity",  np.float32),
    ("ring",       np.uint16),
    ("timestamp",  np.float64),
])


def read_pcd(path):
    with open(path, "rb") as f:
        for line in f:
            if line.strip() == b"DATA binary":
                break
        return np.frombuffer(f.read(), dtype=PCD_DTYPE).copy()


def write_bin(path, xyz, intensity, ring):
    """nuScenes .pcd.bin: float32 N×5 [x, y, z, intensity, ring]"""
    out = np.column_stack([
        xyz.astype(np.float32),
        intensity.astype(np.float32),
        ring.astype(np.float32),
    ])
    out.tofile(path)


# ── Pose interpolation ────────────────────────────────────────────────────────

def interpolate_pose(times, positions, rotations, t_query):
    px = np.interp(t_query, times, positions[:, 0])
    py = np.interp(t_query, times, positions[:, 1])
    pz = np.interp(t_query, times, positions[:, 2])
    p_interp = np.stack([px, py, pz], axis=1)

    t_clamped = np.clip(t_query, times[0], times[-1])
    slerp = Slerp(times, Rotation.from_quat(rotations))
    r_interp = slerp(t_clamped).as_quat()
    return p_interp, r_interp


# ── Deskew ────────────────────────────────────────────────────────────────────

def deskew(pts, ins_times, ins_positions, ins_rotations, T_lidar_ins, t_ref):
    """
    pts: structured array with fields x,y,z,timestamp
    T_lidar_ins: [tx,ty,tz, qx,qy,qz,qw]  — LiDAR origin/orientation in INS frame
    t_ref: reference timestamp (frame file timestamp)
    Returns: deskewed xyz (N,3)
    """
    p_L_I = T_lidar_ins[:3]
    R_L_I = Rotation.from_quat(T_lidar_ins[3:]).as_matrix()

    point_times = pts["timestamp"].astype(np.float64)
    P_L = np.stack([pts["x"], pts["y"], pts["z"]], axis=1).astype(np.float64)

    # World pose of LiDAR at each point's capture time
    p_i, r_i = interpolate_pose(ins_times, ins_positions, ins_rotations, point_times)
    R_i      = Rotation.from_quat(r_i).as_matrix()          # (N,3,3)
    R_WL_i   = np.einsum("mij,jk->mik", R_i, R_L_I)        # R_world_LiDAR(t_i)
    p_WL_i   = p_i + np.einsum("mij,j->mi", R_i, p_L_I)    # p_world_LiDAR(t_i)

    # World pose of LiDAR at reference time
    p_ref, r_ref = interpolate_pose(ins_times, ins_positions, ins_rotations,
                                    np.array([t_ref]))
    p_ref = p_ref[0]
    R_WL_ref  = Rotation.from_quat(r_ref[0]).as_matrix() @ R_L_I
    p_WL_ref  = p_ref + Rotation.from_quat(r_ref[0]).as_matrix() @ p_L_I
    R_LW_ref  = R_WL_ref.T

    # p_LiDAR(t_i) → world → p_LiDAR(t_ref)
    p_world = np.einsum("mij,mj->mi", R_WL_i, P_L) + p_WL_i
    P_ref   = np.einsum("ij,mj->mi", R_LW_ref, p_world - p_WL_ref)
    return P_ref


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src",     required=True)
    parser.add_argument("--dst",     required=True)
    parser.add_argument("--ins",     required=True, help="gnss.csv path")
    parser.add_argument("--calib",   required=True, help="calib_black_ins.json path")
    parser.add_argument("--t_start",    type=float, default=0.0,
                        help="Only process frames with timestamp >= this value (default 0)")
    parser.add_argument("--log_id",     default="cats001-2026-04-28-15-30-0500",
                        help="Log ID for output filename")
    parser.add_argument("--sensor",     default="LIDAR_TOP",
                        help="Sensor name for output filename")
    args = parser.parse_args()

    os.makedirs(args.dst, exist_ok=True)

    # Load extrinsic
    with open(args.calib) as f:
        T_lidar_ins = np.array(json.load(f)["black_ins"]["T_lidar_ins"])

    # Load INS
    ins = pd.read_csv(args.ins)
    ins_times     = ins["_header._stamp._sec"].to_numpy() + \
                    ins["_header._stamp._nanosec"].to_numpy() * 1e-9
    ins_positions = np.stack([
        ins["_east_x_from_longitude"].to_numpy(),
        ins["_north_y_from_latitude"].to_numpy(),
        ins["_up_z_from_height"].to_numpy(),
    ], axis=1)
    ins_rotations = Rotation.from_euler(
        "xyz",
        np.vstack([ins["_roll"].to_numpy(),
                   ins["_pitch"].to_numpy(),
                   ins["_yaw_from_azimuth"].to_numpy()]).T,
        degrees=True
    ).as_quat()

    # Collect and sort PCD files
    pcd_files = sorted(
        glob.glob(os.path.join(args.src, "*.pcd")),
        key=lambda p: float(os.path.splitext(os.path.basename(p))[0])
    )
    pcd_files = [p for p in pcd_files
                 if float(os.path.splitext(os.path.basename(p))[0]) >= args.t_start]

    print(f"Processing {len(pcd_files)} frames (t >= {args.t_start})")

    for pcd_path in pcd_files:
        t_ref = float(os.path.splitext(os.path.basename(pcd_path))[0])
        pts   = read_pcd(pcd_path)

        xyz = deskew(pts, ins_times, ins_positions, ins_rotations, T_lidar_ins, t_ref)

        ts_us    = int(t_ref * 1e6)
        filename = f"{args.log_id}__{args.sensor}__{ts_us}.pcd.bin"
        out_path = os.path.join(args.dst, filename)
        write_bin(out_path, xyz, pts["intensity"], pts["ring"])
        print(f"  {os.path.basename(pcd_path)} → {filename}  ({len(xyz):,} pts)")

    print(f"\nDone. {len(pcd_files)} frames saved to {args.dst}")


if __name__ == "__main__":
    main()
