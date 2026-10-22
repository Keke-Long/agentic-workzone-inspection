"""
undistort_cameras.py — undistort + 10Hz downsample camera frames → nuScenes .jpg

Camera mapping:
  camera0 → CAM_FRONT       (x.x333 frames)
  camera2 → CAM_BACK        (x.x333 frames)
  camera5 → CAM_FRONT_LEFT  (x.x333 frames)
  camera7 → CAM_FRONT_RIGHT (x.x333 frames)
  camera4 → CAM_BACK_LEFT   (x.x666 frames)
  camera6 → CAM_BACK_RIGHT  (x.x666 frames)

Output filename: {log_id}__{sensor_name}__{timestamp_us}.jpg
New K matrix saved to: {dst}/calibration/undistorted_intrinsics.json

Run:
  python3 undistort_cameras.py \
    --src   /home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_05 \
    --dst   /home/data/workzone/work_zone_dataset/work_zone_data_nuScenes/scene-CATS-01 \
    --t_start 10.0 \
    --log_id  cats001-2026-04-28-15-30-0500
"""

import os
import cv2
import json
import glob
import argparse
import numpy as np
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor

# ── Camera config ─────────────────────────────────────────────────────────────

CAMERAS = [
    # (src_folder, sensor_name, target_frac)
    # target_frac: t % 0.1 target value for 10Hz selection
    ("camera0", "CAM_FRONT",       0.033333),
    ("camera2", "CAM_BACK",        0.033333),
    ("camera5", "CAM_FRONT_LEFT",  0.033333),
    ("camera7", "CAM_FRONT_RIGHT", 0.033333),
    ("camera4", "CAM_BACK_LEFT",   0.066666),
    ("camera6", "CAM_BACK_RIGHT",  0.066666),
]

FRAC_TOL = 0.010   # 10ms tolerance for frame selection


# ── Calibration ───────────────────────────────────────────────────────────────

def load_calib(calib_dir, cam_name):
    path = os.path.join(calib_dir, f"calib_black_{cam_name}.json")
    with open(path) as f:
        c = json.load(f)[f"black_{cam_name}"]
    fx, fy, cx, cy = c["intrinsics"]
    K = np.array([[fx, 0, cx],
                  [0, fy, cy],
                  [0,  0,  1]], dtype=np.float64)
    D = np.array(c["distortion_coeffs"], dtype=np.float64)
    return K, D


# ── Frame selection ───────────────────────────────────────────────────────────

def select_frames(src_folder, t_start, target_frac):
    """Return sorted list of (t, path) for frames matching the 10Hz target."""
    paths = glob.glob(os.path.join(src_folder, "*.png"))
    selected = []
    for p in paths:
        t = float(os.path.splitext(os.path.basename(p))[0])
        if t < t_start:
            continue
        if abs(t % 0.1 - target_frac) < FRAC_TOL:
            selected.append((t, p))
    return sorted(selected, key=lambda x: x[0])


# ── Undistort ─────────────────────────────────────────────────────────────────

def compute_undistort_maps(K, D, img_size):
    """Precompute remap tables and return (map1, map2, new_K)."""
    h, w = img_size
    new_K, _ = cv2.getOptimalNewCameraMatrix(K, D, (w, h), alpha=0)
    map1, map2 = cv2.initUndistortRectifyMap(K, D, None, new_K, (w, h), cv2.CV_16SC2)
    return map1, map2, new_K


def undistort_frame(img, map1, map2):
    return cv2.remap(img, map1, map2, interpolation=cv2.INTER_LINEAR)


# ── Write worker (thread pool) ────────────────────────────────────────────────

def _write_jpg(path, img):
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 95])


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src",     required=True, help="Case_XX root (contains camera0/, calibration/)")
    parser.add_argument("--dst",     required=True, help="nuScenes scene root (scene-CATS-01)")
    parser.add_argument("--t_start", type=float, default=10.0)
    parser.add_argument("--log_id",  default="cats001-2026-04-28-15-30-0500")
    args = parser.parse_args()

    calib_dir  = os.path.join(args.src, "calibration")
    new_K_all  = {}

    executor = ThreadPoolExecutor(max_workers=16)

    for cam_name, sensor_name, target_frac in CAMERAS:
        src_folder = os.path.join(args.src, cam_name)
        dst_folder = os.path.join(args.dst, sensor_name)
        os.makedirs(dst_folder, exist_ok=True)

        frames = select_frames(src_folder, args.t_start, target_frac)
        if not frames:
            print(f"[skip] {cam_name}: no frames found")
            continue

        print(f"\n{cam_name} → {sensor_name}  ({len(frames)} frames)")

        # Load calibration and precompute undistort maps from first frame
        K, D = load_calib(calib_dir, cam_name)
        first_img = cv2.imread(frames[0][1])
        map1, map2, new_K = compute_undistort_maps(K, D, first_img.shape[:2])

        new_K_all[sensor_name] = {
            "fx": float(new_K[0, 0]),
            "fy": float(new_K[1, 1]),
            "cx": float(new_K[0, 2]),
            "cy": float(new_K[1, 2]),
            "camera_intrinsic": new_K.tolist(),
        }

        print(f"  K original:     fx={K[0,0]:.1f}  cx={K[0,2]:.1f}  cy={K[1,2]:.1f}")
        print(f"  K undistorted:  fx={new_K[0,0]:.1f}  cx={new_K[0,2]:.1f}  cy={new_K[1,2]:.1f}")

        futures = []
        for t, src_path in tqdm(frames, desc=sensor_name, unit="img"):
            img = cv2.imread(src_path)
            if img is None:
                print(f"  [warn] failed to read {src_path}")
                continue
            und = undistort_frame(img, map1, map2)
            ts_us   = int(t * 1e6)
            filename = f"{args.log_id}__{sensor_name}__{ts_us}.jpg"
            dst_path = os.path.join(dst_folder, filename)
            futures.append(executor.submit(_write_jpg, dst_path, und))

        for fut in futures:
            fut.result()

    executor.shutdown()

    # Save new K matrices
    calib_out = os.path.join(args.dst, "calibration")
    os.makedirs(calib_out, exist_ok=True)
    k_path = os.path.join(calib_out, "undistorted_intrinsics.json")
    with open(k_path, "w") as f:
        json.dump(new_K_all, f, indent=2)
    print(f"\nNew K matrices saved → {k_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
