"""
build_frames_index.py — build scenes/<scene>/frames.json directly for a self-collected CATS-style
scene, without touching the shared CATS_v1.0 nuScenes-table singleton (which only covers scene-CATS-01).

This is the "index" format that preprocessing.device_map.Meta prefers (checked before the CATS_v1.0
fallback), the same format already used for the curated scene-nusc-*/scene-waymo-* scenes — so a scene
built this way is immediately usable by the whole QA_Pipeline toolchain (device_map.py, Stage 2
builder, figure scripts) with no further plumbing.

Frame indexing follows build_sample_tables.py's convention: each of the 7 sensor folders is sorted by
its own filename timestamp and zipped by position (not by nearest-timestamp matching); undistort_cameras.py
already makes every camera's 10 Hz selection land in the same count as LIDAR_TOP.

Run:
  python3 build_frames_index.py \
    --scene_dir  /home/data/workzone/work_zone_dataset/work_zone_data_nuScenes/scene-CATS-02 \
    --calib      /home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_01/calibration \
    --ins        /home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_01/ins/gnss.csv \
    --out        /home/data/workzone/work_zone_code/QA_Pipeline/scenes/scene-CATS-02/frames.json \
    --scene_name scene-CATS-02 \
    --log_id     cats002-2026-09-24-15-40-0500 \
    --date_captured 2026-09-24
"""

import os
import glob
import json
import argparse
import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation, Slerp

def abspath(p):
    return os.path.abspath(p)

# nuScenes channel -> raw calibration camera key (same mapping as build_calibrated_sensor.py / undistort_cameras.py)
CHANNEL_TO_CAM = {
    "CAM_FRONT":       "camera0",
    "CAM_BACK":        "camera2",
    "CAM_FRONT_LEFT":  "camera5",
    "CAM_FRONT_RIGHT": "camera7",
    "CAM_BACK_LEFT":   "camera4",
    "CAM_BACK_RIGHT":  "camera6",
}


def quat_to_nuscenes(q_xyzw):
    """scipy [x,y,z,w] -> nuScenes-style [w,x,y,z]"""
    x, y, z, w = q_xyzw
    return [float(w), float(x), float(y), float(z)]


def sorted_files(folder, ext):
    files = glob.glob(os.path.join(folder, f"*.{ext}"))
    return sorted(files, key=lambda p: int(p.split("__")[-1].split(".")[0]))


def load_ins(ins_path):
    ins = pd.read_csv(ins_path)
    times = (ins["_header._stamp._sec"].to_numpy() + ins["_header._stamp._nanosec"].to_numpy() * 1e-9)
    positions = np.stack([ins["_east_x_from_longitude"].to_numpy(),
                           ins["_north_y_from_latitude"].to_numpy(),
                           ins["_up_z_from_height"].to_numpy()], axis=1)
    rotations = Rotation.from_euler(
        "xyz",
        np.vstack([ins["_roll"].to_numpy(), ins["_pitch"].to_numpy(), ins["_yaw_from_azimuth"].to_numpy()]).T,
        degrees=True,
    ).as_quat()  # [x,y,z,w]
    return times, positions, rotations


def interpolate_pose(ins_times, positions, rotations_quat, t_query):
    px = np.interp(t_query, ins_times, positions[:, 0])
    py = np.interp(t_query, ins_times, positions[:, 1])
    pz = np.interp(t_query, ins_times, positions[:, 2])
    t_clamped = np.clip(t_query, ins_times[0], ins_times[-1])
    slerp = Slerp(ins_times, Rotation.from_quat(rotations_quat))
    rot = slerp(t_clamped).as_quat()
    return np.stack([px, py, pz], axis=1), rot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene_dir",     required=True, help="scene-CATS-0N folder (CALIBRATION/ + 6 CAM dirs + LIDAR_TOP)")
    ap.add_argument("--calib",         required=True, help="Case_XX/calibration folder (calib_black_*.json)")
    ap.add_argument("--ins",           required=True, help="Case_XX/ins/gnss.csv (post ENU+yaw conversion)")
    ap.add_argument("--out",           required=True, help="output frames.json path")
    ap.add_argument("--scene_name",    required=True)
    ap.add_argument("--log_id",        required=True)
    ap.add_argument("--date_captured", required=True, help="YYYY-MM-DD")
    ap.add_argument("--vehicle",       default="black")
    ap.add_argument("--description",   default="Work zone scene")
    args = ap.parse_args()

    # ── calibration: LIDAR_TOP direct, cameras composed through it (same as build_calibrated_sensor.py) ──
    with open(os.path.join(args.calib, "calib_black_ins.json")) as f:
        T_lidar_ins = np.array(json.load(f)["black_ins"]["T_lidar_ins"])
    p_L_I = T_lidar_ins[:3]
    R_L_I = Rotation.from_quat(T_lidar_ins[3:])

    with open(os.path.join(args.scene_dir, "CALIBRATION", "undistorted_intrinsics.json")) as f:
        intrinsics = json.load(f)

    calibrated_sensors = {
        "LIDAR_TOP": {"translation": p_L_I.tolist(), "rotation": quat_to_nuscenes(R_L_I.as_quat()), "camera_intrinsic": []},
    }
    for channel, cam_name in CHANNEL_TO_CAM.items():
        with open(os.path.join(args.calib, f"calib_black_{cam_name}.json")) as f:
            T_lc = np.array(json.load(f)[f"black_{cam_name}"]["T_lidar_camera"])
        p_C_L, R_C_L = T_lc[:3], Rotation.from_quat(T_lc[3:])
        p_C_I = p_L_I + R_L_I.apply(p_C_L)
        R_C_I = R_L_I * R_C_L
        calibrated_sensors[channel] = {"translation": p_C_I.tolist(), "rotation": quat_to_nuscenes(R_C_I.as_quat()),
                                        "camera_intrinsic": intrinsics[channel]["camera_intrinsic"]}

    # ── per-sensor sorted file lists (index-aligned, as in build_sample_tables.py) ──
    sensor_files = {"LIDAR_TOP": sorted_files(os.path.join(args.scene_dir, "LIDAR_TOP"), "bin")}
    for channel in CHANNEL_TO_CAM:
        sensor_files[channel] = sorted_files(os.path.join(args.scene_dir, channel), "jpg")

    n = len(sensor_files["LIDAR_TOP"])
    for ch, files in sensor_files.items():
        if len(files) != n:
            print(f"[warn] {ch} has {len(files)} frames, expected {n} (LIDAR_TOP)")
    n = min(n, *[len(f) for f in sensor_files.values()])

    def ts_of(path):
        return int(os.path.basename(path).split("__")[-1].split(".")[0])

    # ── ego pose: interpolate INS at each sensor's own per-frame timestamp ──
    ins_times, ins_pos, ins_rot = load_ins(args.ins)

    def pose_at(ts_us):
        p, r = interpolate_pose(ins_times, ins_pos, ins_rot, np.array([ts_us / 1e6]))
        return {"translation": p[0].tolist(), "rotation": quat_to_nuscenes(r[0])}

    frames = []
    for i in range(n):
        lidar_path = sensor_files["LIDAR_TOP"][i]
        cam_path = sensor_files["CAM_FRONT"][i]
        cams = {ch: abspath(sensor_files[ch][i]) for ch in CHANNEL_TO_CAM}
        cam_ts = {ch: ts_of(sensor_files[ch][i]) for ch in CHANNEL_TO_CAM}
        frames.append({
            "segment":        args.scene_name,
            "timestamp":      ts_of(cam_path),
            "is_key_frame":   True,
            "cams":           cams,
            "cam_timestamps": cam_ts,
            "lidar":          abspath(lidar_path),
            "lidar_timestamp": ts_of(lidar_path),
            "ego_pose_cam":   pose_at(ts_of(cam_path)),
            "ego_pose_lidar": pose_at(ts_of(lidar_path)),
            "index":          i,
        })

    out = {
        "scene_name":            args.scene_name,
        "source":                "cats",
        "log_id":                args.log_id,
        "vehicle":                args.vehicle,
        "date_captured":         args.date_captured,
        "description":           args.description,
        "fps":                   10.0,
        "n_frames":              n,
        "time_gaps":             [],
        "sensor_frame_rotation": "cats",     # CATS calibrated_sensor frame (x right/y forward) != ego_pose frame (nuScenes convention); Meta.s2p() compensates
        "ego_origin_height_m":   1.6,
        "calibrated_sensors":    calibrated_sensors,
        "frames":                frames,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"Wrote {args.out}  ({n} frames)")


if __name__ == "__main__":
    main()
