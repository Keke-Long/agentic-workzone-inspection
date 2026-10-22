#!/usr/bin/env python3
"""Deterministic, auditable access to CATS scene sensors and geometry."""

from __future__ import annotations

import hashlib
import csv
import json
import math
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from project_common import ROOT, load_config


DATA_ROOT = Path("/home/klong23/workzone/data/workzone_01/processed")
META_ROOT = DATA_ROOT / "CATS_v1.0"


def _rotation(q: list[float]) -> np.ndarray:
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w)],
        [2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w)],
        [2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y)],
    ], dtype=float)


def _stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:20]}"


TRAFFIC_SIGN_CLASSES = {"traffic_sign", "road_work_ahead", "merging_sign", "merge_sign",
                        "left_lane_closed", "right_lane_closed", "lane_closed",
                        "end_road_work", "road_work_end", "detour_sign"}


def matches_reviewed_class(actual, requested):
    return actual == requested or (requested == "traffic_sign" and actual in TRAFFIC_SIGN_CLASSES)


class SceneDataToolsV5:
    def __init__(self, scene_manifest: str | Path | None = None) -> None:
        self.cfg = load_config()
        self.geometry_policy = self.cfg["geometry_policy"]
        manifest_path = Path(scene_manifest) if scene_manifest is not None else Path(
            self.cfg["scene"]["active_manifest"]
        )
        if not manifest_path.is_absolute():
            manifest_path = ROOT / manifest_path
        scene = json.loads(manifest_path.read_text())
        if scene.get("schema") != "current_scene_v1" or not isinstance(scene.get("accepted_observations"), list):
            raise ValueError("active scene must be the materialized current_scene_v1 input")
        self.scene_manifest_path = manifest_path
        self.scene_record = scene
        self.scene_id = str(scene["scene_id"])
        raw_images = scene.get("raw_images", [])
        inferred_data_root = Path(raw_images[0]).parents[2] if raw_images else DATA_ROOT
        self.data_root = Path(scene.get("dataset_root", inferred_data_root))
        self.meta_root = Path(scene.get("metadata_root", self.data_root / META_ROOT.name))
        self.sensors = {row["token"]: row for row in json.loads((self.meta_root / "sensor.json").read_text())}
        self.calibrations = {row["token"]: row for row in json.loads((self.meta_root / "calibrated_sensor.json").read_text())}
        self.poses = {row["token"]: row for row in json.loads((self.meta_root / "ego_pose.json").read_text())}
        self.samples = {row["token"]: row for row in json.loads((self.meta_root / "sample.json").read_text())}
        self.sample_data = json.loads((self.meta_root / "sample_data.json").read_text())
        self.sample_data_by_filename = {Path(row["filename"]).name: row for row in self.sample_data}
        self.sample_data_by_sample: dict[str, list[dict]] = {}
        for row in self.sample_data:
            self.sample_data_by_sample.setdefault(row["sample_token"], []).append(row)
        self.channel_by_calibration = {
            token: self.sensors[row["sensor_token"]]["channel"] for token, row in self.calibrations.items()
        }
        self.rows_by_channel: dict[str, list[dict]] = {}
        for row in self.sample_data:
            self.rows_by_channel.setdefault(self.channel_by_calibration[row["calibrated_sensor_token"]], []).append(row)
        for rows in self.rows_by_channel.values():
            rows.sort(key=lambda row: row["timestamp"])
        self.confirmed_device_condition_findings = list(
            scene.get("confirmed_device_condition_findings", [])
        )
        reviewed = scene["accepted_observations"]
        self.observations = {row["observation_id"]: row for row in reviewed}
        self.pcms_observation_ids = sorted(
            row["observation_id"] for row in reviewed
            if row.get("reviewed_class", "").lower() in {
                "message_board", "pcms", "portable_changeable_message_sign"
            }
        )
        self.arrow_board_observation_ids = sorted(
            row["observation_id"] for row in reviewed
            if row.get("reviewed_class", "").lower() == "arrow_board"
        )
        self._trajectory = self._build_trajectory()
        self.measurements: dict[str, dict] = {}
        self.speed_evidence: dict[str, dict] = {}
        self.external_queries: list[dict] = []
        self.resources = {
            "point_cloud_frames_processed": 0, "points_processed": 0,
            "geometry_tool_calls": 0, "map_web_lookup_calls": 0,
            "image_files_returned": 0, "cpu_seconds": 0.0,
        }

    def _build_trajectory(self) -> list[dict]:
        output, station, previous = [], 0.0, None
        for row in self.rows_by_channel["LIDAR_TOP"]:
            pose = self.poses[row["ego_pose_token"]]
            xyz = np.array(pose["translation"], dtype=float)
            if previous is not None:
                station += float(np.linalg.norm(xyz[:2] - previous[:2]))
            output.append({
                "timestamp_us": row["timestamp"], "station_m": station,
                "translation": pose["translation"], "rotation": pose["rotation"],
                "ego_pose_token": pose["token"], "sample_data_token": row["token"],
            })
            previous = xyz
        return output

    def manifest(self) -> dict:
        scene_rows = json.loads((self.meta_root / "scene.json").read_text())
        scene_meta = next((row for row in scene_rows if row.get("name") == self.scene_id), None)
        if scene_meta is None:
            raise ValueError(f"scene {self.scene_id!r} is absent from {self.meta_root / 'scene.json'}")
        log_rows = json.loads((self.meta_root / "log.json").read_text())
        log = next((row for row in log_rows if row.get("token") == scene_meta.get("log_token")), {})
        reviewed_class_counts: dict[str, int] = defaultdict(int)
        for observation in self.observations.values():
            reviewed_class_counts[observation.get("reviewed_class", "unknown")] += 1
        return {
            "scene_id": self.scene_id,
            "scene_description_redacted": True,
            "available_direct": (
                ["accepted_bbox_observations", "scene_facts"]
                if self.observations else ["scene_facts"]
            ),
            "derivable_local": [
                "full_temporal_images", "lidar_points", "ego_trajectory", "sensor_calibration",
                "device_global_position", "longitudinal_distance", "device_spacing",
                "taper_length", "buffer_length", "sign_spacing", "available_width",
                "rule_based_channelizer_spacing_audit",
                "posted_speed_from_visible_sign",
            ],
            "retrievable_external": ["posted_speed_if_road_segment_can_be_geolocated"],
            "counts": {
                "samples": scene_meta["nbr_samples"],
                "lidar_frames": len(self.rows_by_channel.get("LIDAR_TOP", [])),
                "camera_frames": sum(len(rows) for channel, rows in self.rows_by_channel.items() if channel.startswith("CAM_")),
                "camera_frames_by_channel": {
                    channel: len(rows) for channel, rows in self.rows_by_channel.items() if channel.startswith("CAM_")
                },
                "ego_poses": len(self.poses), "calibrated_sensors": len(self.calibrations),
                "accepted_bbox_observations": len(self.observations),
                "accepted_bbox_observations_by_class": dict(sorted(reviewed_class_counts.items())),
                "accepted_pcms_observations": len(self.pcms_observation_ids),
                "accepted_arrow_board_observations": len(self.arrow_board_observation_ids),
            },
            "derived_scene_facts": {
                "pcms_deployed": True if self.pcms_observation_ids else None,
                "pcms_deployed_provenance": self.pcms_observation_ids,
                "arrow_board_deployed": True if self.arrow_board_observation_ids else None,
                "arrow_board_deployed_provenance": self.arrow_board_observation_ids,
            },
            "trajectory": {
                "start_timestamp_us": self._trajectory[0]["timestamp_us"],
                "end_timestamp_us": self._trajectory[-1]["timestamp_us"],
                "path_length_m": self._trajectory[-1]["station_m"],
            },
            "location": {
                "dataset_location": log.get("location"),
                "road_name": None, "latitude_longitude": None,
                "external_speed_lookup_ready": False,
                "reason": "Metadata identifies Madison, Wisconsin but contains no road name or geodetic coordinates.",
            },
            "forbidden_metadata_removed": ["scene.description"],
        }

    def get_scene_data_manifest(self) -> dict:
        """Public inventory-tool name used by the staged controller."""
        return self.manifest()

    def list_scene_sensors(self) -> dict:
        return {"sensors": [{
            "channel": row["channel"], "modality": row["modality"],
            "frame_count": len(self.rows_by_channel.get(row["channel"], [])),
        } for row in self.sensors.values()]}

    def get_reviewed_observations(
        self, cursor: int = 0, limit: int = 50,
        reviewed_class: str | None = None,
        representative_per_entity: bool = False,
    ) -> dict:
        rows = list(self.observations.values())
        if reviewed_class is not None:
            rows = [row for row in rows if matches_reviewed_class(row.get("reviewed_class"), reviewed_class)]
        if representative_per_entity:
            representatives: dict[str, tuple[float, dict]] = {}
            for row in rows:
                entity_id = row.get("refined_element_id") or row.get("raw_device_id") or row["observation_id"]
                width = max(0.0, float(row["bbox"][2]) - float(row["bbox"][0]))
                height = max(0.0, float(row["bbox"][3]) - float(row["bbox"][1]))
                area = width * height
                current = representatives.get(entity_id)
                if current is None or area > current[0]:
                    representatives[entity_id] = (area, row)
            rows = [value[1] for value in representatives.values()]
        rows = sorted(rows, key=lambda row: (row["frame"], row["camera"], row["observation_id"]))
        limit = min(max(int(limit), 1), 100)
        selected = rows[cursor:cursor + limit]
        return {
            "observations": selected,
            "next_cursor": cursor + limit if cursor + limit < len(rows) else None,
            "total": len(rows),
            "reviewed_class_filter": reviewed_class,
            "representative_per_entity": representative_per_entity,
            "warning": "Accepted 2D boxes establish class/box usability only, not compliance or geometry.",
        }

    def inspect_observation_images(self, observation_ids: list[str]) -> dict:
        if not observation_ids or len(observation_ids) > 12:
            return {"status": "failure", "failure_reason": "request between 1 and 12 observations"}
        unknown = [value for value in observation_ids if value not in self.observations]
        if unknown:
            return {"status": "failure", "failure_reason": f"unknown observations: {unknown}"}
        rows = [self.observations[value] for value in observation_ids]
        paths = list(dict.fromkeys(row["source_image"] for row in rows))
        self.resources["image_files_returned"] += len(paths)
        return {
            "status": "acquired", "observations": rows, "_image_paths": paths,
            "warning": "Images are supplied for model inspection; bbox acceptance is not a compliance label.",
        }

    def list_temporal_frames(self, channel: str, cursor: int = 0, limit: int = 50) -> dict:
        rows = self.rows_by_channel.get(channel, [])
        limit = min(max(int(limit), 1), 200)
        selected = rows[cursor:cursor + limit]
        return {
            "channel": channel, "cursor": cursor,
            "frames": [{"timestamp_us": row["timestamp"], "filename": row["filename"], "sample_token": row["sample_token"]} for row in selected],
            "next_cursor": cursor + limit if cursor + limit < len(rows) else None,
            "total": len(rows),
        }

    def get_vehicle_trajectory(self, cursor: int = 0, limit: int = 100) -> dict:
        limit = min(max(int(limit), 1), 250)
        selected = self._trajectory[cursor:cursor + limit]
        return {"poses": selected, "next_cursor": cursor + limit if cursor + limit < len(self._trajectory) else None,
                "total": len(self._trajectory), "station_definition": "cumulative 2D ego-pose path length"}

    def get_ego_pose(self, timestamp_us: int) -> dict:
        row = min(self._trajectory, key=lambda value: abs(value["timestamp_us"] - int(timestamp_us)))
        return {**row, "timestamp_delta_us": abs(row["timestamp_us"] - int(timestamp_us)), "source": str(self.meta_root / "ego_pose.json")}

    def get_sensor_calibration(self, channel: str) -> dict:
        rows = [row for token, row in self.calibrations.items() if self.channel_by_calibration[token] == channel]
        if not rows:
            return {"channel": channel, "failure_reason": "unknown channel"}
        row = rows[0]
        return {"channel": channel, **row, "source": str(self.meta_root / "calibrated_sensor.json")}

    def get_sensor_sync(self, observation_id: str) -> dict:
        observation = self.observations.get(observation_id)
        if not observation:
            return {"status": "failure", "failure_reason": "unknown accepted observation_id"}
        camera = self.sample_data_by_filename.get(Path(observation["source_image"]).name)
        if not camera:
            return {"status": "failure", "failure_reason": "camera image absent from sample_data"}
        synchronized = self.sample_data_by_sample.get(camera["sample_token"], [])
        return {
            "status": "acquired", "observation_id": observation_id,
            "sample_token": camera["sample_token"], "camera_timestamp_us": camera["timestamp"],
            "synchronized_sensors": [{
                "channel": self.channel_by_calibration[row["calibrated_sensor_token"]],
                "timestamp_us": row["timestamp"], "timestamp_delta_us": row["timestamp"] - camera["timestamp"],
                "filename": row["filename"], "sample_data_token": row["token"],
            } for row in synchronized],
            "source": str(self.meta_root / "sample_data.json"),
        }

    def inspect_temporal_images(self, channel: str, start_cursor: int, count: int, stride: int = 1) -> dict:
        rows = self.rows_by_channel.get(channel, [])
        count, stride = min(max(int(count), 1), 12), max(int(stride), 1)
        selected = rows[start_cursor:start_cursor + count * stride:stride]
        paths = [str(self.data_root / row["filename"]) for row in selected]
        self.resources["image_files_returned"] += len(paths)
        return {
            "channel": channel,
            "images": [{"image_id": Path(path).stem, "timestamp_us": row["timestamp"], "path": path} for path, row in zip(paths, selected)],
            "_image_paths": paths,
        }

    def search_speed_limit_signs(self, cursor: int = 0, limit: int = 20) -> dict:
        candidates = [row for row in self.observations.values() if row.get("reviewed_class") == "traffic_sign"]
        limit = min(max(int(limit), 1), 20)
        selected = sorted(candidates, key=lambda row: (row["frame"], row["camera"]))[cursor:cursor + limit]
        return {
            "candidates": [{k: row[k] for k in ("observation_id", "frame", "camera", "bbox", "source_image")} for row in selected],
            "warning": "Candidate class is traffic_sign only; the Agent must inspect the crop/image before asserting a speed.",
            "next_cursor": cursor + limit if cursor + limit < len(candidates) else None,
            "total": len(candidates),
        }

    def locate_road_segment(self) -> dict:
        self.resources["map_web_lookup_calls"] += 1
        result = {
            "status": "unavailable_after_attempt", "dataset_location": "madison-wi-usa",
            "road_name": None, "latitude_longitude": None,
            "failure_reason": "ego_pose uses a local Cartesian frame and metadata has no geodetic transform or road name",
            "sources_checked": [str(self.meta_root / "log.json"), str(self.meta_root / "map.json"), str(self.meta_root / "ego_pose.json")],
            "query_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.external_queries.append({"tool": "locate_road_segment", "request": {}, "response": result})
        return result

    def lookup_posted_speed(self, road_name: str | None = None, latitude: float | None = None, longitude: float | None = None) -> dict:
        self.resources["map_web_lookup_calls"] += 1
        if not road_name and (latitude is None or longitude is None):
            result = {
                "status": "unavailable_after_attempt", "speed_mph": None,
                "failure_reason": "exact road segment is unavailable; broad Madison lookup would be non-reproducible and unsafe",
                "query_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "road_name": None, "geographic_location": None, "source_url": None,
                "source_authority": None, "applicable_observation_timestamp": None,
                "confidence": 0.0, "conflict_flags": ["road segment unresolved"],
            }
            self.external_queries.append({"tool": "lookup_posted_speed", "request": {}, "response": result})
            return result
        result = {
            "status": "not_implemented_external_provider", "speed_mph": None,
            "failure_reason": "No frozen authoritative road-speed provider is configured for this development test.",
            "query": {"road_name": road_name, "latitude": latitude, "longitude": longitude},
            "query_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "road_name": road_name, "geographic_location": {"latitude": latitude, "longitude": longitude},
            "source_url": None, "source_authority": None, "applicable_observation_timestamp": None,
            "confidence": 0.0, "conflict_flags": ["no frozen authoritative provider configured"],
        }
        self.external_queries.append({
            "tool": "lookup_posted_speed",
            "request": {"road_name": road_name, "latitude": latitude, "longitude": longitude},
            "response": result,
        })
        return result

    def query_road_authority_source(self, road_name: str | None = None,
                                    latitude: float | None = None, longitude: float | None = None) -> dict:
        """Auditable authority-query endpoint; safely refuses unresolved road identity."""
        result = self.lookup_posted_speed(road_name, latitude, longitude)
        result = {**result, "requested_source_type": "road_authority"}
        if result.get("status") == "not_implemented_external_provider":
            result["failure_reason"] = "Road identity was supplied, but no frozen road-authority provider is configured."
        return result

    def record_speed_sign_reading(self, observation_id: str, speed_mph: int, confidence: float) -> dict:
        if observation_id not in self.observations:
            return {"status": "failure", "failure_reason": "unknown accepted observation_id"}
        if not 5 <= int(speed_mph) <= 85:
            return {"status": "failure", "failure_reason": "speed outside plausible range"}
        payload = {
            "speed_mph": int(speed_mph), "speed_type": "visible_sign_candidate",
            "source_authority": "model visual reading of accepted traffic_sign bbox",
            "observation_id": observation_id, "confidence": float(confidence),
            "road_name": None, "geographic_location": None, "source_url": None,
            "local_source": self.observations[observation_id]["source_image"],
            "query_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "applicable_observation_timestamp": self.sample_data_by_filename.get(
                Path(self.observations[observation_id]["source_image"]).name, {}
            ).get("timestamp"),
            "conflict_flags": ["not independently OCR-verified", "temporary-versus-permanent status not established"],
        }
        evidence_id = _stable_id("speed", payload)
        value = {"speed_evidence_id": evidence_id, **payload}
        self.speed_evidence[evidence_id] = value
        return value

    def resolve_speed_evidence_conflict(self, speed_evidence_ids: list[str]) -> dict:
        rows = [self.speed_evidence[value] for value in speed_evidence_ids if value in self.speed_evidence]
        if len(rows) != len(speed_evidence_ids) or not rows:
            return {"status": "failure", "failure_reason": "one or more speed evidence IDs are unknown"}
        speeds = {row["speed_mph"] for row in rows}
        if len(speeds) != 1:
            return {
                "status": "unavailable_after_attempt", "speed_mph": None,
                "speed_evidence_ids": speed_evidence_ids,
                "failure_reason": "speed sources conflict", "conflict_flags": ["different speed values"],
            }
        temporary = [row for row in rows if row.get("speed_type") == "temporary_work_zone"]
        chosen = temporary[0] if temporary else max(rows, key=lambda row: row.get("confidence", 0))
        payload = {**chosen, "status": "acquired", "speed_evidence_ids": speed_evidence_ids}
        payload["conflict_flags"] = sorted(set(flag for row in rows for flag in row.get("conflict_flags", [])))
        return payload

    def _transform_sensor_to_global(self, points: np.ndarray, calibration: dict, pose: dict) -> np.ndarray:
        return (_rotation(pose["rotation"]) @ ((_rotation(calibration["rotation"]) @ points.T).T + calibration["translation"]).T).T + pose["translation"]

    def _transform_global_to_sensor(self, points: np.ndarray, calibration: dict, pose: dict) -> np.ndarray:
        ego = (_rotation(pose["rotation"]).T @ (points - pose["translation"]).T).T
        return (_rotation(calibration["rotation"]).T @ (ego - calibration["translation"]).T).T

    def project_bbox_to_lidar(self, observation_id: str) -> dict:
        started = time.process_time()
        self.resources["geometry_tool_calls"] += 1
        observation = self.observations.get(observation_id)
        if not observation:
            return {"status": "failure", "failure_reason": "unknown accepted observation_id"}
        if self.scene_record.get("validated_bev_geometry"):
            from validated_bev_adapter import locate_from_bev
            return locate_from_bev(self, observation_id)
        camera_row = self.sample_data_by_filename.get(Path(observation["source_image"]).name)
        if not camera_row:
            return {"status": "failure", "failure_reason": "camera image is not indexed in sample_data"}
        lidar_rows = [row for row in self.sample_data_by_sample[camera_row["sample_token"]]
                      if self.channel_by_calibration[row["calibrated_sensor_token"]] == "LIDAR_TOP"]
        if not lidar_rows:
            return {"status": "failure", "failure_reason": "no synchronized lidar frame for camera sample"}
        lidar_row = lidar_rows[0]
        lidar_path = self.data_root / lidar_row["filename"]
        if not lidar_path.is_file():
            return {"status": "failure", "failure_reason": "Preprocessed LiDAR file unavailable; use the case-specific validated raw-LiDAR reconstruction. Metadata entries alone do not establish point-cloud availability."}
        raw = np.fromfile(lidar_path, dtype=np.float32)
        if raw.size % 5:
            return {"status": "failure", "failure_reason": "unexpected lidar point format"}
        points = raw.reshape(-1, 5)[:, :3].astype(float)
        self.resources["point_cloud_frames_processed"] += 1
        self.resources["points_processed"] += len(points)
        lidar_cal = self.calibrations[lidar_row["calibrated_sensor_token"]]
        camera_cal = self.calibrations[camera_row["calibrated_sensor_token"]]
        lidar_pose = self.poses[lidar_row["ego_pose_token"]]
        camera_pose = self.poses[camera_row["ego_pose_token"]]
        global_points = self._transform_sensor_to_global(points, lidar_cal, lidar_pose)
        camera_points = self._transform_global_to_sensor(global_points, camera_cal, camera_pose)
        depth = camera_points[:, 2]
        valid = depth > 0.5
        uvw = (np.array(camera_cal["camera_intrinsic"]) @ camera_points[valid].T).T
        uv = uvw[:, :2] / uvw[:, 2:3]
        x1, y1, x2, y2 = map(float, observation["bbox"])
        in_box_local = (uv[:, 0] >= x1) & (uv[:, 0] <= x2) & (uv[:, 1] >= y1) & (uv[:, 1] <= y2)
        global_candidates = global_points[np.flatnonzero(valid)[in_box_local]]
        camera_candidates = camera_points[np.flatnonzero(valid)[in_box_local]]
        if len(global_candidates) < 3:
            return {
                "status": "unavailable_after_attempt", "observation_id": observation_id,
                "associated_lidar_frames": [lidar_row["filename"]],
                "failure_reason": f"only {len(global_candidates)} projected lidar points fall inside bbox",
                "quality_flags": ["insufficient_lidar_support"],
            }
        candidate_depth = camera_candidates[:, 2]
        floor = float(np.percentile(candidate_depth, 10))
        cluster = global_candidates[candidate_depth <= floor + max(1.5, 0.05 * floor)]
        center = np.median(cluster, axis=0)
        spread = float(np.percentile(np.linalg.norm(cluster - center, axis=1), 90)) if len(cluster) > 1 else 2.0
        projection_arrays = self._project_points_to_trajectory(cluster[:, :2])
        stations = projection_arrays["station_m"]
        lateral_offsets = projection_arrays["signed_lateral_offset_m"]
        low_percentile, high_percentile = self.geometry_policy["station_confidence_percentiles"]
        station_interval = [
            float(np.percentile(stations, low_percentile)),
            float(np.percentile(stations, high_percentile)),
        ]
        lateral_interval = [
            float(np.percentile(lateral_offsets, low_percentile)),
            float(np.percentile(lateral_offsets, high_percentile)),
        ]
        station_m = float(np.median(stations))
        lateral_offset_m = float(np.median(lateral_offsets))
        lateral_residual_p95 = float(np.percentile(np.abs(lateral_offsets), 95))
        station_uncertainty = max(station_m - station_interval[0], station_interval[1] - station_m)
        quality_flags = ["bbox_frustum_can_include_background", "not_survey_grade"]
        if lateral_residual_p95 > self.geometry_policy["lateral_residual_warning_m"]:
            quality_flags.append("large_trajectory_lateral_residual")
        longitudinal_geometry_usable = lateral_residual_p95 <= self.geometry_policy["lateral_residual_reject_m"]
        if not longitudinal_geometry_usable:
            quality_flags.append("trajectory_lateral_residual_exceeds_gate")
        result = {
            "status": "acquired", "location_id": _stable_id("location", [observation_id, lidar_row["token"]]),
            "observation_id": observation_id, "global_xyz_m": center.tolist(),
            "uncertainty_m": max(spread, 0.5), "spatial_uncertainty_m": max(spread, 0.5),
            "road_station_m": station_m,
            "station_confidence_interval_m": station_interval,
            "station_uncertainty_m": station_uncertainty,
            "station_sample_count": len(stations),
            "trajectory_lateral_offset_m": lateral_offset_m,
            "lateral_confidence_interval_m": lateral_interval,
            "trajectory_lateral_residual_m": abs(lateral_offset_m),
            "trajectory_lateral_residual_p95_m": lateral_residual_p95,
            "longitudinal_geometry_usable": longitudinal_geometry_usable,
            "trajectory_local_tangent_xy": self._project_to_trajectory(center[:2])["tangent_xy"],
            "trajectory_local_normal_xy": self._project_to_trajectory(center[:2])["normal_xy"],
            "projected_points_in_bbox": len(global_candidates),
            "depth_cluster_points": len(cluster), "associated_image_ids": [Path(observation["source_image"]).stem],
            "associated_bbox_ids": [observation_id], "associated_lidar_frames": [lidar_row["filename"]],
            "trajectory_pose_source": str(self.meta_root / "ego_pose.json"),
            "calibration_source": str(self.meta_root / "calibrated_sensor.json"),
            "measurement_method": (
                "synchronized lidar projection into accepted 2D bbox; nearest-depth robust cluster; "
                "each retained point projected independently to trajectory station"
            ),
            "quality_flags": quality_flags, "failure_reason": None,
        }
        self.resources["cpu_seconds"] += time.process_time() - started
        return result

    def _project_points_to_trajectory(self, xy: np.ndarray) -> dict[str, np.ndarray]:
        points = np.asarray(xy, dtype=float).reshape(-1, 2)
        if len(points) > 512:
            parts = [self._project_points_to_trajectory(points[index:index + 512])
                     for index in range(0, len(points), 512)]
            return {key: np.concatenate([part[key] for part in parts], axis=0) for key in parts[0]}
        starts = np.array([row["translation"][:2] for row in self._trajectory[:-1]], dtype=float)
        ends = np.array([row["translation"][:2] for row in self._trajectory[1:]], dtype=float)
        station_starts = np.array([row["station_m"] for row in self._trajectory[:-1]], dtype=float)
        deltas = ends - starts
        lengths = np.linalg.norm(deltas, axis=1)
        valid = lengths > 1e-9
        if not np.any(valid):
            raise RuntimeError("ego trajectory has no non-degenerate segment")
        starts, deltas, lengths, station_starts = (
            starts[valid], deltas[valid], lengths[valid], station_starts[valid]
        )
        tangents = deltas / lengths[:, None]
        normals = np.column_stack((-tangents[:, 1], tangents[:, 0]))
        relative = points[:, None, :] - starts[None, :, :]
        fractions = np.einsum("nmi,mi->nm", relative, deltas) / (lengths[None, :] ** 2)
        fractions = np.clip(fractions, 0.0, 1.0)
        projected = starts[None, :, :] + fractions[:, :, None] * deltas[None, :, :]
        residual_vectors = points[:, None, :] - projected
        distance_squared = np.einsum("nmi,nmi->nm", residual_vectors, residual_vectors)
        best_indices = np.argmin(distance_squared, axis=1)
        rows = np.arange(len(points))
        best_fractions = fractions[rows, best_indices]
        best_residuals = residual_vectors[rows, best_indices]
        best_normals = normals[best_indices]
        return {
            "station_m": station_starts[best_indices] + best_fractions * lengths[best_indices],
            "lateral_residual_m": np.sqrt(distance_squared[rows, best_indices]),
            "signed_lateral_offset_m": np.einsum("ni,ni->n", best_residuals, best_normals),
            "projected_xy_m": projected[rows, best_indices],
            "tangent_xy": tangents[best_indices],
            "normal_xy": best_normals,
        }

    def _project_to_trajectory(self, xy: list[float] | np.ndarray) -> dict:
        values = self._project_points_to_trajectory(np.asarray(xy[:2], dtype=float).reshape(1, 2))
        return {
            "station_m": float(values["station_m"][0]),
            "lateral_residual_m": float(values["lateral_residual_m"][0]),
            "signed_lateral_offset_m": float(values["signed_lateral_offset_m"][0]),
            "projected_xy_m": values["projected_xy_m"][0].tolist(),
            "tangent_xy": values["tangent_xy"][0].tolist(),
            "normal_xy": values["normal_xy"][0].tolist(),
        }

    def _station(self, xyz: list[float]) -> tuple[float, float]:
        projection = self._project_to_trajectory(xyz[:2])
        return projection["station_m"], projection["lateral_residual_m"]

    def locate_device_in_scene(self, observation_id: str) -> dict:
        return self.project_bbox_to_lidar(observation_id)

    @staticmethod
    def _interval_distance(left: list[float], right: list[float]) -> list[float]:
        if left[0] > right[1]:
            lower = left[0] - right[1]
        elif right[0] > left[1]:
            lower = right[0] - left[1]
        else:
            lower = 0.0
        upper = max(abs(left_value - right_value) for left_value in left for right_value in right)
        return [float(lower), float(upper)]

    @staticmethod
    def _threshold_assessment(
        confidence_interval_m: list[float], threshold_value: float | None,
        threshold_unit: str | None, violation_when: str | None, geometry_ready: bool,
    ) -> dict:
        if threshold_value is None or threshold_unit is None or violation_when is None:
            return {
                "status": "threshold_not_supplied", "threshold_m": None,
                "violation_when": violation_when, "clear_violation": False,
                "reason": "No numeric normative threshold was supplied to the measurement tool.",
            }
        if threshold_unit not in {"m", "ft"}:
            raise ValueError("threshold_unit must be m or ft")
        if violation_when not in {"below_minimum", "above_maximum"}:
            raise ValueError("violation_when must be below_minimum or above_maximum")
        threshold_m = float(threshold_value) * (0.3048 if threshold_unit == "ft" else 1.0)
        if not geometry_ready:
            return {
                "status": "geometry_not_eligible", "threshold_m": threshold_m,
                "violation_when": violation_when, "clear_violation": False,
                "reason": "Endpoint semantics or measurement direction failed validation.",
            }
        lower, upper = confidence_interval_m
        clear = upper < threshold_m if violation_when == "below_minimum" else lower > threshold_m
        return {
            "status": "clear_violation" if clear else "no_clear_violation",
            "threshold_m": threshold_m, "violation_when": violation_when,
            "clear_violation": clear,
            "reason": (
                "The complete confidence interval lies beyond the violation threshold."
                if clear else
                "The confidence interval does not lie wholly beyond the violation threshold; no obvious error is established."
            ),
        }

    @staticmethod
    def _expected_endpoint_roles(measurement_type: str) -> tuple[str, str] | None:
        return {
            "device_spacing": ("spacing_device", "spacing_device"),
            "taper_length": ("taper_start", "taper_end"),
            "buffer_length": ("buffer_start", "buffer_end"),
            "sign_spacing": ("upstream_sign", "downstream_sign"),
            "downstream_taper": ("downstream_taper_start", "downstream_taper_end"),
        }.get(measurement_type)

    def _longitudinal_measurement_from_locations(
        self, start: dict, end: dict, measurement_type: str,
        start_role: str, end_role: str, threshold_value: float | None,
        threshold_unit: str | None, violation_when: str | None,
    ) -> dict:
        start = {**start, "semantic_role": start_role}
        end = {**end, "semantic_role": end_role}
        ordered = sorted((start, end), key=lambda row: (row["road_station_m"], row["observation_id"]))
        upstream, downstream = ordered
        value = downstream["road_station_m"] - upstream["road_station_m"]
        upstream_interval = upstream["station_confidence_interval_m"]
        downstream_interval = downstream["station_confidence_interval_m"]
        confidence_interval = [
            max(0.0, downstream_interval[0] - upstream_interval[1]),
            max(0.0, downstream_interval[1] - upstream_interval[0]),
        ]
        expected_roles = self._expected_endpoint_roles(measurement_type)
        endpoint_semantics_valid = bool(
            expected_roles
            and start_role == expected_roles[0]
            and end_role == expected_roles[1]
            and upstream["semantic_role"] == expected_roles[0]
            and downstream["semantic_role"] == expected_roles[1]
        )
        geometry_direction_valid = all(row.get("longitudinal_geometry_usable") is True for row in ordered)
        quality_flags = sorted(set(start["quality_flags"] + end["quality_flags"]))
        if not endpoint_semantics_valid:
            quality_flags.append("endpoint_semantics_unverified_or_order_conflict")
        if not geometry_direction_valid:
            quality_flags.append("longitudinal_geometry_failed_lateral_gate")
        geometry_ready = endpoint_semantics_valid and geometry_direction_valid
        threshold_assessment = self._threshold_assessment(
            confidence_interval, threshold_value, threshold_unit, violation_when, geometry_ready
        )
        uncertainty = max(value - confidence_interval[0], confidence_interval[1] - value)
        payload = [measurement_type, start["observation_id"], start_role,
                   end["observation_id"], end_role, round(value, 4)]
        result = {
            "status": "acquired", "measurement_id": _stable_id("measurement", payload),
            "measurement_type": measurement_type, "geometry_direction": "longitudinal_station",
            "value": value, "unit": "m", "uncertainty": uncertainty,
            "confidence_interval": confidence_interval,
            "start_anchor": start, "end_anchor": end, "ordered_anchors": ordered,
            "endpoint_semantics_valid": endpoint_semantics_valid,
            "geometry_direction_valid": geometry_direction_valid,
            "threshold_assessment": threshold_assessment,
            "deficiency_supported": threshold_assessment["clear_violation"],
            "associated_image_ids": start["associated_image_ids"] + end["associated_image_ids"],
            "associated_bbox_ids": [start["observation_id"], end["observation_id"]],
            "associated_lidar_frames": start["associated_lidar_frames"] + end["associated_lidar_frames"],
            "trajectory_pose_source": str(self.meta_root / "ego_pose.json"),
            "calibration_source": str(self.meta_root / "calibrated_sensor.json"),
            "measurement_method": (
                "difference of automatically station-sorted endpoint medians; confidence interval derived "
                "from endpoint station support intervals (see anchor provenance); lateral residual used only as a quality gate"
            ),
            "quality_flags": sorted(set(quality_flags)), "failure_reason": None,
        }
        self.measurements[result["measurement_id"]] = result
        return result

    def measure_longitudinal_distance(
        self, start_observation_id: str, end_observation_id: str,
        measurement_type: str = "longitudinal_distance",
        start_role: str = "unspecified_start", end_role: str = "unspecified_end",
        threshold_value: float | None = None, threshold_unit: str | None = None,
        violation_when: str | None = None,
    ) -> dict:
        started = time.process_time()
        start, end = self.locate_device_in_scene(start_observation_id), self.locate_device_in_scene(end_observation_id)
        if start.get("status") != "acquired" or end.get("status") != "acquired":
            return {"status": "unavailable_after_attempt", "measurement_type": measurement_type,
                    "failure_reason": "one or both anchors could not be associated", "start_anchor": start, "end_anchor": end}
        result = self._longitudinal_measurement_from_locations(
            start, end, measurement_type, start_role, end_role,
            threshold_value, threshold_unit, violation_when,
        )
        self.resources["cpu_seconds"] += time.process_time() - started
        return result

    def measure_device_spacing(
        self, observation_ids: list[str], threshold_value: float | None = None,
        threshold_unit: str | None = None, violation_when: str | None = None,
    ) -> dict:
        if len(observation_ids) < 2 or len(observation_ids) > 10:
            return {"status": "failure", "failure_reason": "between two and ten anchors are required per call"}
        located = [self.locate_device_in_scene(observation_id) for observation_id in observation_ids]
        failures = [row for row in located if row.get("status") != "acquired"]
        if failures:
            return {"status": "partial_or_unavailable", "failure_reason": "one or more anchors could not be associated",
                    "failed_anchors": failures}
        representatives: dict[str, dict] = {}
        removed: list[str] = []
        for row in located:
            observation = self.observations[row["observation_id"]]
            entity_key = observation.get("refined_element_id") or observation.get("raw_device_id") or row["observation_id"]
            interval = row["station_confidence_interval_m"]
            quality = (interval[1] - interval[0], -row.get("depth_cluster_points", 0), row["observation_id"])
            prior = representatives.get(entity_key)
            if prior is None or quality < prior["_selection_quality"]:
                if prior is not None:
                    removed.append(prior["observation_id"])
                representatives[entity_key] = {**row, "_selection_quality": quality}
            else:
                removed.append(row["observation_id"])
        ordered = sorted(representatives.values(), key=lambda row: (row["road_station_m"], row["observation_id"]))
        if len(ordered) < 2:
            return {"status": "failure", "failure_reason": "fewer than two distinct physical entities remain after deduplication",
                    "duplicate_observation_ids_removed": sorted(removed)}
        values = [
            self._longitudinal_measurement_from_locations(
                left, right, "device_spacing", "spacing_device", "spacing_device",
                threshold_value, threshold_unit, violation_when,
            )
            for left, right in zip(ordered, ordered[1:])
        ]
        compact = []
        for row in values:
            if row.get("status") != "acquired":
                compact.append(row)
                continue
            compact.append({
                **{key: row[key] for key in (
                    "status", "measurement_id", "measurement_type", "value", "unit", "uncertainty",
                    "confidence_interval", "associated_image_ids", "associated_bbox_ids",
                    "associated_lidar_frames", "trajectory_pose_source", "calibration_source",
                    "measurement_method", "quality_flags", "failure_reason",
                )},
                "start_anchor": {key: row["start_anchor"].get(key) for key in
                                 ("observation_id", "semantic_role", "road_station_m", "station_uncertainty_m")},
                "end_anchor": {key: row["end_anchor"].get(key) for key in
                               ("observation_id", "semantic_role", "road_station_m", "station_uncertainty_m")},
                "endpoint_semantics_valid": row["endpoint_semantics_valid"],
                "geometry_direction_valid": row["geometry_direction_valid"],
                "threshold_assessment": row["threshold_assessment"],
                "deficiency_supported": row["deficiency_supported"],
            })
        return {"measurement_type": "device_spacing_series", "segments": compact,
                "status": "acquired", "ordered_observation_ids": [row["observation_id"] for row in ordered],
                "duplicate_observation_ids_removed": sorted(removed)}

    @staticmethod
    def _classify_channelizer_gaps(sequence: list[dict]) -> dict:
        """Fit a query-independent taper-plus-tangent model in road coordinates."""
        laterals = np.asarray([row["lateral_m"] for row in sequence], dtype=float)
        stations = np.asarray([row["station_m"] for row in sequence], dtype=float)
        smoothed = laterals.copy()
        for index in range(1, len(laterals) - 1):
            smoothed[index] = float(np.median(laterals[index - 1:index + 2]))
        candidates = []
        minimum_segment_points = 4
        for split in range(minimum_segment_points, len(sequence) - minimum_segment_points + 1):
            for orientation in ("taper_then_tangent", "tangent_then_taper"):
                if orientation == "taper_then_tangent":
                    taper_x, taper_y = stations[:split], smoothed[:split]
                    tangent_y = smoothed[split:]
                else:
                    taper_x, taper_y = stations[split:], smoothed[split:]
                    tangent_y = smoothed[:split]
                slope, intercept = np.polyfit(taper_x, taper_y, 1)
                fitted = slope * taper_x + intercept
                lateral_shift = abs(float(fitted[-1] - fitted[0]))
                error = float(np.sum((taper_y - fitted) ** 2) +
                              np.sum((tangent_y - np.median(tangent_y)) ** 2))
                candidates.append((error, orientation, split, float(slope), lateral_shift))
        best = min(candidates) if candidates else None
        constant_error = float(np.sum((smoothed - np.median(smoothed)) ** 2))
        has_geometric_taper = bool(
            best and abs(best[3]) >= 0.02 and best[4] >= 1.0 and best[0] < 0.9 * constant_error
        )
        regions = ["tangent"] * (len(sequence) - 1)
        if has_geometric_taper and best:
            _, orientation, split, _, _ = best
            if orientation == "taper_then_tangent":
                for index in range(min(split - 1, len(regions))):
                    regions[index] = "taper"
            else:
                for index in range(max(0, split), len(regions)):
                    regions[index] = "taper"
        return {
            "gap_regions": regions,
            "model": "piecewise road-coordinate linear taper plus constant-lateral tangent",
            "orientation": best[1] if has_geometric_taper and best else "all_tangent",
            "change_station_m": None if not has_geometric_taper or not best else float(stations[best[2]]),
            "taper_lateral_slope": None if not has_geometric_taper or not best else best[3],
            "taper_lateral_shift_m": None if not has_geometric_taper or not best else best[4],
            "piecewise_error": None if not best else best[0], "constant_error": constant_error,
        }

    @staticmethod
    def _sustained_true_runs(flags: list[bool], minimum_length: int = 2) -> list[tuple[int, int]]:
        runs: list[tuple[int, int]] = []
        start: int | None = None
        for index, flag in enumerate(flags + [False]):
            if flag and start is None:
                start = index
            elif not flag and start is not None:
                if index - start >= minimum_length:
                    runs.append((start, index))
                start = None
        return runs

    def audit_channelizer_spacing(
        self, thresholds: dict[str, dict], minimum_consecutive_exceedances: int = 2,
    ) -> dict:
        """Audit the accepted channelizer line nearest the ego trajectory.

        Traffic drums, traffic cones, and generic channelizing devices are treated
        as channelizers. The program uses human-accepted 2D observations with
        existing local scene positions, consolidates repeated observations into
        physical-track candidates, removes near-duplicate tracks, builds smooth
        road-coordinate sequences, selects the continuous sequence nearest the
        driven trajectory, and tests every adjacent gap in that sequence. A formal
        deficiency requires a configured number of consecutive gaps whose
        conservative lower bounds exceed the supplied registered thresholds.
        """
        started = time.process_time()
        self.resources["geometry_tool_calls"] += 1
        if not thresholds or not set(thresholds).issubset({"taper", "tangent"}):
            raise ValueError("registered thresholds must provide taper and/or tangent conditions")
        if minimum_consecutive_exceedances < 1:
            raise ValueError("minimum_consecutive_exceedances must be positive")
        thresholds_m: dict[str, float] = {}
        for condition, rule in thresholds.items():
            if rule.get("violation_when") != "above_maximum":
                raise ValueError(f"{condition} spacing requires an above_maximum threshold")
            value = float(rule["value"])
            unit = rule["unit"]
            if value <= 0 or unit not in {"m", "ft"}:
                raise ValueError(f"invalid registered threshold for {condition}")
            thresholds_m[condition] = value if unit == "m" else value * 0.3048
        accepted = list(self.observations.values())
        channelizer_classes = {"traffic_drum", "traffic_cone", "channelizing_device"}
        invalidated_entities = set(self.scene_record.get("invalidated_entity_ids", []))

        grouped: dict[str, list[tuple[dict, np.ndarray]]] = defaultdict(list)
        accepted_observation_count = 0
        for observation in accepted:
            if observation.get("reviewed_class") not in channelizer_classes:
                continue
            entity_id = observation.get("refined_element_id") or observation.get("raw_device_id")
            xyz = observation.get("xyz")
            if not entity_id or entity_id in invalidated_entities or not xyz:
                continue
            if observation.get("geometry_eligible") is not True:
                continue
            accepted_observation_count += 1
            grouped[entity_id].append((observation, np.asarray(xyz, dtype=float)))

        candidates: list[dict] = []
        excluded_low_support = 0
        excluded_unstable = 0
        for entity_id, rows in grouped.items():
            independent_frames = {row[0]["frame"] for row in rows}
            if len(independent_frames) < 2:
                excluded_low_support += 1
                continue
            xyz_rows = np.asarray([row[1] for row in rows])
            median_xyz = np.median(xyz_rows, axis=0)
            radial = np.linalg.norm(xyz_rows[:, :2] - median_xyz[:2], axis=1)
            uncertainty_m = max(0.5, float(np.percentile(radial, 90)))
            if uncertainty_m > 2.0:
                excluded_unstable += 1
                continue
            representative = min(rows, key=lambda row: float(np.linalg.norm(row[1][:2] - median_xyz[:2])))[0]
            road = self._project_to_trajectory(median_xyz[:2])
            candidates.append({
                "entity_id": entity_id,
                "representative_observation_id": representative["observation_id"],
                "source_image": representative["source_image"],
                "xyz": median_xyz,
                "station_m": road["station_m"],
                "lateral_m": road["signed_lateral_offset_m"],
                "uncertainty_m": uncertainty_m,
                "accepted_observation_count": len(rows),
                "independent_frame_count": len(independent_frames),
                "reviewed_classes": sorted({row[0]["reviewed_class"] for row in rows}),
                "merged_entity_ids": [entity_id],
            })

        # Collapse multiple track IDs that resolve to the same physical object.
        # This query-independent spatial gate prevents duplicate tracks from being
        # treated as intentionally close devices.
        parent = list(range(len(candidates)))

        def find(value: int) -> int:
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        def union(left: int, right: int) -> None:
            a, b = find(left), find(right)
            if a != b:
                parent[b] = a

        for left in range(len(candidates)):
            for right in range(left + 1, len(candidates)):
                if (not self.scene_record.get("validated_bev_geometry") and
                        float(np.linalg.norm(candidates[left]["xyz"][:2] - candidates[right]["xyz"][:2])) <= 1.5):
                    union(left, right)
        duplicate_groups: dict[int, list[dict]] = defaultdict(list)
        for index, row in enumerate(candidates):
            duplicate_groups[find(index)].append(row)
        entities: list[dict] = []
        for rows in duplicate_groups.values():
            chosen = min(rows, key=lambda row: (
                row["uncertainty_m"], -row["independent_frame_count"], row["entity_id"]
            ))
            entities.append({
                **chosen,
                "merged_entity_ids": sorted(
                    entity_id for row in rows for entity_id in row["merged_entity_ids"]
                ),
                "reviewed_classes": sorted(set(
                    reviewed_class
                    for row in rows
                    for reviewed_class in row["reviewed_classes"]
                )),
            })

        # Deterministic path cover in Frenet coordinates. Parallel drum lines
        # remain separate because their lateral separation normally exceeds the
        # fixed 2.2 m step gate; a taper may change laterally only gradually.
        max_station_link_m = 75.0
        sequences: list[list[dict]] = []
        for entity in sorted(entities, key=lambda row: (row["station_m"], row["lateral_m"], row["entity_id"])):
            choices = []
            for index, sequence in enumerate(sequences):
                prior = sequence[-1]
                station_delta = entity["station_m"] - prior["station_m"]
                lateral_delta = abs(entity["lateral_m"] - prior["lateral_m"])
                if (0.05 if self.scene_record.get("validated_bev_geometry") else 1.5) <= station_delta <= max_station_link_m and lateral_delta <= 2.2:
                    cost = lateral_delta / 2.2 + station_delta / max_station_link_m
                    choices.append((cost, index))
            if choices:
                sequences[min(choices)[1]].append(entity)
            else:
                sequences.append([entity])
        sequences = [sequence for sequence in sequences if len(sequence) >= 3]
        candidate_sequence_count = len(sequences)
        if sequences:
            # Only the continuous channelizer line nearest the driven trajectory
            # defines traffic-side spacing. More distant parallel lines may be
            # work-space boundaries and must not create additional findings.
            selected_sequence = min(
                sequences,
                key=lambda sequence: (
                    float(np.median([abs(row["lateral_m"]) for row in sequence])),
                    -(sequence[-1]["station_m"] - sequence[0]["station_m"]),
                    sequence[0]["entity_id"],
                ),
            )
            selected_sequence_median_abs_lateral_m = float(np.median([
                abs(row["lateral_m"]) for row in selected_sequence
            ]))
            selected_sequence_entity_ids = [row["entity_id"] for row in selected_sequence]
            selected_sequence_reviewed_class_counts: dict[str, int] = defaultdict(int)
            for row in selected_sequence:
                for reviewed_class in row["reviewed_classes"]:
                    selected_sequence_reviewed_class_counts[reviewed_class] += 1
            sequences = [selected_sequence]
        else:
            selected_sequence_median_abs_lateral_m = None
            selected_sequence_entity_ids = []
            selected_sequence_reviewed_class_counts = defaultdict(int)

        # The human bbox audit is deliberately partial. Use the complete active
        # device inventory only as a conservative veto: an unreviewed automatic
        # channelizer between two accepted endpoints can cancel a gap claim, but
        # can never create compliance evidence or a deficiency by itself.
        inventory_path = Path(
            self.scene_record.get("data_sources", {}).get(
                "device_inventory",
                ROOT.parents[1] / "bev_full_scene/scene_evidence_current/device_inventory.csv",
            )
        )
        possible_interveners = []
        with inventory_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("class_name") != "channelizing_device" or row.get("inspection_layer") != "active_device":
                    continue
                if row.get("eligible_for_any_position_plot") != "True":
                    continue
                try:
                    xy = np.asarray([float(row["x_enu_m"]), float(row["y_enu_m"])], dtype=float)
                except (TypeError, ValueError):
                    continue
                possible_interveners.append({"entity_id": row["id"], "xy": xy})

        def intervening_entities(left: dict, right: dict) -> list[str]:
            start_xy, end_xy = left["xyz"][:2], right["xyz"][:2]
            delta = end_xy - start_xy
            squared = float(np.dot(delta, delta))
            if squared <= 1e-9:
                return []
            endpoint_entities = set(left["merged_entity_ids"] + right["merged_entity_ids"])
            found = []
            for candidate in possible_interveners:
                if candidate["entity_id"] in endpoint_entities:
                    continue
                fraction = float(np.dot(candidate["xy"] - start_xy, delta) / squared)
                if not 0.05 < fraction < 0.95:
                    continue
                projected = start_xy + fraction * delta
                if float(np.linalg.norm(candidate["xy"] - projected)) <= 2.0:
                    found.append(candidate["entity_id"])
            return sorted(set(found))

        evaluated_gaps = 0
        clear_exceedance_gaps = 0
        gaps_vetoed_by_possible_intervener = 0
        violation_runs = []
        sequence_summaries = []
        all_representative_ids = []
        for sequence_index, sequence in enumerate(sequences, start=1):
            gaps = []
            region_model = self._classify_channelizer_gaps(sequence)
            channelization_regions = region_model["gap_regions"]
            for gap_index, (left, right) in enumerate(zip(sequence, sequence[1:])):
                channelization_region = channelization_regions[gap_index]
                threshold_m = thresholds_m.get(channelization_region)
                value_m = float(np.linalg.norm(right["xyz"][:2] - left["xyz"][:2]))
                lower_m = max(0.0, value_m - left["uncertainty_m"] - right["uncertainty_m"])
                upper_m = value_m + left["uncertainty_m"] + right["uncertainty_m"]
                blockers = intervening_entities(left, right)
                clear = threshold_m is not None and lower_m > threshold_m and not blockers
                gaps.append({
                    "gap_index": gap_index + 1,
                    "from_entity_id": left["entity_id"], "to_entity_id": right["entity_id"],
                    "channelization_region": channelization_region,
                    "threshold_m": threshold_m,
                    "evaluated_against_registered_rule": threshold_m is not None,
                    "value_m": value_m, "confidence_interval_m": [lower_m, upper_m],
                    "possible_intervening_entity_ids": blockers,
                    "clear_exceedance": clear,
                })
                evaluated_gaps += int(threshold_m is not None)
                clear_exceedance_gaps += int(clear)
                gaps_vetoed_by_possible_intervener += int(threshold_m is not None and lower_m > threshold_m and bool(blockers))
            run_ranges = self._sustained_true_runs(
                [row["clear_exceedance"] for row in gaps], minimum_consecutive_exceedances
            )
            for start, end in run_ranges:
                run_gaps = gaps[start:end]
                run_entities = sequence[start:end + 1]
                violation_runs.append({
                    "sequence_id": f"sequence_{sequence_index:02d}",
                    "gap_count": len(run_gaps),
                    "start_station_m": run_entities[0]["station_m"],
                    "end_station_m": run_entities[-1]["station_m"],
                    "maximum_gap_m": max(row["value_m"] for row in run_gaps),
                    "minimum_conservative_gap_m": min(row["confidence_interval_m"][0] for row in run_gaps),
                    "entity_ids": [row["entity_id"] for row in run_entities],
                    "evidence_observation_ids": [row["representative_observation_id"] for row in run_entities],
                    "entities": [{
                        "entity_id": row["entity_id"],
                        "station_m": row["station_m"], "lateral_m": row["lateral_m"],
                        "uncertainty_m": row["uncertainty_m"],
                        "reviewed_classes": row["reviewed_classes"],
                        "observation_id": row["representative_observation_id"],
                    } for row in run_entities],
                    "gaps": [{
                        "from_entity_id": row["from_entity_id"], "to_entity_id": row["to_entity_id"],
                        "value_m": row["value_m"],
                        "lower_m": row["confidence_interval_m"][0],
                        "upper_m": row["confidence_interval_m"][1],
                    } for row in run_gaps],
                })
            all_representative_ids.extend(row["representative_observation_id"] for row in sequence)
            sequence_summaries.append({
                "sequence_id": f"sequence_{sequence_index:02d}", "entity_count": len(sequence),
                "gap_count": len(gaps), "start_station_m": sequence[0]["station_m"],
                "end_station_m": sequence[-1]["station_m"],
                "taper_gap_count": channelization_regions.count("taper"),
                "tangent_gap_count": channelization_regions.count("tangent"),
                "region_model": region_model,
                "device_road_coordinates": [{
                    "entity_id": row["entity_id"], "station_m": row["station_m"],
                    "lateral_m": row["lateral_m"],
                } for row in sequence],
                "clear_exceedance_gap_count": sum(row["clear_exceedance"] for row in gaps),
                "sustained_violation_run_count": len(run_ranges),
                "gaps": gaps,
            })

        payload = ["channelizer_spacing_series", thresholds,
                   sorted((row["sequence_id"], row["start_station_m"], row["end_station_m"])
                          for row in violation_runs)]
        measurement_id = _stable_id("measurement", payload)
        deficiency_supported = bool(violation_runs)
        result = {
            "status": "acquired", "measurement_id": measurement_id,
            "measurement_type": "channelizer_spacing_series",
            "thresholds_applied": {
                condition: {**thresholds[condition], "value_m": thresholds_m[condition]}
                for condition in sorted(thresholds)
            },
            "deficiency_supported": deficiency_supported,
            "minimum_consecutive_exceedances": minimum_consecutive_exceedances,
            "accepted_channelizer_observations_scanned": accepted_observation_count,
            "physical_entity_candidates": len(entities),
            "candidate_sequence_count": candidate_sequence_count,
            "sequences_evaluated": len(sequences),
            "selected_sequence_policy": "continuous channelizer line with minimum median absolute lateral offset from ego trajectory",
            "selected_sequence_median_abs_lateral_m": selected_sequence_median_abs_lateral_m,
            "selected_sequence_entity_ids": selected_sequence_entity_ids,
            "selected_sequence_reviewed_class_counts": dict(sorted(selected_sequence_reviewed_class_counts.items())),
            "region_classification_method": "three-point median lateral smoothing followed by deterministic piecewise road-coordinate fitting of a sloped taper and constant-lateral tangent",
            "included_reviewed_classes": sorted(channelizer_classes),
            "gaps_evaluated": evaluated_gaps, "clear_exceedance_gap_count": clear_exceedance_gaps,
            "gaps_vetoed_by_possible_intervener": gaps_vetoed_by_possible_intervener,
            "violation_run_count": len(violation_runs), "violation_runs": violation_runs[:20],
            "sequence_summaries": sequence_summaries,
            "associated_bbox_ids": sorted(set(all_representative_ids)),
            "associated_image_ids": sorted(set(
                Path(row["source_image"]).stem for sequence in sequences for row in sequence
            )),
            "endpoint_semantics_valid": True, "geometry_direction_valid": True,
            "sequence_inference_valid": bool(sequences) and evaluated_gaps > 0,
            "measurement_method": "rule-based accepted-track deduplication, Frenet path cover, nearest-trajectory sequence selection, and exhaustive adjacent-gap audit",
            "quality_flags": [
                "accepted_bbox_class_only", "track_positions_are_not_survey_grade",
                "sequence_membership_is_rule_based", "single_gap_is_not_a_formal_deficiency",
                "farther_parallel_channelizer_lines_excluded",
                "complete_automatic_inventory_used_only_to_veto_possible_missed_devices",
            ],
            "excluded_low_support_entities": excluded_low_support,
            "excluded_unstable_entities": excluded_unstable,
            "failure_reason": None,
        }
        self.measurements[measurement_id] = result
        self.resources["cpu_seconds"] += time.process_time() - started
        return result

    def measure_taper_length(self, start_observation_id: str, end_observation_id: str,
                             threshold_value: float | None = None, threshold_unit: str | None = None,
                             violation_when: str | None = None) -> dict:
        return self.measure_longitudinal_distance(start_observation_id, end_observation_id, "taper_length",
                                                  "taper_start", "taper_end", threshold_value,
                                                  threshold_unit, violation_when)

    def measure_buffer_length(self, start_observation_id: str, end_observation_id: str,
                              threshold_value: float | None = None, threshold_unit: str | None = None,
                              violation_when: str | None = None) -> dict:
        return self.measure_longitudinal_distance(start_observation_id, end_observation_id, "buffer_length",
                                                  "buffer_start", "buffer_end", threshold_value,
                                                  threshold_unit, violation_when)

    def measure_sign_spacing(self, start_observation_id: str, end_observation_id: str,
                             threshold_value: float | None = None, threshold_unit: str | None = None,
                             violation_when: str | None = None) -> dict:
        return self.measure_longitudinal_distance(start_observation_id, end_observation_id, "sign_spacing",
                                                  "upstream_sign", "downstream_sign", threshold_value,
                                                  threshold_unit, violation_when)

    def measure_downstream_taper(self, start_observation_id: str, end_observation_id: str,
                                 threshold_value: float | None = None, threshold_unit: str | None = None,
                                 violation_when: str | None = None) -> dict:
        return self.measure_longitudinal_distance(
            start_observation_id, end_observation_id, "downstream_taper",
            "downstream_taper_start", "downstream_taper_end", threshold_value,
            threshold_unit, violation_when,
        )

    def estimate_available_width(
        self, left_observation_id: str, right_observation_id: str,
        threshold_value: float | None = None, threshold_unit: str | None = None,
        violation_when: str | None = None,
    ) -> dict:
        started = time.process_time()
        left = self.locate_device_in_scene(left_observation_id)
        right = self.locate_device_in_scene(right_observation_id)
        if left.get("status") != "acquired" or right.get("status") != "acquired":
            return {"status": "unavailable_after_attempt", "measurement_type": "available_width",
                    "failure_reason": "one or both width boundaries could not be associated",
                    "left_anchor": left, "right_anchor": right}
        left = {**left, "semantic_role": "left_boundary"}
        right = {**right, "semantic_role": "right_boundary"}
        midpoint = (np.array(left["global_xyz_m"][:2]) + np.array(right["global_xyz_m"][:2])) / 2
        road_frame = self._project_to_trajectory(midpoint)
        tangent = np.array(road_frame["tangent_xy"])
        normal = np.array(road_frame["normal_xy"])
        delta = np.array(left["global_xyz_m"][:2]) - np.array(right["global_xyz_m"][:2])
        normal_separation = abs(float(np.dot(delta, normal)))
        longitudinal_offset = abs(float(np.dot(delta, tangent)))
        station_offset = abs(left["road_station_m"] - right["road_station_m"])
        endpoint_semantics_valid = left["trajectory_lateral_offset_m"] > right["trajectory_lateral_offset_m"]
        geometry_direction_valid = (
            station_offset <= self.geometry_policy["width_max_longitudinal_offset_m"]
            and normal_separation >= self.geometry_policy["width_normal_dominance_ratio"] * longitudinal_offset
        )
        confidence_interval = self._interval_distance(
            left["lateral_confidence_interval_m"], right["lateral_confidence_interval_m"]
        )
        geometry_ready = endpoint_semantics_valid and geometry_direction_valid
        threshold_assessment = self._threshold_assessment(
            confidence_interval, threshold_value, threshold_unit, violation_when, geometry_ready
        )
        quality_flags = sorted(set(left["quality_flags"] + right["quality_flags"]))
        if not endpoint_semantics_valid:
            quality_flags.append("left_right_boundary_semantics_conflict")
        if not geometry_direction_valid:
            quality_flags.append("boundary_pair_does_not_define_road_normal_cross_section")
        uncertainty = max(normal_separation - confidence_interval[0], confidence_interval[1] - normal_separation)
        payload = ["available_width", left_observation_id, right_observation_id, round(normal_separation, 4)]
        result = {
            "status": "acquired", "measurement_id": _stable_id("measurement", payload),
            "measurement_type": "available_width", "geometry_direction": "road_normal",
            "value": normal_separation, "unit": "m", "uncertainty": uncertainty,
            "confidence_interval": confidence_interval,
            "left_anchor": left, "right_anchor": right,
            "endpoint_semantics_valid": endpoint_semantics_valid,
            "geometry_direction_valid": geometry_direction_valid,
            "longitudinal_offset_m": longitudinal_offset, "station_offset_m": station_offset,
            "road_tangent_xy": tangent.tolist(), "road_normal_xy": normal.tolist(),
            "threshold_assessment": threshold_assessment,
            "deficiency_supported": threshold_assessment["clear_violation"],
            "associated_image_ids": left["associated_image_ids"] + right["associated_image_ids"],
            "associated_bbox_ids": [left_observation_id, right_observation_id],
            "associated_lidar_frames": left["associated_lidar_frames"] + right["associated_lidar_frames"],
            "trajectory_pose_source": str(self.meta_root / "ego_pose.json"),
            "calibration_source": str(self.meta_root / "calibrated_sensor.json"),
            "measurement_method": "boundary separation projected onto the local road-normal direction",
            "quality_flags": sorted(set(quality_flags)), "failure_reason": None,
        }
        self.measurements[result["measurement_id"]] = result
        self.resources["cpu_seconds"] += time.process_time() - started
        return result

    def resource_snapshot(self) -> dict:
        return {**self.resources, "measurements_saved": len(self.measurements),
                "speed_evidence_saved": len(self.speed_evidence),
                "external_query_sources": sorted(set(
                    source for row in self.external_queries for source in (row["response"].get("source_url"),)
                    if source
                )), "external_queries": self.external_queries}
