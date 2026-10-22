"""
build_sample_tables.py — generate sample.json and sample_data.json for CATS dataset.

- sample:      1 entry per LiDAR frame (10Hz keyframe)
- sample_data: 7 sensors × N frames, ego_pose_token == sample_data_token (nuScenes convention)
- calibrated_sensor tokens are pre-generated here (one per sensor, fixed for the scene)
  → printed at the end for use in build_calibrated_sensor.py

Run:
  python3 build_sample_tables.py \
    --meta  /home/data/workzone/work_zone_dataset/work_zone_data_nuScenes/CATS_v1.0 \
    --scene_dir /home/data/workzone/work_zone_dataset/work_zone_data_nuScenes/scene-CATS-01
"""

import os
import glob
import json
import uuid
import argparse


def token():
    return uuid.uuid4().hex


# sensor channel → (src subfolder, fileformat, width, height)
SENSOR_META = {
    "LIDAR_TOP":       ("LIDAR_TOP",       "pcd", 0,    0),
    "CAM_FRONT":       ("CAM_FRONT",       "jpg", 3840, 2160),
    "CAM_BACK":        ("CAM_BACK",        "jpg", 3840, 2162),
    "CAM_FRONT_LEFT":  ("CAM_FRONT_LEFT",  "jpg", 1920, 1536),
    "CAM_FRONT_RIGHT": ("CAM_FRONT_RIGHT", "jpg", 1920, 1536),
    "CAM_BACK_LEFT":   ("CAM_BACK_LEFT",   "jpg", 1920, 1536),
    "CAM_BACK_RIGHT":  ("CAM_BACK_RIGHT",  "jpg", 1920, 1536),
}


def sorted_files(folder, ext):
    files = glob.glob(os.path.join(folder, f"*.{ext}"))
    return sorted(files, key=lambda p: int(p.split("__")[-1].split(".")[0]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--meta",      required=True, help="CATS_v1.0 folder")
    parser.add_argument("--scene_dir", required=True, help="scene-CATS-01 folder")
    args = parser.parse_args()

    # ── Load existing tables ──────────────────────────────────────────────────
    with open(os.path.join(args.meta, "scene.json")) as f:
        scene = json.load(f)[0]
    with open(os.path.join(args.meta, "sensor.json")) as f:
        sensor_token = {s["channel"]: s["token"] for s in json.load(f)}

    scene_token        = scene["token"]
    first_sample_token = scene["first_sample_token"]
    last_sample_token  = scene["last_sample_token"]

    # ── Pre-generate calibrated_sensor tokens (one per sensor, scene-wide) ───
    cal_sensor_token = {ch: token() for ch in SENSOR_META}

    # ── Collect file lists per sensor ─────────────────────────────────────────
    ext_map = {"pcd": "pcd.bin", "jpg": "jpg"}
    sensor_files = {}
    for ch, (subfolder, fmt, w, h) in SENSOR_META.items():
        folder = os.path.join(args.scene_dir, subfolder)
        ext    = "bin" if fmt == "pcd" else "jpg"
        files  = sorted(glob.glob(os.path.join(folder, f"*.{ext}")),
                        key=lambda p: int(p.split("__")[-1].split(".")[0]))
        sensor_files[ch] = files

    n = len(sensor_files["LIDAR_TOP"])
    print(f"Frames per sensor: {n}")
    for ch, files in sensor_files.items():
        if len(files) != n:
            print(f"  [warn] {ch} has {len(files)} frames, expected {n}")

    # ── Generate sample tokens (one per LiDAR frame) ─────────────────────────
    sample_tokens = [token() for _ in range(n)]
    sample_tokens[0]    = first_sample_token
    sample_tokens[n - 1] = last_sample_token

    # ── Build sample.json ─────────────────────────────────────────────────────
    lidar_files = sensor_files["LIDAR_TOP"]
    samples = []
    for i, lidar_path in enumerate(lidar_files):
        ts = int(os.path.basename(lidar_path).split("__")[-1].split(".")[0])
        samples.append({
            "token":       sample_tokens[i],
            "timestamp":   ts,
            "scene_token": scene_token,
            "prev":        sample_tokens[i - 1] if i > 0     else "",
            "next":        sample_tokens[i + 1] if i < n - 1 else "",
        })
    _write(args.meta, "sample.json", samples)

    # ── Build sample_data.json ────────────────────────────────────────────────
    # prev/next chains per sensor
    sd_tokens = {ch: [token() for _ in range(n)] for ch in SENSOR_META}

    sample_data = []
    for ch, (subfolder, fmt, w, h) in SENSOR_META.items():
        files  = sensor_files[ch]
        tokens = sd_tokens[ch]
        for i, fpath in enumerate(files):
            fname    = os.path.basename(fpath)
            ts       = int(fname.split("__")[-1].split(".")[0])
            sd_tok   = tokens[i]
            rel_path = f"scene-CATS-01/{subfolder}/{fname}"
            sample_data.append({
                "token":                    sd_tok,
                "sample_token":             sample_tokens[i],
                "ego_pose_token":           sd_tok,          # same token (nuScenes convention)
                "calibrated_sensor_token":  cal_sensor_token[ch],
                "timestamp":                ts,
                "fileformat":               fmt,
                "is_key_frame":             True,
                "height":                   h,
                "width":                    w,
                "filename":                 rel_path,
                "prev":                     tokens[i - 1] if i > 0     else "",
                "next":                     tokens[i + 1] if i < n - 1 else "",
            })
    _write(args.meta, "sample_data.json", sample_data)

    # ── Print tokens for downstream scripts ───────────────────────────────────
    print("\ncalibrated_sensor tokens (use in build_calibrated_sensor.py):")
    for ch, tok in cal_sensor_token.items():
        print(f"  {ch}: {tok}")


def _write(dst, filename, data):
    path = os.path.join(dst, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote {path}  ({len(data)} entries)")


if __name__ == "__main__":
    main()
