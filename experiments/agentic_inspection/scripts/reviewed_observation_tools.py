#!/usr/bin/env python3
"""Read the current reviewed bbox decisions and observation ledger."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from project_common import load_config


class ReviewedObservationTools:
    def __init__(self) -> None:
        source = load_config()["source"]
        with Path(source["reviewed_bboxes"]).open(encoding="utf-8-sig", newline="") as handle:
            self.reviews = {row["observation_id"]: row for row in csv.DictReader(handle)}
        confirmations = json.loads(Path(source["expert_evidence_confirmations"]).read_text())["confirmations"]
        self.reviews.update({row["observation_id"]: row for row in confirmations})
        corrections = json.loads(Path(source["user_adjudications"]).read_text())["bbox_corrections"]
        self.corrections = {row["observation_id"]: row for row in corrections}
        for row in corrections:
            self.reviews[row["observation_id"]] = {
                **self.reviews.get(row["observation_id"], {}),
                "observation_id": row["observation_id"], "decision": row["decision"],
                "proposal_class": row["class_name"], "reviewer": row["reviewer"], "note": row["note"],
            }
        with Path(source["observation_ledger"]).open() as handle:
            self.ledger = {row["observation_id"]: row for row in map(json.loads, handle)}

    def get_reviewed_observations(self, ids: list[str]) -> dict:
        output = []
        for observation_id in ids:
            review, observation = self.reviews.get(observation_id), self.ledger.get(observation_id)
            if not review or not observation or review.get("decision") not in {
                "correct", "expert_confirmed", "user_confirmed"
            }:
                continue
            correction = self.corrections.get(observation_id)
            output.append({
                "observation_id": observation_id, "frame": observation["frame"],
                "camera": observation["channel"],
                "raw_device_id": observation.get("raw_device_id"),
                "refined_element_id": observation.get("refined_element_id"),
                "bbox": correction["bbox"] if correction else observation["bbox"],
                "reviewed_class": review.get("proposal_class") or review.get("class_name"),
                "human_bbox_review_status": review.get("decision"),
                "source_image": correction["source_image"] if correction else observation["source_image"],
                "review_note": review.get("note") or "Human confirmed class and usable 2D bbox only.",
            })
        return {
            "observations": output,
            "warning": "Accepted bbox review establishes class and 2D box usability, not semantics, physical identity, temporal state, or survey-grade geometry.",
        }
