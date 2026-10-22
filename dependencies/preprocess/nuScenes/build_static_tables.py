"""
build_static_tables.py — generate sensor.json, log.json, map.json, scene.json for CATS dataset.

scene.json includes pre-generated first_sample_token / last_sample_token so that
build_sample.py can read them and assign them to the correct samples without
generating new tokens.

Run:
  python3 build_static_tables.py \
    --dst        /home/data/workzone/work_zone_dataset/work_zone_data_nuScenes/CATS_v1.0 \
    --lidar_dir  /home/data/workzone/work_zone_dataset/work_zone_data_nuScenes/scene-CATS-01/LIDAR_TOP
"""

import os
import glob
import json
import uuid
import argparse


def token():
    return uuid.uuid4().hex


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dst",       required=True, help="Output folder (CATS_v1.0)")
    parser.add_argument("--lidar_dir", required=True, help="LIDAR_TOP folder to count samples")
    args = parser.parse_args()
    os.makedirs(args.dst, exist_ok=True)

    # ── sensor.json ──────────────────────────────────────────────────────────
    sensors = [
        {"token": token(), "channel": "LIDAR_TOP",       "modality": "lidar"},
        {"token": token(), "channel": "CAM_FRONT",        "modality": "camera"},
        {"token": token(), "channel": "CAM_BACK",         "modality": "camera"},
        {"token": token(), "channel": "CAM_FRONT_LEFT",   "modality": "camera"},
        {"token": token(), "channel": "CAM_FRONT_RIGHT",  "modality": "camera"},
        {"token": token(), "channel": "CAM_BACK_LEFT",    "modality": "camera"},
        {"token": token(), "channel": "CAM_BACK_RIGHT",   "modality": "camera"},
    ]
    _write(args.dst, "sensor.json", sensors)

    # ── log.json ─────────────────────────────────────────────────────────────
    log_token = token()
    logs = [
        {
            "token":         log_token,
            "logfile":       "cats001-2026-04-28-15-30-0500",
            "vehicle":       "black",
            "date_captured": "2026-04-28",
            "location":      "madison-wi-usa",
        }
    ]
    _write(args.dst, "log.json", logs)

    # ── map.json ─────────────────────────────────────────────────────────────
    maps = [
        {
            "token":      token(),
            "category":   "semantic_prior",
            "filename":   "maps/cats_map.png",
            "log_tokens": [log_token],
        }
    ]
    _write(args.dst, "map.json", maps)

    # ── scene.json ───────────────────────────────────────────────────────────
    nbr_samples = len(glob.glob(os.path.join(args.lidar_dir, "*.pcd.bin")))
    scene_token       = token()
    first_sample_token = token()
    last_sample_token  = token()

    scenes = [
        {
            "token":              scene_token,
            "log_token":          log_token,
            "nbr_samples":        nbr_samples,
            "first_sample_token": first_sample_token,
            "last_sample_token":  last_sample_token,
            "name":               "scene-CATS-01",
            "description":        "Work zone scene, Madison WI, 2026-04-28",
        }
    ]
    _write(args.dst, "scene.json", scenes)

    print("\nTokens to reuse in other tables:")
    print(f"  log_token:          {log_token}")
    print(f"  scene_token:        {scene_token}")
    print(f"  first_sample_token: {first_sample_token}")
    print(f"  last_sample_token:  {last_sample_token}")
    for s in sensors:
        print(f"  sensor {s['channel']}: {s['token']}")


def _write(dst, filename, data):
    path = os.path.join(dst, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote {path}  ({len(data)} entries)")


if __name__ == "__main__":
    main()
