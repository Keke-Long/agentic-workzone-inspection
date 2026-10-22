import os
import json
import glob
import argparse
import numpy as np
import pandas as pd
from pypcd4 import PointCloud
from scipy.spatial.transform import Rotation, Slerp


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def interpolate_pose(times, positions, rotations, t_query):
    px = np.interp(t_query, times, positions[:, 0])
    py = np.interp(t_query, times, positions[:, 1])
    pz = np.interp(t_query, times, positions[:, 2])
    p_interp = np.stack([px, py, pz], axis=1)

    # np.interp 自动外推边界值，Slerp 不支持外推，clamp 到有效范围
    t_clamped = np.clip(t_query, times[0], times[-1])
    slerp = Slerp(times, Rotation.from_quat(rotations))
    rot_q = slerp(t_clamped)
    r_interp = rot_q.as_quat()
    return p_interp, r_interp


def deskew(points, fields, ins_times, ins_positions, ins_rotations, extrinsic, t_ref):
    pcs = points.copy()
    name_to_idx = {n: i for i, n in enumerate(fields)}
    itime = name_to_idx.get("timestamp")
    ix, iy, iz = name_to_idx["x"], name_to_idx["y"], name_to_idx["z"]
    time_i = pcs[:, itime].astype(float)

    p_i, r_i = interpolate_pose(ins_times, ins_positions, ins_rotations, time_i)
    p_ref, r_ref = interpolate_pose(ins_times, ins_positions, ins_rotations, np.array([t_ref]))
    p_ref, r_ref = p_ref[0], r_ref[0]

    R_i = Rotation.from_quat(r_i).as_matrix()
    R_ref = Rotation.from_quat(r_ref).as_matrix()

    p_L_I = extrinsic[:3]
    R_L_I = Rotation.from_quat(extrinsic[3:]).as_matrix()

    R_WL_i = np.einsum('mij,jk->mik', R_i, R_L_I)
    p_WL_i = p_i + (R_i @ p_L_I.reshape(3, 1)).squeeze(-1)

    R_WL_ref = R_ref @ R_L_I
    p_WL_ref = p_ref + R_ref @ p_L_I
    R_LW_ref = R_WL_ref.T

    R_fix = np.array([[0, 1, 0],
                      [-1, 0, 0],
                      [0, 0, 1]], dtype=float)

    P_L = pcs[:, [ix, iy, iz]].astype(float)
    P_L = (R_fix @ P_L.T).T

    p_world = (R_WL_i @ P_L[..., None]).squeeze(-1) + p_WL_i
    P_ref = (R_LW_ref @ (p_world - p_WL_ref).T).T
    P_out = (R_fix.T @ P_ref.T).T
    return P_out  # Only return x,y,z


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src",    required=True,  help="Folder containing .pcd files")
    parser.add_argument("--dst",    required=True,  help="Output folder to save .npz files")
    parser.add_argument("--calib",  default=None,   help="Path to extrinsic JSON file (required unless --no_deskew)")
    parser.add_argument("--ins",    default=None,   help="Path to INS CSV file (required unless --no_deskew)")
    parser.add_argument("--z_min",  type=float, default=-1.5, help="Filter points below this height in LiDAR frame (default: -1.5)")
    parser.add_argument("--t_ref_start", type=float, default=None,
                        help="Deskew reference time for idx=0 (e.g. camera start 1.9333). "
                             "Each frame uses t_ref_start + idx*0.1. "
                             "If not set, uses the PCD file timestamp.")
    parser.add_argument("--no_deskew", action="store_true",
                        help="Skip deskew, save raw xyz directly.")
    args = parser.parse_args()

    if not args.no_deskew and (args.calib is None or args.ins is None):
        parser.error("--calib and --ins are required unless --no_deskew is set.")

    ensure_dir(args.dst)

    if not args.no_deskew:
        extrinsic = np.array(json.load(open(args.calib))["black_ins"]["T_lidar_ins"])

        ins = pd.read_csv(args.ins)
        ins_sec = ins["_header._stamp._sec"].to_numpy()
        ins_nsec = ins["_header._stamp._nanosec"].to_numpy()
        ins_times = ins_sec + ins_nsec * 1e-9

        ins_positions = np.stack([
            ins["_east_x_from_longitude"].to_numpy(),
            ins["_north_y_from_latitude"].to_numpy(),
            ins["_up_z_from_height"].to_numpy()
        ], axis=1)

        roll = ins["_roll"].to_numpy()
        pitch = ins["_pitch"].to_numpy()
        yaw = ins["_yaw_from_azimuth"].to_numpy()
        ins_rotations = Rotation.from_euler('xyz', np.vstack([roll, pitch, yaw]).T, degrees=True).as_quat()

    # 正确排序：根据文件名中的浮点时间戳排序
    pcd_list = sorted(
        glob.glob(os.path.join(args.src, "*.pcd")),
        key=lambda x: float(os.path.splitext(os.path.basename(x))[0])
    )

    for idx, pcd_path in enumerate(pcd_list):
        print(f"Processing {pcd_path}...")
        pc = PointCloud.from_path(pcd_path)
        fields = list(pc.fields)
        points = pc.numpy()

        if args.no_deskew:
            name_to_idx = {n: i for i, n in enumerate(fields)}
            ix, iy, iz = name_to_idx["x"], name_to_idx["y"], name_to_idx["z"]
            xyz = points[:, [ix, iy, iz]].astype(float)
        else:
            if args.t_ref_start is not None:
                t_ref = args.t_ref_start + idx * 0.1
            else:
                t_ref = float(os.path.splitext(os.path.basename(pcd_path))[0])

            xyz = deskew(
                points, fields,
                ins_times, ins_positions, ins_rotations,
                extrinsic,
                t_ref
            )

        before = len(xyz)
        xyz = xyz[xyz[:, 2] > args.z_min]
        print(f"  Height filter z>{args.z_min}: {before} -> {len(xyz)} pts")

        out_path = os.path.join(args.dst, f"{idx:03d}.npz")
        np.savez_compressed(out_path, xyz=xyz)
        print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()