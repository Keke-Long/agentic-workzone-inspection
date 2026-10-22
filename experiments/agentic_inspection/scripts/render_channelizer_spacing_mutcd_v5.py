#!/usr/bin/env python3
"""Render the current MUTCD S/2S channelizer-spacing geometry audit."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt

from project_common import ROOT
from scene_data_tools_v5 import SceneDataToolsV5


def main() -> None:
    result = SceneDataToolsV5().audit_channelizer_spacing(30)
    summary = result["sequence_summaries"][0]
    gaps = summary["gaps"]
    coordinates = summary["device_road_coordinates"]
    stations = [row["station_m"] for row in coordinates]
    laterals = [row["lateral_m"] for row in coordinates]

    figure, axes = plt.subplots(2, 1, figsize=(13, 8), constrained_layout=True)
    axis = axes[0]
    for index, gap in enumerate(gaps):
        color = "#d95f02" if gap["channelization_region"] == "taper" else "#1b9e77"
        axis.plot(stations[index:index + 2], laterals[index:index + 2], color=color, linewidth=3)
    axis.scatter(stations, laterals, c="#202020", s=24, zorder=3, label="31 accepted physical devices")
    axis.set_xlabel("Road station (m)")
    axis.set_ylabel("Signed lateral offset from ego trajectory (m)")
    axis.set_title("Nearest continuous channelizer line: MUTCD region classification")
    axis.grid(alpha=0.25)
    axis.plot([], [], color="#d95f02", linewidth=3, label="Taper")
    axis.plot([], [], color="#1b9e77", linewidth=3, label="Tangent")
    axis.legend(loc="best")

    axis = axes[1]
    gap_numbers = list(range(1, len(gaps) + 1))
    values = [row["value_m"] for row in gaps]
    lowers = [row["confidence_interval_m"][0] for row in gaps]
    uppers = [row["confidence_interval_m"][1] for row in gaps]
    colors = ["#d95f02" if row["channelization_region"] == "taper" else "#1b9e77" for row in gaps]
    axis.bar(gap_numbers, values, color=colors, alpha=0.7, label="Estimated gap")
    axis.errorbar(gap_numbers, values,
                  yerr=[[value - low for value, low in zip(values, lowers)],
                        [high - value for value, high in zip(values, uppers)]],
                  fmt="none", ecolor="#333333", elinewidth=0.8, capsize=2)
    axis.axhline(result["thresholds"]["taper"]["value_m"], color="#d95f02", linestyle="--",
                 label="Taper limit: 30 ft (9.144 m)")
    axis.axhline(result["thresholds"]["tangent"]["value_m"], color="#1b9e77", linestyle="--",
                 label="Tangent limit: 60 ft (18.288 m)")
    axis.set_xlabel("Adjacent-device gap number")
    axis.set_ylabel("Gap distance (m)")
    axis.set_title("0/30 conservative gap intervals exceed the applicable MUTCD limit")
    axis.set_xticks(gap_numbers)
    axis.grid(axis="y", alpha=0.25)
    axis.legend(loc="upper left", ncol=2)

    figure.suptitle(
        "MUTCD 11th Ed. §6K.01 ¶04 channelizer-spacing audit — satisfied / no obvious spacing violation",
        fontsize=14,
    )
    output = ROOT / "figures/channelizer_spacing_mutcd_v5.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    audit_path = ROOT / "inputs/channelizer_spacing_mutcd_v5_audit.json"
    audit_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "figure": str(output), "audit": str(audit_path),
        "measurement_id": result["measurement_id"],
        "inspection_status": result["inspection_status"],
        "clear_exceedance_gap_count": result["clear_exceedance_gap_count"],
        "gaps_evaluated": result["gaps_evaluated"],
    }, indent=2))


if __name__ == "__main__":
    main()
