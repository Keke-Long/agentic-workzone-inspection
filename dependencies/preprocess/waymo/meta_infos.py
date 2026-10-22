import os
import json
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from argparse import ArgumentParser
from scipy.spatial.transform import Rotation, Slerp

def load_ins_pose(gnss_path):
    ins = pd.read_csv(gnss_path)
    times = ins["_header._stamp._sec"] + ins["_header._stamp._nanosec"] * 1e-9
    positions = np.stack([
        ins["_east_x_from_longitude"].to_numpy(),
        ins["_north_y_from_latitude"].to_numpy(),
        ins["_up_z_from_height"].to_numpy()
    ], axis=1)
    roll = ins["_roll"].to_numpy()
    pitch = ins["_pitch"].to_numpy()
    yaw = ins["_yaw_from_azimuth"].to_numpy()
    rotations = Rotation.from_euler("xyz", np.vstack([roll, pitch, yaw]).T, degrees=True)
    return times, positions, rotations

def interpolate_pose(times, positions, rotations, t_query):
    p_interp = np.stack([
        np.interp(t_query, times, positions[:, 0]),
        np.interp(t_query, times, positions[:, 1]),
        np.interp(t_query, times, positions[:, 2])
    ], axis=0).T
    slerp = Slerp(times, rotations)
    r_interp = slerp([t_query])[0].as_matrix()
    return p_interp, r_interp

# def make_lidar2world(pos, rot_mat, T_lidar_ins):
#     R_i = rot_mat
#     p_i = pos.reshape(3, 1)
#     R_L_I = Rotation.from_quat(T_lidar_ins[3:]).as_matrix()
#     p_L_I = T_lidar_ins[:3].reshape(3, 1)
#     R_W_L = R_i @ R_L_I
#     p_W_L = R_i @ p_L_I + p_i
#     Tw = np.eye(4)
#     Tw[:3, :3] = R_W_L
#     Tw[:3, 3] = p_W_L[:, 0]
#     return Tw
    
def make_lidar2world(pos, rot_mat, T_lidar_ins):
    R_i = rot_mat                              # INS -> World
    p_i = pos.reshape(3, 1)

    # LiDAR -> INS extrinsic
    R_L_I = Rotation.from_quat(T_lidar_ins[3:]).as_matrix()
    p_L_I = T_lidar_ins[:3].reshape(3, 1)

    # 90-degree rotation fix
    R_fix = np.array([
        [0,  1, 0],
        [-1, 0, 0],
        [0,  0, 1]
    ], dtype=float)

    # Apply fix in the LiDAR frame BEFORE extrinsic
    R_L_I_fixed = R_L_I @ R_fix

    # Compose INS -> World with corrected LiDAR orientation
    R_W_L = R_i @ R_L_I_fixed
    p_W_L = R_i @ p_L_I + p_i

    # Build transform
    Tw = np.eye(4)
    Tw[:3, :3] = R_W_L
    Tw[:3, 3] = p_W_L[:, 0]
    return Tw


def parse_extrinsic_lidar_camera(T_lidar_camera):
    t = np.array(T_lidar_camera[:3])
    q = np.array(T_lidar_camera[3:])
    R = Rotation.from_quat(q).as_matrix()
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T

def parse_args():
    parser = ArgumentParser(description="Generate JSON with camera/lidar/INS calibration and poses")
    parser.add_argument("--seq", type=str, required=True, help="Sequence name, e.g. segment-xxx")
    parser.add_argument("--base_dir", type=str, required=True, help="Base directory for data")
    parser.add_argument("--gnss", type=str, required=True, help="Path to GNSS CSV file")
    parser.add_argument("--cam_calib", type=str, required=True, help="Camera calibration JSON path")
    parser.add_argument("--ins_calib", type=str, required=True, help="INS to Lidar calibration JSON path")
    parser.add_argument("--out", type=str, required=True, help="Output JSON file path")
    return parser.parse_args()

def main():
    args = parse_args()
    base_seq = args.seq
    base_dir = Path(args.base_dir)
    #pcd_dir = base_dir / "workzone_dataset" / "pcds" / base_seq
    #img_dir = base_dir / "workzone_dataset" / "undistort_images" / base_seq
    pcd_dir = base_dir / "workzone_dataset(200)" / "pcds" / base_seq
    img_dir = base_dir / "workzone_dataset(200)" / "undistort_images" / base_seq
    print(f"📁 处理序列: {base_seq}")
    print(f"    点云目录: {pcd_dir}")
    print(f"    图像目录: {img_dir}")
    out_json = Path(args.out)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    with open(args.cam_calib) as f:
        cam_calib = json.load(f)
    cam_key = list(cam_calib.keys())[0]
    K = np.array(cam_calib[cam_key]["intrinsics"])
    K_str = np.array2string(K, separator=' ', max_line_width=np.inf)
    T_camera_lidar = parse_extrinsic_lidar_camera(cam_calib[cam_key]["T_lidar_camera"])
    T_camera_lidar_str = np.array2string(T_camera_lidar, separator=' ', max_line_width=np.inf)

    with open(args.ins_calib) as f:
        ins_calib = json.load(f)
    T_lidar_ins = np.array(ins_calib["black_ins"]["T_lidar_ins"])

    ins_times, ins_pos, ins_rots = load_ins_pose(args.gnss)

    frames = []
    idx = 0
    while True:
        pcd_path = pcd_dir / f"{idx:03d}.npz"
        img_path = img_dir / f"{idx:03d}" / "Front.jpg"
        if not pcd_path.exists() or not img_path.exists():
            break

        t_ref = 1.0 + idx * 0.1
        try:
            pos, rot = interpolate_pose(ins_times, ins_pos, ins_rots, t_ref)
        except Exception as e:
            print(f"⚠️ 插值失败: idx={idx}, time={t_ref}, 原因: {e}")
            idx += 1
            continue

        lidar2world = make_lidar2world(pos, rot, T_lidar_ins)

        lidar2world_str = np.array2string(lidar2world, separator=' ', max_line_width=np.inf)

        frame = {
            "cams_info": {
                "FRONT": {
                    "data_path": str(img_path.relative_to(base_dir)),
                    "camera_intrinsics": K_str,
                    "camera2lidar": T_camera_lidar_str
                }
            },
            "path": {
                "pcd": str(pcd_path.relative_to(base_dir))
            },
            "lidar2world": lidar2world_str
        }

        frames.append(frame)
        idx += 1

    output = {
        "seq_name": base_seq,
        "frames": frames
    }
    with open(out_json, "w") as f:
        json.dump(output, f, indent=2)
    print(f"✅ 成功写入 JSON 文件：{out_json}")
    
    # 追加：同时写入 PKL
    out_pkl = out_json.with_suffix(".pkl")
    with open(out_pkl, "wb") as f:
        pickle.dump(output, f)
    print(f"✅ 成功写入 PKL 文件：{out_pkl}")

if __name__ == "__main__":
    main()
