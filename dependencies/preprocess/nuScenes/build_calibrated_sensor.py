"""
build_calibrated_sensor.py — generate calibrated_sensor.json for CATS dataset.

Transform chain:
  Camera → LiDAR (T_lidar_camera) → INS/ego (T_lidar_ins)
  LIDAR  → INS/ego directly        (T_lidar_ins)

calibrated_sensor_tokens are read from sample_data.json (stored there by build_sample_tables.py).

Run:
  python3 build_calibrated_sensor.py \
    --meta       /home/data/workzone/work_zone_dataset/work_zone_data_nuScenes/CATS_v1.0 \
    --calib      /home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_05/calibration \
    --intrinsics /home/data/workzone/work_zone_dataset/work_zone_data_nuScenes/scene-CATS-01/calibration/undistorted_intrinsics.json
"""

import os
import json
import argparse
import numpy as np
from scipy.spatial.transform import Rotation


# nuScenes channel → raw calibration camera key
CHANNEL_TO_CAM = {
    "CAM_FRONT":       "camera0",
    "CAM_BACK":        "camera2",
    "CAM_FRONT_LEFT":  "camera5",
    "CAM_FRONT_RIGHT": "camera7",
    "CAM_BACK_LEFT":   "camera4",
    "CAM_BACK_RIGHT":  "camera6",
}


def quat_to_nuscenes(q_xyzw):
    """scipy [x,y,z,w] → nuScenes [w,x,y,z]"""
    x, y, z, w = q_xyzw
    return [w, x, y, z]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--meta",       required=True, help="CATS_v1.0 folder")
    parser.add_argument("--calib",      required=True, help="Case_XX/calibration folder")
    parser.add_argument("--intrinsics", required=True, help="undistorted_intrinsics.json path")
    args = parser.parse_args()

    # ── Load inputs ───────────────────────────────────────────────────────────
    with open(os.path.join(args.meta, "sensor.json")) as f:
        sensor_token = {s["channel"]: s["token"] for s in json.load(f)}

    with open(os.path.join(args.meta, "sample_data.json")) as f:
        sd = json.load(f)

    # Extract unique calibrated_sensor_token per channel from sample_data
    cal_token = {}
    for entry in sd:
        channel = entry["filename"].split("/")[1]  # "LIDAR_TOP", "CAM_FRONT", ...
        cal_token[channel] = entry["calibrated_sensor_token"]

    with open(args.intrinsics) as f:
        intrinsics = json.load(f)

    with open(os.path.join(args.calib, "calib_black_ins.json")) as f:
        T_lidar_ins = np.array(json.load(f)["black_ins"]["T_lidar_ins"])

    p_L_in_I = T_lidar_ins[:3]
    R_L_to_I = Rotation.from_quat(T_lidar_ins[3:])  # [x,y,z,w]

    # ── Build entries ─────────────────────────────────────────────────────────
    entries = []

    # LIDAR_TOP: directly from T_lidar_ins
    entries.append({
        "token":            cal_token["LIDAR_TOP"],
        "sensor_token":     sensor_token["LIDAR_TOP"],
        "translation":      p_L_in_I.tolist(),
        "rotation":         quat_to_nuscenes(R_L_to_I.as_quat()),
        "camera_intrinsic": [],
    })
    print(f"LIDAR_TOP: translation={p_L_in_I.tolist()}")

    # Cameras: compose T_lidar_camera with T_lidar_ins
    for channel, cam_name in CHANNEL_TO_CAM.items():
        calib_path = os.path.join(args.calib, f"calib_black_{cam_name}.json")
        with open(calib_path) as f:
            T_lc = np.array(json.load(f)[f"black_{cam_name}"]["T_lidar_camera"])

        p_C_in_L = T_lc[:3]
        R_C_to_L = Rotation.from_quat(T_lc[3:])

        # Camera in INS/ego frame
        p_C_in_I = p_L_in_I + R_L_to_I.apply(p_C_in_L)
        R_C_to_I = R_L_to_I * R_C_to_L

        cam_intrinsic = intrinsics[channel]["camera_intrinsic"]

        entries.append({
            "token":            cal_token[channel],
            "sensor_token":     sensor_token[channel],
            "translation":      p_C_in_I.tolist(),
            "rotation":         quat_to_nuscenes(R_C_to_I.as_quat()),
            "camera_intrinsic": cam_intrinsic,
        })
        print(f"{channel} ({cam_name}): translation={[round(v,4) for v in p_C_in_I.tolist()]}")

    path = os.path.join(args.meta, "calibrated_sensor.json")
    with open(path, "w") as f:
        json.dump(entries, f, indent=2)
    print(f"\nWrote {path}  ({len(entries)} entries)")


if __name__ == "__main__":
    main()
