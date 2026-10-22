"""
build_ego_pose.py — generate ego_pose.json for CATS dataset.

One ego_pose entry per sample_data entry (ego_pose_token == sample_data_token).
Poses are interpolated from gnss.csv at each sample_data timestamp.

Run:
  python3 build_ego_pose.py \
    --meta /home/data/workzone/work_zone_dataset/work_zone_data_nuScenes/CATS_v1.0 \
    --ins  /home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_05/ins/gnss.csv
"""

import os
import json
import argparse
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation, Slerp


def interpolate_pose(ins_times, positions, rotations_quat, t_query):
    """Interpolate ENU position and quaternion at query times (seconds)."""
    px = np.interp(t_query, ins_times, positions[:, 0])
    py = np.interp(t_query, ins_times, positions[:, 1])
    pz = np.interp(t_query, ins_times, positions[:, 2])

    t_clamped = np.clip(t_query, ins_times[0], ins_times[-1])
    slerp = Slerp(ins_times, Rotation.from_quat(rotations_quat))
    rot = slerp(t_clamped).as_quat()  # [x,y,z,w]
    return np.stack([px, py, pz], axis=1), rot


def quat_to_nuscenes(q_xyzw):
    """scipy [x,y,z,w] → nuScenes [w,x,y,z]"""
    return [float(q_xyzw[3]), float(q_xyzw[0]), float(q_xyzw[1]), float(q_xyzw[2])]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--meta", required=True, help="CATS_v1.0 folder")
    parser.add_argument("--ins",  required=True, help="gnss.csv path")
    args = parser.parse_args()

    # ── Load INS ──────────────────────────────────────────────────────────────
    ins = pd.read_csv(args.ins)
    ins_times = (ins["_header._stamp._sec"].to_numpy() +
                 ins["_header._stamp._nanosec"].to_numpy() * 1e-9)

    positions = np.stack([
        ins["_east_x_from_longitude"].to_numpy(),
        ins["_north_y_from_latitude"].to_numpy(),
        ins["_up_z_from_height"].to_numpy(),
    ], axis=1)

    rotations = Rotation.from_euler(
        "xyz",
        np.vstack([ins["_roll"].to_numpy(),
                   ins["_pitch"].to_numpy(),
                   ins["_yaw_from_azimuth"].to_numpy()]).T,
        degrees=True,
    ).as_quat()  # [x,y,z,w]

    # ── Load sample_data ──────────────────────────────────────────────────────
    with open(os.path.join(args.meta, "sample_data.json")) as f:
        sd = json.load(f)

    # Each sample_data has ego_pose_token == its own token, timestamp in µs
    tokens     = np.array([e["ego_pose_token"] for e in sd])
    timestamps = np.array([e["timestamp"]      for e in sd], dtype=np.float64)
    t_seconds  = timestamps / 1e6  # µs → s

    # ── Interpolate ───────────────────────────────────────────────────────────
    pos_interp, rot_interp = interpolate_pose(ins_times, positions, rotations, t_seconds)

    # ── Build ego_pose entries ────────────────────────────────────────────────
    ego_poses = []
    for i in range(len(sd)):
        ego_poses.append({
            "token":       tokens[i],
            "timestamp":   int(timestamps[i]),
            "translation": pos_interp[i].tolist(),
            "rotation":    quat_to_nuscenes(rot_interp[i]),
        })

    path = os.path.join(args.meta, "ego_pose.json")
    with open(path, "w") as f:
        json.dump(ego_poses, f, indent=2)
    print(f"Wrote {path}  ({len(ego_poses)} entries)")
    print(f"  time range: {t_seconds.min():.3f}s ~ {t_seconds.max():.3f}s")
    print(f"  INS range:  {ins_times.min():.3f}s ~ {ins_times.max():.3f}s")


if __name__ == "__main__":
    main()
