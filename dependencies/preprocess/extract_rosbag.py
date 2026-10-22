import os
import cv2
import csv
import numpy as np

import rosbag2_py
from cv_bridge import CvBridge
from pypcd4 import PointCloud
from sensor_msgs_py.point_cloud2 import read_points
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

bridge = CvBridge()

# ======================================
# Config
# ======================================
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--time', type=str, required=True, help="Time in format YYYYMMDD_HHMMSS")
parser.add_argument('--src', type=str, required=True, help="Source folder")
parser.add_argument('--dst', type=str, required=True, help="Destination folder")
args = parser.parse_args()
time = args.time
input_root = args.src
output_root = args.dst

executor = ThreadPoolExecutor(max_workers=64)

cars = {
    "black": [
        f"{input_root}/RecordBlk1_{time}",
        f"{input_root}/RecordBlk2_{time}",
    ]
}

ALLOWED_TOPICS_BY_BAGKEY = {
    "RecordBlk1": ["/camera0/image_raw"],
    "RecordBlk2": [
        "/rslidar_points_rs128",
        "/bynav/inspvax",
        "/bynav/imu/data_raw",
        "/bynav/corrimudata",
    ],
}

COMMON_TOPIC_TO_DIR = {
    "/camera0/image_raw": "camera0",
    "/rslidar_points_rs128": "lidar",
    "/bynav/imu/data_raw": "imu_raw",
    "/bynav/inspvax": "gnss",
    "/bynav/corrimudata": "imu_corrected",
}

POINT_FIELD_DATATYPES = {
    1: np.int8,
    2: np.uint8,
    3: np.int16,
    4: np.uint16,
    5: np.int32,
    6: np.uint32,
    7: np.float32,
    8: np.float64,
}

# ======================================
# Tool functions
# ======================================

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def timestamp_rel_str(msg, base_sec):
    """仅以秒为基准归一化，不处理纳秒"""
    rel_sec = msg.header.stamp.sec - base_sec
    return f"{rel_sec}.{msg.header.stamp.nanosec:09d}"

def save_image_msg(msg, folder, car_name, topic, base_sec):
    cv_img = bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
    if car_name.lower() == "black" and COMMON_TOPIC_TO_DIR.get(topic) == "camera0":
        cv_img = cv2.flip(cv_img, -1)
        cv_img = cv_img[:-2, :]
    filename = f"{timestamp_rel_str(msg, base_sec)}.png"
    cv2.imwrite(os.path.join(folder, filename), cv_img)

def save_pointcloud_msg(msg, folder, base_sec):
    field_names = [f.name for f in msg.fields]
    field_types = [POINT_FIELD_DATATYPES.get(f.datatype, np.float32) for f in msg.fields]

    points_struct = np.array(list(read_points(msg, field_names=field_names, skip_nans=True)))
    if points_struct.size == 0:
        return

    points = np.stack([points_struct[name].astype(np.float64) for name in field_names], axis=-1)

    # === timestamp 匿名化：统一起点为 base_sec（INS 起点）===
    if "timestamp" in field_names:
        idx = field_names.index("timestamp")
        points[:, idx] = points[:, idx] - base_sec

    pc = PointCloud.from_points(points, tuple(field_names), tuple(field_types))

    filename = f"{timestamp_rel_str(msg, base_sec)}.pcd"
    pcd_path = os.path.join(folder, filename)
    pc.save(pcd_path)

def flatten_field(prefix, value):
    flat = {}
    if hasattr(value, "__slots__"):
        for attr in value.__slots__:
            flat.update(flatten_field(f"{prefix}{attr}.", getattr(value, attr)))
    elif isinstance(value, (list, tuple, np.ndarray)):
        for i, v in enumerate(value):
            flat[f"{prefix}{i}"] = v
    else:
        # 特殊处理 nanosec
        if isinstance(value, int) and "nanosec" in prefix:
            flat[prefix[:-1]] = f"{value:09d}"  # 固定9位整数，补前导0
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

def write_header_from_msg(csv_path, msg):
    ensure_dir(os.path.dirname(csv_path))
    flat = flatten_msg(msg)
    # 不再额外加 _t_rel_sec
    with open(csv_path, "w", newline="") as f:
        csv.writer(f).writerow(flat.keys())

def append_ins_msg(msg, csv_path, base_sec):
    flat = flatten_msg(msg)
    # 直接修改 _header._stamp._sec 为相对秒
    if "_header._stamp._sec" in flat:
        flat["_header._stamp._sec"] = msg.header.stamp.sec - base_sec
    with open(csv_path, "a", newline="") as f:
        csv.writer(f).writerow(flat.values())

# ======================================
# Main
# ======================================

def find_base_sec_from_blk2(bag_dirs):
    """预扫描 RecordBlk2，返回统一 base_sec = 第一条有 header 的消息秒数 - 1。
    Camera 和 LiDAR+INS 共用此基准，保证三者时间轴一致。"""
    for rosbag_dir in bag_dirs:
        if "RecordBlk2" not in rosbag_dir or not os.path.exists(rosbag_dir):
            continue
        storage_options   = rosbag2_py.StorageOptions(uri=rosbag_dir, storage_id="mcap")
        converter_options = rosbag2_py.ConverterOptions(
            input_serialization_format="cdr", output_serialization_format="cdr")
        reader = rosbag2_py.SequentialReader()
        reader.open(storage_options, converter_options)
        type_map = {t.name: t.type for t in reader.get_all_topics_and_types()}
        while reader.has_next():
            topic, data, _ = reader.read_next()
            msg_type = type_map.get(topic)
            if not msg_type:
                continue
            try:
                msg_cls = get_message(msg_type)
                msg = deserialize_message(data, msg_cls)
                if hasattr(msg, "header"):
                    base_sec = msg.header.stamp.sec - 1
                    print(f"🕒 Unified base_sec = {base_sec}  "
                          f"(from RecordBlk2 first header at {msg.header.stamp.sec}.{msg.header.stamp.nanosec:09d})")
                    return base_sec
            except Exception:
                continue
    raise RuntimeError("未能从 RecordBlk2 中找到有效 header，无法确定 base_sec")


for car_name, bag_dirs in cars.items():
    print(f"\n🚗 Processing car: {car_name}")

    # 统一 base_sec：由 RecordBlk2 第一条 header 决定，Camera 也用同一基准
    shared_base_sec = find_base_sec_from_blk2(bag_dirs)

    for rosbag_dir in bag_dirs:
        if not os.path.exists(rosbag_dir):
            print(f"⏭️  Skip (not found): {rosbag_dir}")
            continue

        bagkey = "RecordBlk1" if "RecordBlk1" in rosbag_dir else ("RecordBlk2" if "RecordBlk2" in rosbag_dir else None)
        if bagkey is None:
            print(f"⏭️  Skip (unknown bag type): {rosbag_dir}")
            continue
        allowed_topics = set(ALLOWED_TOPICS_BY_BAGKEY[bagkey])

        print(f"\n▶ {rosbag_dir}")
        futures = []
        reader = rosbag2_py.SequentialReader()
        storage_options = rosbag2_py.StorageOptions(uri=rosbag_dir, storage_id="mcap")
        converter_options = rosbag2_py.ConverterOptions(input_serialization_format="cdr", output_serialization_format="cdr")
        reader.open(storage_options, converter_options)
        total_messages = reader.get_metadata().message_count
        pbar = tqdm(desc=f"Processing {rosbag_dir}", unit="msg", total=total_messages)

        topic_types = reader.get_all_topics_and_types()
        type_map = {t.name: t.type for t in topic_types}

        image_count = 0
        pointcloud_count = 0
        ins_count = 0
        base_sec = shared_base_sec  # 所有 bag 共用同一基准

        while reader.has_next():
            topic, data, t = reader.read_next()
            pbar.update(1)
            if topic not in allowed_topics:
                continue

            out_subdir = COMMON_TOPIC_TO_DIR.get(topic)
            if out_subdir is None:
                continue
            if "bynav" not in topic:
                folder = os.path.join(output_root, out_subdir)
                ensure_dir(folder)
            else:
                folder = None  # 明确无文件夹

            msg_type = type_map.get(topic)
            if not msg_type:
                continue

            try:
                msg_cls = get_message(msg_type)
                msg = deserialize_message(data, msg_cls)

                if base_sec is None:
                    continue

                if "bynav" in topic:
                    ins_csv_path = os.path.join(output_root, "ins", f"{COMMON_TOPIC_TO_DIR[topic]}.csv")
                    ensure_dir(os.path.dirname(ins_csv_path))
                    if not os.path.exists(ins_csv_path):
                        write_header_from_msg(ins_csv_path, msg)
                    append_ins_msg(msg, ins_csv_path, base_sec)
                    ins_count += 1

                elif "sensor_msgs/msg/Image" in msg_type:
                    futures.append(executor.submit(save_image_msg, msg, folder, car_name, topic, base_sec))
                    image_count += 1

                elif "sensor_msgs/msg/PointCloud2" in msg_type:
                    futures.append(executor.submit(save_pointcloud_msg, msg, folder, base_sec))
                    pointcloud_count += 1

            except Exception as e:
                print(f"[Warning] Failed to process {topic}: {e}")

        pbar.close()
        for f in tqdm(futures, desc="Waiting for threads"):
            f.result()

        print(f"\nSummary for {car_name} - {rosbag_dir}:")
        print(f"   - Images:      {image_count}")
        print(f"   - PointClouds: {pointcloud_count}")
        print(f"   - INS msgs:    {ins_count}")

print("\n✅ Extracted all messages with sec-based normalized timestamps (t=0 at first header.sec).")


from pyproj import Transformer
import pandas as pd
import numpy as np

def make_enu_transformer(anchor_lat, anchor_lon, anchor_hgt):
    pipeline = (
        f"+proj=pipeline "
        f"+step +proj=longlat +datum=WGS84 +type=crs "
        f"+step +proj=cart +datum=WGS84 "
        f"+step +proj=topocentric +lat_0={anchor_lat} +lon_0={anchor_lon} +h_0={anchor_hgt}"
    )
    return Transformer.from_pipeline(pipeline)

# === 读取数据 ===
ins_path = os.path.join(output_root, "ins", "gnss.csv")
ins = pd.read_csv(ins_path)

# === 经纬高 → ENU ===
anchor_lat = ins["_latitude"].iloc[0]
anchor_lon = ins["_longitude"].iloc[0]
anchor_hgt = ins["_height"].iloc[0]

llh2enu = make_enu_transformer(anchor_lat, anchor_lon, anchor_hgt)
east, north, up = llh2enu.transform(
    ins["_longitude"].to_numpy(),
    ins["_latitude"].to_numpy(),
    ins["_height"].to_numpy()
)

ins["_east_x_from_longitude"] = east - east[0]
ins["_north_y_from_latitude"] = north - north[0]
ins["_up_z_from_height"] = up - up[0]

# === 姿态角 azimuth → yaw ===
azimuth = ins["_azimuth"].to_numpy()
yaw = (90.0 - azimuth + 180.0) % 360.0 - 180.0
ins["_yaw_from_azimuth"] = yaw

# === 列顺序调整 ===
cols = list(ins.columns)

# 找出 azimuth 所在位置
if "_azimuth" in cols:
    az_idx = cols.index("_azimuth")
    # 把 yaw 插入在 azimuth 后面
    cols.insert(az_idx + 1, cols.pop(cols.index("_yaw_from_azimuth")))

# 把 ENU 三列放到最后
enu_cols = ["_east_x_from_longitude", "_north_y_from_latitude", "_up_z_from_height"]
for c in enu_cols:
    if c in cols:
        cols.remove(c)
cols += enu_cols

# 重新排列列顺序
ins = ins[cols]

# === 保存 ===
ins.to_csv(ins_path, index=False)
print("✅ ENU 坐标与 yaw 已添加并保存回原文件 gnss.csv")