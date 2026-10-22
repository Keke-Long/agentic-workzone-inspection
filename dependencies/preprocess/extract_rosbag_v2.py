"""
extract_rosbag_v2.py  —  4-bag layout (20260424+)

Bag layout (new):
  RecordBlk1_<time>  →  /camera0/image_raw
  RecordBlk2_<time>  →  /camera1/image_raw  +  GNSS/IMU
  RecordBlk3_<time>  →  /rslidar_points_rs128
  RecordBlk4_<time>  →  /camera4~7/image_raw

Run:
  source /home/bcao44/miniforge3/envs/ros2/setup.bash
  source /home/bcao44/ros2_ws/install/setup.bash
  python3 extract_rosbag_v2.py \
      --time 20260424_170459 \
      --src  /home/data/workzone/workzone_data/raw_bags \
      --dst  /home/data/workzone/workzone_data/20260424_170459
"""

import os
import cv2
import csv
import numpy as np
import argparse

import rosbag2_py
from cv_bridge import CvBridge
from pypcd4 import PointCloud
from sensor_msgs_py.point_cloud2 import read_points
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

# ======================================
# Config
# ======================================

parser = argparse.ArgumentParser()
parser.add_argument("--time", type=str, required=True, help="YYYYMMDD_HHMMSS")
parser.add_argument("--src",  type=str, required=True, help="Raw bags root folder")
parser.add_argument("--dst",  type=str, required=True, help="Output folder")
args = parser.parse_args()

TIME         = args.time
INPUT_ROOT   = args.src
OUTPUT_ROOT  = args.dst

# cameras that need 180° flip + top-2-row crop (physically mounted upside-down)
FLIP_CAMERAS = {"camera0", "camera1", "camera2"}

BAGS = {
    "RecordBlk1": f"{INPUT_ROOT}/RecordBlk1_{TIME}",
    "RecordBlk2": f"{INPUT_ROOT}/RecordBlk2_{TIME}",
    "RecordBlk3": f"{INPUT_ROOT}/RecordBlk3_{TIME}",
    "RecordBlk4": f"{INPUT_ROOT}/RecordBlk4_{TIME}",
}

# topics extracted from each bag
ALLOWED_TOPICS = {
    "RecordBlk1": {"/camera0/image_raw"},
    "RecordBlk2": {"/camera1/image_raw",
                   "/bynav/inspvax",
                   "/bynav/imu/data_raw",
                   "/bynav/corrimudata"},
    "RecordBlk3": {"/rslidar_points_rs128",
                   "/camera2/image_raw"},
    "RecordBlk4": {"/camera4/image_raw",
                   "/camera5/image_raw",
                   "/camera6/image_raw",
                   "/camera7/image_raw"},
}

TOPIC_TO_DIR = {
    "/camera0/image_raw":      "camera0",
    "/camera1/image_raw":      "camera1",
    "/camera2/image_raw":      "camera2",
    "/camera4/image_raw":      "camera4",
    "/camera5/image_raw":      "camera5",
    "/camera6/image_raw":      "camera6",
    "/camera7/image_raw":      "camera7",
    "/rslidar_points_rs128":   "lidar",
    "/bynav/imu/data_raw":     "imu_raw",
    "/bynav/inspvax":          "gnss",
    "/bynav/corrimudata":      "imu_corrected",
}

POINT_FIELD_DATATYPES = {
    1: np.int8, 2: np.uint8, 3: np.int16, 4: np.uint16,
    5: np.int32, 6: np.uint32, 7: np.float32, 8: np.float64,
}

bridge   = CvBridge()
executor = ThreadPoolExecutor(max_workers=64)

# ======================================
# Helpers
# ======================================

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def timestamp_str(msg, base_sec):
    rel_sec = msg.header.stamp.sec - base_sec
    return f"{rel_sec}.{msg.header.stamp.nanosec:09d}"


# ── Thread-pool workers: pure disk I/O only, no ROS msg access ────────────────

def _write_image(path, img):
    if not cv2.imwrite(path, img):
        print(f"[warn] imwrite failed: {path}")


def _write_pcd(path, pts, field_names, field_types):
    pc = PointCloud.from_points(pts, tuple(field_names), tuple(field_types))
    pc.save(path)


# ── Main-thread decoders: extract all data from msg before submitting ─────────

def decode_image(msg, cam_name, base_sec):
    """Decode ROS Image msg → (numpy_array, timestamp_str) in main thread."""
    img = bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
    if cam_name in FLIP_CAMERAS:
        img = cv2.flip(img, -1)[:-2, :]
    return np.ascontiguousarray(img), timestamp_str(msg, base_sec)


def decode_pointcloud(msg, base_sec):
    """Decode ROS PointCloud2 msg → (pts, field_names, field_types, ts_str).
    Called in the main thread so the msg buffer is still valid."""
    field_names = [f.name for f in msg.fields]
    field_types = [POINT_FIELD_DATATYPES.get(f.datatype, np.float32) for f in msg.fields]

    pts_struct = np.array(list(read_points(msg, field_names=field_names, skip_nans=True)))
    if pts_struct.size == 0:
        return None, None, None, None

    pts = np.stack([pts_struct[n].astype(np.float64) for n in field_names], axis=-1)

    if "timestamp" in field_names:
        idx = field_names.index("timestamp")
        pts[:, idx] -= base_sec

    return pts, field_names, field_types, timestamp_str(msg, base_sec)


def flatten_field(prefix, value):
    flat = {}
    if hasattr(value, "__slots__"):
        for attr in value.__slots__:
            flat.update(flatten_field(f"{prefix}{attr}.", getattr(value, attr)))
    elif isinstance(value, (list, tuple, np.ndarray)):
        for i, v in enumerate(value):
            flat[f"{prefix}{i}"] = v
    else:
        if isinstance(value, int) and "nanosec" in prefix:
            flat[prefix[:-1]] = f"{value:09d}"
        else:
            if isinstance(value, (np.generic, np.ndarray)):
                value = np.array(value).item() if np.array(value).size == 1 else value.tolist()
            flat[prefix[:-1]] = value
    return flat


def flatten_msg(msg):
    flat = {}
    for attr in msg.__slots__:
        flat.update(flatten_field(f"{attr}.", getattr(msg, attr)))
    return flat


def write_csv_header(csv_path, msg):
    ensure_dir(os.path.dirname(csv_path))
    with open(csv_path, "w", newline="") as f:
        csv.writer(f).writerow(flatten_msg(msg).keys())


def append_ins_row(msg, csv_path, base_sec):
    flat = flatten_msg(msg)
    if "_header._stamp._sec" in flat:
        flat["_header._stamp._sec"] = msg.header.stamp.sec - base_sec
    with open(csv_path, "a", newline="") as f:
        csv.writer(f).writerow(flat.values())


def open_reader(bag_dir):
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=bag_dir, storage_id="mcap"),
        rosbag2_py.ConverterOptions(
            input_serialization_format="cdr",
            output_serialization_format="cdr"),
    )
    return reader

# ======================================
# Step 1: Determine unified base_sec from Blk2
# ======================================

def find_gnss_base_sec(blk2_dir):
    """Scan Blk2 for the first GNSS (inspvax) message; base_sec = stamp.sec - 1.
    Used for LiDAR and INS — both on GPS-synchronized clock."""
    reader  = open_reader(blk2_dir)
    typemap = {t.name: t.type for t in reader.get_all_topics_and_types()}
    while reader.has_next():
        topic, data, _ = reader.read_next()
        if "inspvax" not in topic:
            continue
        msg_type = typemap.get(topic)
        if not msg_type:
            continue
        try:
            msg = deserialize_message(data, get_message(msg_type))
            base = msg.header.stamp.sec - 1
            print(f"[gnss_base_sec] {base}  "
                  f"(first inspvax: {msg.header.stamp.sec}.{msg.header.stamp.nanosec:09d})")
            return base
        except Exception:
            continue
    raise RuntimeError("No inspvax found in RecordBlk2 — cannot determine gnss_base_sec")


blk2_dir = BAGS["RecordBlk2"]
if not os.path.exists(blk2_dir):
    raise FileNotFoundError(f"RecordBlk2 not found: {blk2_dir}")

gnss_base_sec = find_gnss_base_sec(blk2_dir)

# ======================================
# Step 2: Extract each bag
# ======================================

for blk_key, bag_dir in BAGS.items():
    if not os.path.exists(bag_dir):
        print(f"[skip] {blk_key} not found: {bag_dir}")
        continue

    allowed = ALLOWED_TOPICS[blk_key]
    print(f"\n▶ {blk_key}  ({bag_dir})")

    reader   = open_reader(bag_dir)
    typemap  = {t.name: t.type for t in reader.get_all_topics_and_types()}
    total    = reader.get_metadata().message_count
    pbar     = tqdm(total=total, desc=blk_key, unit="msg")
    futures  = []

    img_count = pc_count = ins_count = 0

    while reader.has_next():
        topic, data, _ = reader.read_next()
        pbar.update(1)

        if topic not in allowed:
            continue

        out_dir  = TOPIC_TO_DIR.get(topic)
        msg_type = typemap.get(topic)
        if out_dir is None or msg_type is None:
            continue

        try:
            msg = deserialize_message(data, get_message(msg_type))

            # ── GNSS / IMU ─────────────────────────────────────
            if "bynav" in topic:
                csv_path = os.path.join(OUTPUT_ROOT, "ins", f"{out_dir}.csv")
                ensure_dir(os.path.dirname(csv_path))
                if not os.path.exists(csv_path):
                    write_csv_header(csv_path, msg)
                append_ins_row(msg, csv_path, gnss_base_sec)
                ins_count += 1

            # ── Camera ─────────────────────────────────────────
            elif "sensor_msgs/msg/Image" in msg_type:
                folder = os.path.join(OUTPUT_ROOT, out_dir)
                ensure_dir(folder)
                img, ts = decode_image(msg, out_dir, gnss_base_sec)
                path = os.path.join(folder, f"{ts}.png")
                futures.append(executor.submit(_write_image, path, img))
                img_count += 1

            # ── LiDAR ──────────────────────────────────────────
            elif "sensor_msgs/msg/PointCloud2" in msg_type:
                folder = os.path.join(OUTPUT_ROOT, out_dir)
                ensure_dir(folder)
                pts, fnames, ftypes, ts = decode_pointcloud(msg, gnss_base_sec)  # GPS clock
                if pts is not None:
                    path = os.path.join(folder, f"{ts}.pcd")
                    futures.append(executor.submit(_write_pcd, path, pts, fnames, ftypes))
                    pc_count += 1

        except Exception as e:
            print(f"[warn] {topic}: {e}")

    pbar.close()
    for fut in tqdm(futures, desc=f"{blk_key} flush", unit="file"):
        try:
            fut.result()
        except Exception as e:
            print(f"[error] {e}")

    print(f"  images: {img_count}  |  pointclouds: {pc_count}  |  ins: {ins_count}")

print("\n✅ Extraction complete.")

# ======================================
# Step 3: ENU coordinates + yaw → gnss.csv
# ======================================

from pyproj import Transformer

ins_path = os.path.join(OUTPUT_ROOT, "ins", "gnss.csv")
if not os.path.exists(ins_path):
    print("[skip] gnss.csv not found, skipping ENU conversion")
else:
    ins = pd.read_csv(ins_path)

    anchor_lat = ins["_latitude"].iloc[0]
    anchor_lon = ins["_longitude"].iloc[0]
    anchor_hgt = ins["_height"].iloc[0]

    pipeline = (
        f"+proj=pipeline "
        f"+step +proj=longlat +datum=WGS84 +type=crs "
        f"+step +proj=cart +datum=WGS84 "
        f"+step +proj=topocentric +lat_0={anchor_lat} +lon_0={anchor_lon} +h_0={anchor_hgt}"
    )
    tf = Transformer.from_pipeline(pipeline)
    east, north, up = tf.transform(
        ins["_longitude"].to_numpy(),
        ins["_latitude"].to_numpy(),
        ins["_height"].to_numpy(),
    )

    ins["_east_x_from_longitude"]  = east  - east[0]
    ins["_north_y_from_latitude"]  = north - north[0]
    ins["_up_z_from_height"]       = up    - up[0]

    azimuth = ins["_azimuth"].to_numpy()
    ins["_yaw_from_azimuth"] = (90.0 - azimuth + 180.0) % 360.0 - 180.0

    # reorder: yaw after azimuth, ENU at end
    cols = list(ins.columns)
    if "_azimuth" in cols:
        az_idx = cols.index("_azimuth")
        cols.insert(az_idx + 1, cols.pop(cols.index("_yaw_from_azimuth")))
    for c in ["_east_x_from_longitude", "_north_y_from_latitude", "_up_z_from_height"]:
        if c in cols:
            cols.remove(c)
    cols += ["_east_x_from_longitude", "_north_y_from_latitude", "_up_z_from_height"]

    ins[cols].to_csv(ins_path, index=False)
    print(f"✅ ENU + yaw written to {ins_path}")
