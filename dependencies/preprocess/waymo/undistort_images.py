import os
import cv2
import json
import numpy as np
from pathlib import Path
import argparse
import math
from decimal import Decimal

def parse_args():
    parser = argparse.ArgumentParser(
        description="Undistort images (rational_polynomial) and save without black borders."
    )
    parser.add_argument("--base_dir", type=str, required=True,
                        help='Base dir, e.g. "/home/data/workzone/workzone_data_processed"')
    parser.add_argument("--output_dir", type=str, required=True,
                        help='Output dir, e.g. "/home/data/workzone/workzone_dataset/undistort_images"')
    parser.add_argument("--camera", type=str, default="camera0",
                        help='Camera folder name (default: "camera0")')
    parser.add_argument("--calib", type=str, default="/home/data/workzone/Calibration/calib_black_camera0.json",
                        help='Relative path to calibration JSON (default: /home/data/workzone/Calibration/calib_black_camera0.json)')
    parser.add_argument("--interval", type=float, default=0.1,
                        help="Sampling interval in seconds (default: 0.1)")
    parser.add_argument("--start_prefix", type=str, default="0.9999",
                        help='采样起始时间（默认从 0.9999 开始），单位秒，小数点后四位')
    parser.add_argument("--dist_order", type=str, default="opencv",
                        choices=["opencv", "k123456_p1p2"],
                        help='Distortion coeff order: "opencv"=[k1,k2,p1,p2,k3,k4,k5,k6] '
                             'or "k123456_p1p2"=[k1,k2,k3,k4,k5,k6,p1,p2]')
    parser.add_argument("--no_undistort", action="store_true",
                        help="Skip undistortion and just copy the selected raw images.")
    return parser.parse_args()

def reorder_dist(dist_raw, order):
    d = np.array(dist_raw, dtype=np.float64).reshape(-1)
    if d.size != 8:
        raise ValueError(f"Expect 8 distortion coeffs for rational model, got {d.size}")
    if order == "opencv":
        return d
    else:
        k1, k2, k3, k4, k5, k6, p1, p2 = d.tolist()
        return np.array([k1, k2, p1, p2, k3, k4, k5, k6], dtype=np.float64)

def trunc4_to_int(t: float) -> int:
    # 保留到小数点后4位并转换为整数单位（1e-4 s）
    return int(math.floor(t * 10000.0 + 1e-9))

def main():
    args = parse_args()

    base_dir = Path(args.base_dir)
    camera_dir = base_dir / args.camera
    calib_path = base_dir / args.calib
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # === Load calibration ===
    with open(calib_path, "r") as f:
        calib_all = json.load(f)
    key = "black_camera0" if "black_camera0" in calib_all else list(calib_all.keys())[0]
    calib = calib_all[key]

    if calib.get("camera_model", "").lower() != "rational_polynomial":
        print(f'⚠️ 警告：camera_model="{calib.get("camera_model")}", 不是 "rational_polynomial"。按 rational 处理。')

    fx, fy, cx, cy = calib["intrinsics"]
    K = np.array([[fx, 0, cx],
                  [0, fy, cy],
                  [0,  0,  1]], dtype=np.float64)

    dist = reorder_dist(calib["distortion_coeffs"], args.dist_order)

    # === Collect images ===
    imgs = sorted(camera_dir.glob("*.jpg")) + sorted(camera_dir.glob("*.png"))
    if not imgs:
        raise FileNotFoundError(f"未在 {camera_dir} 找到图像文件。")

    timestamps = [float(p.stem) for p in imgs]
    imgs = [p for _, p in sorted(zip(timestamps, imgs))]
    timestamps = [float(p.stem) for p in imgs]  # re-derive after numeric sort

    # === 将所有图像按时间戳截断映射为整数单位（1e-4 秒）
    key_to_path = {}
    keys_int = []
    for t, path in zip(timestamps, imgs):
        k = trunc4_to_int(t)
        if k not in key_to_path:
            key_to_path[k] = path
            keys_int.append(k)

    if not keys_int:
        raise RuntimeError("没有可用时间戳。")

    keys_int = sorted(keys_int)
    max_k = keys_int[-1]
    step = int(round(args.interval * 10000))  # interval 转整数单位

    # 起始时间：默认从 0.9999 开始
    base_k = int(Decimal(args.start_prefix) * 10000)

    targets = list(range(base_k, max_k + 1, step))
    selected = [key_to_path[k] for k in targets if k in key_to_path]

    print(f"将处理 {len(selected)} 张图像（从 {args.start_prefix}s 开始，每隔 {args.interval}s 采样）。")

    # === 处理并保存 ===
    map1 = map2 = None
    cache_size = None

    for idx, img_path in enumerate(selected):
        print(f"[{idx:03d}] {img_path}")

        subdir = output_dir / f"{idx:03d}"
        subdir.mkdir(parents=True, exist_ok=True)
        out_path = subdir / "Front.jpg"

        if args.no_undistort:
            import shutil
            shutil.copy2(str(img_path), str(out_path))
            print(f"✅ 复制：{out_path}")
            continue

        img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
        if img is None:
            print(f"⚠️ 无法读取图像：{img_path}")
            continue

        h, w = img.shape[:2]
        if cache_size != (w, h):
            newK, roi = cv2.getOptimalNewCameraMatrix(K, dist, (w, h), alpha=0)
            map1, map2 = cv2.initUndistortRectifyMap(
                K, dist, R=None, newCameraMatrix=newK, size=(w, h), m1type=cv2.CV_16SC2
            )
            cache_size = (w, h)
            roi_cached = roi

        undist = cv2.remap(img, map1, map2, interpolation=cv2.INTER_LINEAR)
        x, y, ww, hh = roi_cached
        undist = undist[y:y+hh, x:x+ww]

        ok = cv2.imwrite(str(out_path), undist)
        if ok:
            print(f"✅ 保存：{out_path}")
        else:
            print(f"❌ 写入失败：{out_path}")

    print("完成。输出目录：", output_dir)

if __name__ == "__main__":
    main()
