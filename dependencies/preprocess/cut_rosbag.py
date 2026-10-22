#!/usr/bin/env python3
import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message
import math, argparse, os

def get_header_time(msg):
    if hasattr(msg, "header"):
        return msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
    return None

def safe_get_message(type_name):
    try:
        return get_message(type_name)
    except Exception:
        return None

def safe_deserialize(data, msg_type):
    if msg_type is None:
        return None
    try:
        return deserialize_message(data, msg_type)
    except Exception:
        return None


# -------------------- RecordBlk1 对齐逻辑 --------------------
def handle_blk1(reader, msg_type_cache, ref_topic):
    first_header = None
    # 找第一条 header
    while reader.has_next():
        topic, data, t = reader.read_next()
        if topic != ref_topic:
            continue
        msg = safe_deserialize(data, msg_type_cache[topic])
        if msg is None:
            continue
        h = get_header_time(msg)
        if h is not None:
            first_header = h
            break

    if first_header is None:
        raise RuntimeError("未找到 RecordBlk1 的首帧 header")

    target_sec = math.ceil(first_header)
    last_before = None

    # 再找最后一个 < ceil 的帧
    reader.seek(0)
    while reader.has_next():
        topic, data, t = reader.read_next()
        if topic != ref_topic:
            continue
        msg = safe_deserialize(data, msg_type_cache[topic])
        if msg is None:
            continue
        h = get_header_time(msg)
        if h is None:
            continue
        if h < target_sec:
            last_before = h
        else:
            break

    print(f"🕒 {ref_topic} 对齐帧(header): {last_before:.9f}")
    return last_before


# -------------------- RecordBlk2 对齐逻辑 --------------------
def handle_blk2(storage_options, converter_options, msg_type_cache, ref_topics):
    """
    RecordBlk2 特殊规则：
      - /bynav/imu/data_raw  -> 取最后一个 < ceil(first_header)
      - /rslidar_points_rs128, /bynav/inspvax -> 取第一个 >= ceil(first_header)
    统一起点取三者的最小值；写出区间为 [start, start + duration + 0.008]
    """
    # 指定每个参考topic的对齐模式
    MODES = {
        "/bynav/imu/data_raw": "last_before",
        "/rslidar_points_rs128": "first_after",
        "/bynav/inspvax": "first_after",
    }

    ref_times = {}

    for topic in ref_topics:
        mode = MODES.get(topic, "first_after")

        # --- 找该topic的首个header时间 ---
        temp_reader = rosbag2_py.SequentialReader()
        temp_reader.open(storage_options, converter_options)

        first_header = None
        while temp_reader.has_next():
            tp, data, t = temp_reader.read_next()
            if tp != topic:
                continue
            msg = safe_deserialize(data, msg_type_cache.get(tp))
            if msg is None:
                continue
            h = get_header_time(msg)
            if h is not None:
                first_header = h
                break

        if first_header is None:
            print(f"⚠️ {topic} 无有效 header，跳过。")
            continue

        target_sec = math.ceil(first_header)

        # --- 根据模式选择对齐帧 ---
        temp_reader = rosbag2_py.SequentialReader()
        temp_reader.open(storage_options, converter_options)

        pick = None
        last_before = None

        while temp_reader.has_next():
            tp, data, t = temp_reader.read_next()
            if tp != topic:
                continue
            msg = safe_deserialize(data, msg_type_cache.get(tp))
            if msg is None:
                continue
            h = get_header_time(msg)
            if h is None:
                continue

            if mode == "first_after":
                if h >= target_sec:
                    pick = h
                    break
            elif mode == "last_before":
                if h < target_sec:
                    last_before = h
                else:
                    # 一旦遇到 >= 整秒，停止，取最后一个 < 整秒 的
                    pick = last_before
                    break

        # 如果是 last_before 且循环到末尾也没遇到 >= 整秒，则用最后记住的 last_before
        if pick is None and mode == "last_before":
            pick = last_before

        if pick is not None:
            ref_times[topic] = pick
            print(f"🕒 {topic} 对齐帧(header, {mode}): {pick:.9f}")
        else:
            print(f"⚠️ 未能为 {topic} 选到对齐帧（mode={mode}）")

    if not ref_times:
        raise RuntimeError("未找到任何 RecordBlk2 对齐时间")

    # ✅ 统一起点取三者“最小值”（最早）
    new_start_sec = min(ref_times.values())
    return new_start_sec

# -------------------- 主函数 --------------------
def cut_rosbag_to_next_whole_second(input_bag, output_dir, duration):
    print(f"📦 处理 {input_bag} ...")
    storage_id = "mcap"

    bag_name = os.path.basename(os.path.normpath(input_bag))
    base_output = os.path.join(output_dir, f"{bag_name}_cut")
    output_bag = base_output
    suffix = 1
    while os.path.exists(output_bag):
        output_bag = f"{base_output}_{suffix}"
        suffix += 1
    print(f"📁 输出路径: {output_bag}")

    storage_options = rosbag2_py.StorageOptions(uri=input_bag, storage_id=storage_id)
    converter_options = rosbag2_py.ConverterOptions("", "")

    reader = rosbag2_py.SequentialReader()
    reader.open(storage_options, converter_options)
    topic_types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    msg_type_cache = {name: safe_get_message(t) for name, t in topic_types.items()}

    # --- 分支逻辑 ---
    if "RecordBlk1" in bag_name:
        ref_topic = "/camera0/image_raw"
        print(f"🎯 基准 topic: {ref_topic}")
        reader_blk = rosbag2_py.SequentialReader()
        reader_blk.open(storage_options, converter_options)
        new_start_sec = handle_blk1(reader_blk, msg_type_cache, ref_topic)
        new_end_sec = new_start_sec + duration + 0.008
    elif "RecordBlk2" in bag_name:
        ref_topics = ["/rslidar_points_rs128", "/bynav/imu/data_raw", "/bynav/inspvax"]
        print(f"🎯 基准 topics: {ref_topics}")
        new_start_sec = handle_blk2(storage_options, converter_options, msg_type_cache, ref_topics)
        new_end_sec = new_start_sec + duration + 0.008
    else:
        raise RuntimeError("⚠️ 未识别数据块类型")

    print(f"⏱️ 截取区间: [{new_start_sec:.9f}, {new_end_sec:.9f}]")

       # === 写出 ===
    reader = rosbag2_py.SequentialReader()
    reader.open(storage_options, converter_options)
    writer = rosbag2_py.SequentialWriter()
    writer.open(
        rosbag2_py.StorageOptions(uri=output_bag, storage_id=storage_id),
        rosbag2_py.ConverterOptions("", "")
    )

    # ✅ 针对 RecordBlk2，仅保留指定 topic
    if "RecordBlk2" in bag_name:
        allowed_topics = ["/rslidar_points_rs128", "/bynav/imu/data_raw", "/bynav/inspvax"]
    else:
        # RecordBlk1 默认保留全部
        allowed_topics = [t.name for t in reader.get_all_topics_and_types()]

    for topic in reader.get_all_topics_and_types():
        if topic.name not in allowed_topics:
            continue
        writer.create_topic(rosbag2_py.TopicMetadata(
            name=topic.name,
            type=topic.type,
            serialization_format="cdr"
        ))

    kept_count, total_count = 0, 0
    while reader.has_next():
        topic, data, t = reader.read_next()
        total_count += 1

        if topic not in allowed_topics:
            continue

        msg = safe_deserialize(data, msg_type_cache[topic])
        h = get_header_time(msg) if msg else None
        ts = h if h else t * 1e-9

        # === 特殊处理 IMU ===
        if topic == "/bynav/imu/data_raw":
            # 🔹 开头必须 >= new_start_sec（去掉多的第一帧）
            # 🔹 末尾允许多 0.01 s（多写一帧）
            if new_start_sec <= ts <= new_end_sec + 0.008:
                writer.write(topic, data, t)
                kept_count += 1
        else:
            # 普通 topic 正常截取
            if new_start_sec <= ts <= new_end_sec:
                writer.write(topic, data, t)
                kept_count += 1

    print(f"✅ 完成 {output_bag}，保留 {kept_count}/{total_count} 条消息\n")


def main():
    parser = argparse.ArgumentParser(description="按不同规则截取 ROS2 MCAP bag")
    parser.add_argument("-s", "--src", required=True)
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("-d", "--duration", required=True, type=float)
    args = parser.parse_args()
    cut_rosbag_to_next_whole_second(args.src, args.output, args.duration)

if __name__ == "__main__":
    main()
