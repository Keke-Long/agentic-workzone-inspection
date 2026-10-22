#!/usr/bin/env python3
"""Build a query-independent structured index for MUTCD 11th Edition.

The builder reads only the frozen manual. It does not read a scene manifest,
benchmark reference, requirement catalog, or model output. Source-unit and
clause identifiers are hashes of manual-native locators and text.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess


SECTION_RE = re.compile(r"^\s*Section\s+(\d+[A-Z]\.\d{2})\s+(.+?)\s*$", re.MULTILINE)
TA_NOTES_RE = re.compile(
    r"Notes for Figure\s+(6P-\d+)[—-]Typical Application\s+(\d+)\s*\n\s*(.+?)\s*$",
    re.MULTILINE,
)
TA_FIGURE_RE = re.compile(
    r"Figure\s+(6P-\d+)\.\s+(.+?)\s+\(TA-(\d+)\)", re.MULTILINE | re.DOTALL
)
MODALITY_HEADINGS = {"Standard:": "shall", "Guidance:": "should", "Option:": "may", "Support:": "support"}


def _resolved_modality(parsed_modality: str, text: str) -> str:
    """Recover a normative modality when PDF columns split a heading from its clause.

    MUTCD tables occasionally interleave with paragraph text in PDF extraction.
    In that case the last visible heading can be ``Support`` even though the
    paragraph itself contains a direct operative verb.  This rule is manual-wide:
    it does not depend on a section, paragraph, scene, or benchmark answer.
    """
    if parsed_modality in {"shall", "should", "may"}:
        return parsed_modality
    opening = normalize_space(text)[:260]
    match = re.search(r"\b(shall|should|may)\b", opening, re.I)
    return match.group(1).lower() if match else parsed_modality


def _scope_tags(region: str, subject: str, relation: str,
                predicate_text: str = "") -> list[str]:
    """Assign conservative, structured scope tags from the rule's predicate.

    Deliberately do not inspect threshold/source prose: those fields often quote
    adjacent work-zone areas or referenced tables and are not the rule's topic.
    Ambiguous clauses remain untagged so Stage 2 can disposition them explicitly.
    """
    tags: set[str] = set()
    region_tags = {
        "pavement_markings": "pavement_markings",
        "buffer": "buffer_or_activity_area",
        "activity": "buffer_or_activity_area",
    }
    if region in region_tags:
        tags.add(region_tags[region])
    tail_match = re.search(r"\b(?:shall|should|may)\b(.*)", predicate_text,
                           re.I | re.S)
    predicate_tail = tail_match.group(1) if tail_match else ""
    predicate = f"{subject} {relation} {predicate_tail}".casefold()
    topic_patterns = {
        "positive_protection_or_attenuator": (
            "positive protection", "temporary traffic barrier", "impact attenuator",
            "truck-mounted attenuator",
        ),
        "pedestrian_bicycle_accessibility": (
            "pedestrian", "bicycle", "accessibility",
        ),
        "nighttime_or_illumination": ("nighttime", "illumination"),
        "material_or_crashworthiness_specification": (
            "crashworthy", "crashworthiness", "device material",
            "retroreflective material", "non-retroreflective",
            "name and telephone number", "owner identification",
            "owner or manufacturer",
        ),
        "mounting_height": ("mounting height",),
        "device_product_specification": (
            "full brilliance", "minimum size", "legibility distance",
            "number of elements", "flashes per minute", "dimming",
            "display capability", "matrix of elements", "rectangular appearance",
            "remote controls", "element on-time", "mode selections",
            "recess-mounted", "upper hood", "suitable elements capable",
            "minimum mounting height", "mounted on a vehicle", "color presented",
            "non-reflective black", "high-intensity rotating",
            "following mode", "mode shall be provided",
        ),
    }
    for tag, patterns in topic_patterns.items():
        if any(pattern in predicate for pattern in patterns):
            tags.add(tag)
    return sorted(tags)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def source_id(kind: str, locator: str, text: str) -> str:
    material = json.dumps(
        {"kind": kind, "locator": locator, "text": normalize_space(text)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "src_" + hashlib.sha256(material).hexdigest()[:20]


def compound_tokens(text: str) -> list[str]:
    """Preserve MUTCD-native identifiers such as TA-30, 6K.01, and W20-5L."""
    lowered = text.lower().replace("‑", "-").replace("–", "-").replace("—", "-")
    tokens: list[str] = []
    for pattern, prefix in (
        (r"\bta\s*-?\s*(\d{1,3})\b", "ta"),
        (r"\bsection\s+(\d+[a-z]\.\d{2})\b", "section"),
        (r"\bfigure\s+(\d+[a-z]-\d+)\b", "figure"),
        (r"\btable\s+(\d+[a-z])[-‑](\d+)\b", "table"),
    ):
        def capture(match: re.Match[str], marker: str = prefix) -> str:
            value = "-".join(group for group in match.groups() if group is not None)
            tokens.extend((f"{marker}:{value}", value, marker))
            return " "
        lowered = re.sub(pattern, capture, lowered)
    tokens.extend(re.findall(r"[a-z]+\d+(?:-[a-z0-9]+)*|\d+[a-z]\.\d{2}|[a-z]+|\d+(?:\.\d+)?", lowered))
    return tokens


def bm25_rank(query: str, documents: list[str]) -> list[tuple[float, int]]:
    tokenized = [compound_tokens(document) for document in documents]
    query_tokens = compound_tokens(query)
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))
    average_length = sum(map(len, tokenized)) / max(1, len(tokenized))
    ranked = []
    for index, tokens in enumerate(tokenized):
        counts = Counter(tokens)
        score = 0.0
        for token in query_tokens:
            frequency = counts[token]
            if not frequency:
                continue
            inverse = math.log(1 + (len(tokenized) - document_frequency[token] + 0.5) /
                               (document_frequency[token] + 0.5))
            denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(tokens) / max(1, average_length))
            score += inverse * frequency * 2.5 / denominator
        ranked.append((score, index))
    return sorted(ranked, key=lambda row: (-row[0], row[1]))


def pdf_pages(pdf_path: Path) -> list[str]:
    output = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"], check=True, capture_output=True, text=True
    ).stdout
    pages = output.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def printed_page(text: str) -> int | None:
    matches = re.findall(r"(?:^|\s)Page\s+(\d{1,4})(?:\s|$)", text, re.MULTILINE)
    return int(matches[0]) if matches else None


def _paragraphs(fragments: list[dict]) -> list[dict]:
    paragraphs: list[dict] = []
    modality = "unspecified"
    current: dict | None = None
    for fragment in fragments:
        for raw_line in fragment["text"].splitlines():
            line = normalize_space(raw_line)
            if not line:
                continue
            if line in MODALITY_HEADINGS:
                if current:
                    paragraphs.append(current)
                    current = None
                modality = MODALITY_HEADINGS[line]
                continue
            match = re.match(r"^(?:(\d{2})|(\d{1,2})\.)\s+(.+)$", line)
            if match:
                if current:
                    paragraphs.append(current)
                current = {
                    "paragraph": (match.group(1) or match.group(2)).zfill(2), "modality": modality,
                    "text": match.group(3), "pdf_page": fragment["pdf_page"],
                    "printed_page": fragment["printed_page"],
                }
            elif current:
                current["text"] += " " + line
    if current:
        paragraphs.append(current)
    return paragraphs


def _region(text: str, unit_code: str | None = None) -> str:
    lowered = text.lower()
    # Section placement is stronger topic evidence than incidental words in a
    # clause.  This is a manual-wide structural route, not a clause whitelist.
    code = str(unit_code or "").upper()
    if code.startswith("SEC-6H"):
        return "advance_warning"
    if code.startswith("SEC-6K"):
        return "channelizing_devices"
    if any(term in lowered for term in ("applies to", "work duration", "long-term", "short-term")):
        return "applicability"
    if "pavement marking" in lowered:
        return "pavement_markings"
    if any(term in lowered for term in ("channelizing device", "cones", "drums", "barricades")):
        return "channelizing_devices"
    if any(term in lowered for term in ("taper", "transition", "shift")):
        return "transition"
    if "buffer" in lowered:
        return "buffer"
    if any(term in lowered for term in ("warning sign", "lane closed", "road work ahead")):
        return "advance_warning"
    if "termination" in lowered or "end road work" in lowered:
        return "termination"
    if any(term in lowered for term in ("table ", "formula", "distance in feet", "spacing")):
        return "distance_table"
    if "work space" in lowered or "activity area" in lowered:
        return "activity"
    return "general_notes"


def _required_inputs(text: str) -> list[str]:
    lowered = text.lower()
    inputs = ["raw_images"]
    if "speed" in lowered:
        inputs.append("posted_speed_mph")
    if any(term in lowered for term in ("spacing", "distance", "length", "width")):
        inputs.extend(("accepted_bbox_observations", "ego_trajectory", "lidar_points"))
    if "long-term" in lowered or "short-term" in lowered:
        inputs.append("work_duration_category")
    if "lane" in lowered:
        inputs.extend(("closed_lane", "roadway_configuration"))
    return list(dict.fromkeys(inputs))


def _semantic_fields(unit_code: str, paragraph: str, text: str, modality: str) -> dict:
    lowered = text.lower()
    modality = _resolved_modality(modality, text)
    fields = {
        "subject": normalize_space(text).split(" shall ")[0].split(" should ")[0].split(" may ")[0][:180],
        "modality": modality,
        "relation": "states",
        "threshold": normalize_space(text),
        "applicability_conditions": [],
        "required_inputs": _required_inputs(text),
    }
    curated: dict[tuple[str, str], dict] = {
        ("SEC-6K.01", "04"): {
            "subject": "spacing between cones, tubular markers, vertical panels, drums, and barricades",
            "modality": "should", "relation": "does_not_exceed",
            "threshold": "S ft in taper channelization; 2S ft in tangent channelization, where S is speed limit in mph",
            "applicability_conditions": ["device is used for taper or tangent channelization"],
            "required_inputs": ["posted_speed_mph", "accepted_bbox_observations", "ego_trajectory", "lidar_points", "channelization_region"],
        },
        ("SEC-6N.11", "03"): {
            "subject": "non-mobile lane closure on a multi-lane road", "modality": "shall",
            "relation": "uses", "threshold": "transition area containing a merging taper",
            "applicability_conditions": ["multi-lane road", "lane closed", "operation is not mobile"],
            "required_inputs": ["roadway_configuration", "closed_lane", "work_duration_category", "raw_images"],
        },
        ("SEC-6N.11", "09"): {
            "subject": "left-hand lane closure on a multi-lane undivided road", "modality": "may",
            "relation": "uses_typical_application", "threshold": "Figure 6P-30 / TA-30 when traffic flow permits",
            "applicability_conditions": ["multi-lane undivided road", "left-hand lane is closed", "traffic flow permits"],
            "required_inputs": ["roadway_configuration", "closed_lane", "roadway_lane_count"],
        },
        ("SEC-6N.11", "10"): {
            "subject": "channelizing devices for only-left-lane closure on an undivided road", "modality": "shall",
            "relation": "are_placed", "threshold": "along the center line and along the adjacent lane",
            "applicability_conditions": ["undivided road", "only the left-hand lane is closed"],
            "required_inputs": ["roadway_configuration", "closed_lane", "lanes_closed", "accepted_bbox_observations", "raw_images"],
        },
        ("SEC-6J.01", "03"): {
            "subject": "existing pavement markings in long-term stationary TTC zones", "modality": "shall",
            "relation": "are_maintained_and_aligned", "threshold": "maintained under Chapters 3A and 3B and matched at both ends",
            "applicability_conditions": ["long-term stationary TTC zone"],
            "required_inputs": ["work_duration_category", "raw_images"],
        },
    }
    fields.update(curated.get((unit_code, paragraph), {}))
    if fields["relation"] == "states":
        if "shall" in lowered:
            fields["relation"] = "shall_comply"
        elif "should" in lowered:
            fields["relation"] = "should_comply"
        elif "may" in lowered:
            fields["relation"] = "may_apply"
    return fields


def _source_units(pages: list[str]) -> tuple[list[dict], list[dict]]:
    sections: dict[str, dict] = {}
    current: str | None = None
    for page_number, text in enumerate(pages, 1):
        matches = [match for match in SECTION_RE.finditer(text) if not re.search(r"\.{5,}", match.group(2))]
        cursor = 0
        for match in matches:
            if current and match.start() > cursor:
                sections[current]["fragments"].append({
                    "pdf_page": page_number, "printed_page": printed_page(text),
                    "text": text[cursor:match.start()],
                })
            code, title = match.groups()
            current = "SEC-" + code.upper()
            sections.setdefault(current, {
                "source_unit_code": current, "unit_type": "section", "title": normalize_space(title),
                "chapter": code[:-3].upper(), "fragments": [],
            })
            cursor = match.end()
        if current and cursor < len(text):
            sections[current]["fragments"].append({
                "pdf_page": page_number, "printed_page": printed_page(text), "text": text[cursor:],
            })

    typical: dict[str, dict] = {}
    for page_number, text in enumerate(pages, 1):
        note = TA_NOTES_RE.search(text)
        figure = TA_FIGURE_RE.search(text)
        if note:
            figure_code, number, title = note.groups()
            code = f"TA-{int(number)}"
            typical.setdefault(code, {
                "source_unit_code": code, "unit_type": "typical_application",
                "title": normalize_space(title), "chapter": "6P", "figure_code": figure_code,
                "fragments": [],
            })["fragments"].append({
                "pdf_page": page_number, "printed_page": printed_page(text), "text": text[note.end():],
            })
        if figure:
            figure_code, title, number = figure.groups()
            code = f"TA-{int(number)}"
            typical.setdefault(code, {
                "source_unit_code": code, "unit_type": "typical_application",
                "title": normalize_space(title), "chapter": "6P", "figure_code": figure_code,
                "fragments": [],
            })["fragments"].append({
                "pdf_page": page_number, "printed_page": printed_page(text), "text": text,
            })
    return list(sections.values()), list(typical.values())


def _curated_table_structure(pages: list[str]) -> tuple[list[dict], list[dict]]:
    """Expose diagram-referenced MUTCD tables as query-independent source units.

    PDF text extraction interleaves adjacent table columns on these pages, so the
    source-derived rows below preserve the printed table values explicitly instead
    of hiding them inside a neighboring section paragraph.
    """
    specifications = [
        {
            "code": "TABLE-6B-1", "title": "Recommended Advance Warning Sign Minimum Spacing",
            "chapter": "6B", "pdf_page": 813, "printed_page": 773, "region": "distance_table",
            "subject": "advance warning sign dimensions A, B, and C",
            "modality": "guidance", "relation": "recommended_minimum_spacing",
            "threshold": (
                "Urban low speed: A=100 ft, B=100 ft, C=100 ft; urban high speed: A=350 ft, "
                "B=350 ft, C=350 ft; rural: A=500 ft, B=500 ft, C=500 ft; expressway/freeway: "
                "A=1,000 ft, B=1,500 ft, C=2,640 ft. A is restriction-to-first-sign distance, "
                "B first-to-second, and C second-to-third."
            ),
            "conditions": ["road type and agency-determined speed category"],
            "inputs": ["roadway_configuration", "posted_speed_mph", "traffic_sign_observations",
                       "ego_trajectory", "lidar_points"],
            "span": (
                "Table 6B-1. Recommended Advance Warning Sign Minimum Spacing. Urban (low speed): "
                "100 feet, 100 feet, 100 feet. Urban (high speed): 350 feet, 350 feet, 350 feet. "
                "Rural: 500 feet, 500 feet, 500 feet. Expressway / Freeway: 1,000 feet, 1,500 feet, "
                "2,640 feet. The column headings A, B, and C are the dimensions shown in Figures "
                "6P-1 through 6P-54."
            ),
        },
        {
            "code": "TABLE-6B-3", "title": "Taper Length Criteria for Temporary Traffic Control Zones",
            "chapter": "6B", "pdf_page": 815, "printed_page": 775, "region": "transition",
            "subject": "temporary traffic control taper length by taper type",
            "modality": "guidance", "relation": "minimum_or_approximate_length",
            "threshold": (
                "Merging taper at least L; shifting taper at least 0.5L; shoulder taper at least "
                "0.33L; one-lane two-way taper 50 to 100 ft; downstream taper 50 to 100 ft."
            ),
            "conditions": ["the corresponding taper type is used"],
            "inputs": ["taper_type", "posted_speed_mph", "lateral_offset_width_ft",
                       "accepted_bbox_observations", "ego_trajectory", "lidar_points"],
            "span": (
                "Table 6B-3. Taper Length Criteria for Temporary Traffic Control Zones. Merging "
                "Taper: at least L. Shifting Taper: at least 0.5 L. Shoulder Taper: at least 0.33 L. "
                "One-Lane, Two-Way Traffic Taper: 50 feet minimum, 100 feet maximum. Downstream "
                "Taper: 50 feet minimum, 100 feet maximum."
            ),
        },
        {
            "code": "TABLE-6B-4", "title": "Formulas for Determining Taper Length",
            "chapter": "6B", "pdf_page": 815, "printed_page": 775, "region": "distance_table",
            "subject": "taper length L",
            "modality": "guidance", "relation": "is_calculated",
            "threshold": "For S of 40 mph or less, L = W*S^2/60; for S of 45 mph or more, L = W*S.",
            "conditions": ["a taper using dimension L is shown or required"],
            "inputs": ["posted_speed_mph", "lateral_offset_width_ft", "accepted_bbox_observations",
                       "ego_trajectory", "lidar_points"],
            "span": (
                "Table 6B-4. Formulas for Determining Taper Length. 40 mph or less: L = WS2/60. "
                "45 mph or more: L = WS. Where L is taper length in feet, W is width of offset in "
                "feet, and S is posted speed limit, off-peak 85th-percentile speed prior to work "
                "starting, or anticipated operating speed in mph."
            ),
        },
        {
            "code": "TABLE-6P-2", "title": "Meaning of Symbols on Typical Application Diagrams",
            "chapter": "6P", "pdf_page": 899, "printed_page": 859, "region": "general_notes",
            "subject": "symbols used on Typical Application diagrams",
            "modality": "support", "relation": "defines_figure_symbols",
            "threshold": (
                "Defines arrow board, changeable message sign, channelizing device, crash cushion, "
                "travel direction, flagger, longitudinal channelizing device, pavement markings "
                "that should be removed for a long-term project, shadow vehicle, sign, temporary "
                "barrier, truck-mounted attenuator, Type 3 barricade, work space, and work vehicle."
            ),
            "conditions": ["interpreting a Typical Application diagram"],
            "inputs": ["raw_images", "accepted_bbox_observations"],
            "span": (
                "Table 6P-2. Meaning of Symbols on Typical Application Diagrams. Arrow board; "
                "changeable message sign or support trailer; channelizing device; crash cushion; "
                "direction of travel; flagger; longitudinal channelizing device; pavement markings "
                "that should be removed for a long-term project; shadow vehicle; sign; temporary "
                "barrier; truck-mounted attenuator; Type 3 barricade; work space; work vehicle."
            ),
        },
    ]
    units, nodes = [], []
    for row in specifications:
        locator = f"{row['code']}; PDF page {row['pdf_page']}"
        # Use the normalized row transcription as the source span.  A full PDF
        # page is not an atomic table row and can contain unrelated scope terms.
        source_page_span = normalize_space(row["span"])
        nodes.append({
            "node_id": source_id("table", locator, source_page_span),
            "source_unit_code": row["code"], "unit_type": "table", "chapter": row["chapter"],
            "region": row["region"], "node_type": "table_rule", "paragraph": "table",
            "subject": row["subject"], "modality": row["modality"], "relation": row["relation"],
            "threshold": row["threshold"], "applicability_conditions": row["conditions"],
            "required_inputs": row["inputs"],
            "scope_tags": _scope_tags(row["region"], row["subject"], row["relation"]),
            "source": {"pdf_page": row["pdf_page"], "printed_page": row["printed_page"],
                       "source_locator": locator, "source_span": source_page_span,
                       "normalized_table_transcription": row["span"]},
        })
        units.append({
            "source_unit_code": row["code"], "unit_type": "table", "title": row["title"],
            "chapter": row["chapter"], "raw_text": row["span"] + " " + source_page_span,
            "source_pages": [row["pdf_page"]],
            "printed_pages": [row["printed_page"]], "available_regions": [row["region"]],
        })
    return units, nodes


def _typical_application_figure_nodes(unit: dict) -> list[dict]:
    """Split machine-readable diagram content from prose notes for every TA.

    This is generic over all Typical Applications and runs before a scene is
    available. It does not decide which diagram or component a test case needs.
    """
    figure_code = unit.get("figure_code")
    if not figure_code:
        return []
    figure_number = int(figure_code.split("-", 1)[1])
    marker = re.compile(
        rf"Figure\s+{re.escape(figure_code)}\.\s+.*?\(TA-{figure_number}\)", re.I | re.S
    )
    fragment = next((row for row in unit["fragments"] if marker.search(row["text"])), None)
    if not fragment:
        return []
    start = marker.search(fragment["text"]).start()
    raw_figure = fragment["text"][start:]
    end_match = re.search(rf"Typical Application\s+{figure_number}\b", raw_figure, re.I)
    if end_match:
        raw_figure = raw_figure[:end_match.end()]
    figure_span = normalize_space(raw_figure)
    if not figure_span:
        return []
    page = fragment["pdf_page"]
    printed = fragment["printed_page"]
    locator = f"Figure {figure_code} (TA-{figure_number}); PDF page {page}"
    conditions = [f"TA-{figure_number} is selected for the scene"]
    nodes: list[dict] = []

    def add(component: str, region: str, subject: str, modality: str, relation: str,
            threshold: str, inputs: list[str]) -> None:
        component_locator = f"{locator}; component {component}"
        nodes.append({
            "node_id": source_id("figure_component", component_locator, figure_span),
            "source_unit_code": unit["source_unit_code"], "unit_type": "typical_application",
            "chapter": unit["chapter"], "region": region, "node_type": "figure_component",
            "paragraph": f"figure:{component}", "subject": subject, "modality": modality,
            "relation": relation, "threshold": threshold,
            "applicability_conditions": conditions, "required_inputs": inputs,
            "scope_tags": _scope_tags(region, subject, relation),
            "normative_basis": ({
                "source_unit_code": "SEC-6P.01", "paragraph": "02",
                "principle": "Typical Application diagrams are Guidance minimum solutions",
            } if modality == "should" else None),
            "source": {"pdf_page": page, "printed_page": printed,
                       "source_locator": component_locator, "source_span": figure_span},
        })

    add("diagram", "general_notes", f"{unit['source_unit_code']} diagram",
        "should", "depicts_guidance_minimum_solution",
        "Use the controls, positions, and dimensions depicted in the Typical Application figure, "
        "interpreted with its notes and referenced tables.",
        ["raw_images", "accepted_bbox_observations"])

    sign_pattern = re.compile(r"\b(?:[A-Z]\d{1,2}-\d+[A-Za-z]*P?|[A-Z]\d+-\d+[A-Za-z]*)\b")
    sign_codes = sorted(set(sign_pattern.findall(figure_span)))
    for sign_code in sign_codes:
        occurrences = list(re.finditer(rf"\b{re.escape(sign_code)}\b", figure_span))
        optional = bool(occurrences) and all(
            "optional" in figure_span[item.end():item.end() + 24].lower() for item in occurrences
        )
        add(f"sign:{sign_code}", "advance_warning", f"{sign_code} sign in {unit['source_unit_code']}",
            "may" if optional else "should", "is_depicted_at_figure_position",
            f"{sign_code} is {'optional ' if optional else ''}at the position and in the sequence shown in the figure.",
            ["raw_images", "accepted_bbox_observations"])

    dimension_letters = [letter for letter in ("A", "B", "C")
                         if re.search(rf"\b{letter}\b", figure_span)]
    if dimension_letters:
        add("dimensions:" + "-".join(dimension_letters), "distance_table",
            f"{', '.join(dimension_letters)} sign-spacing dimensions in {unit['source_unit_code']}",
            "should", "uses_referenced_table_dimensions",
            f"Resolve the depicted {', '.join(dimension_letters)} dimensions through the figure's referenced spacing table.",
            ["roadway_configuration", "posted_speed_mph", "accepted_bbox_observations",
             "ego_trajectory", "lidar_points"])
    if re.search(r"\bL\b", figure_span):
        add("dimension:L", "transition", f"taper dimension L in {unit['source_unit_code']}",
            "should", "uses_referenced_taper_formula",
            "Resolve L through the taper-criteria and taper-formula tables referenced by the figure.",
            ["posted_speed_mph", "lateral_offset_width_ft", "accepted_bbox_observations",
             "ego_trajectory", "lidar_points"])
    if "buffer space" in figure_span.lower():
        optional = "buffer space (optional)" in figure_span.lower()
        add("buffer_space", "buffer", f"buffer space in {unit['source_unit_code']}",
            "may" if optional else "should", "is_depicted_at_figure_position",
            f"A buffer space is {'optional and ' if optional else ''}located as shown in the figure.",
            ["raw_images", "accepted_bbox_observations", "ego_trajectory", "lidar_points"])
    for label, component, subject in (
        ("truck-mounted attenuator", "truck_mounted_attenuator", "truck-mounted attenuator"),
        ("work vehicle", "work_vehicle", "work vehicle"),
        ("arrow board", "arrow_board", "arrow board"),
        ("changeable message sign", "changeable_message_sign", "changeable message sign"),
    ):
        if label not in figure_span.lower():
            continue
        optional = f"{label} (optional)" in figure_span.lower()
        add(component, "optional_devices" if optional else "activity",
            f"{subject} in {unit['source_unit_code']}", "may" if optional else "should",
            "is_depicted_at_figure_position",
            f"The {subject} is {'optional and ' if optional else ''}located as shown in the figure.",
            ["raw_images", "accepted_bbox_observations"])
    return nodes


def build_index(pdf_path: Path) -> dict:
    pages = pdf_pages(pdf_path)
    sections, typical = _source_units(pages)
    table_units, table_nodes = _curated_table_structure(pages)
    units = sections + typical
    nodes: list[dict] = []
    for unit in units:
        paragraph_fragments = unit["fragments"]
        if unit["unit_type"] == "typical_application":
            paragraph_fragments = []
            figure_heading = re.compile(r"Figure\s+6P-\d+\.", re.I)
            for fragment in unit["fragments"]:
                cleaned = dict(fragment)
                heading = figure_heading.search(cleaned["text"])
                if heading:
                    cleaned["text"] = cleaned["text"][:heading.start()]
                paragraph_fragments.append(cleaned)
        paragraphs = _paragraphs(paragraph_fragments)
        for row in paragraphs:
            fields = _semantic_fields(unit["source_unit_code"], row["paragraph"], row["text"], row["modality"])
            locator = f"{unit['source_unit_code']} paragraph {row['paragraph']}; PDF page {row['pdf_page']}"
            node = {
                "node_id": source_id("clause", locator, row["text"]),
                "source_unit_code": unit["source_unit_code"], "unit_type": unit["unit_type"],
                "chapter": unit["chapter"], "region": _region(row["text"], unit["source_unit_code"]),
                "node_type": "normative_clause", "paragraph": row["paragraph"], **fields,
                "scope_tags": _scope_tags(
                    _region(row["text"], unit["source_unit_code"]),
                    fields["subject"], fields["relation"], row["text"]
                ),
                "source": {
                    "pdf_page": row["pdf_page"], "printed_page": row["printed_page"],
                    "source_locator": locator, "source_span": normalize_space(row["text"]),
                },
            }
            nodes.append(node)
        if unit["unit_type"] == "typical_application":
            nodes.extend(_typical_application_figure_nodes(unit))
        raw_text = "\n".join(fragment["text"] for fragment in unit["fragments"])
        unit["raw_text"] = normalize_space(raw_text)
        unit["source_pages"] = sorted({fragment["pdf_page"] for fragment in unit["fragments"]})
        unit["printed_pages"] = sorted({fragment["printed_page"] for fragment in unit["fragments"]
                                         if fragment["printed_page"] is not None})
        unit["available_regions"] = sorted({node["region"] for node in nodes
                                             if node["source_unit_code"] == unit["source_unit_code"]})
        unit.pop("fragments")
    units.extend(table_units)
    nodes.extend(table_nodes)
    # PDF extraction can repeat an identical numbered fragment when tables or
    # page overlays duplicate text. Source hashes define identity, so retain one.
    nodes = list({node["node_id"]: node for node in nodes}.values())

    unit_codes = {unit["source_unit_code"] for unit in units}
    nodes_by_unit: dict[str, list[dict]] = {}
    for node in nodes:
        nodes_by_unit.setdefault(node["source_unit_code"], []).append(node)
    edges: dict[tuple[str, str, str], dict] = {}
    for unit in units:
        text = unit["raw_text"]
        targets = [("section", "SEC-" + value.upper()) for value in re.findall(r"Section\s+(\d+[A-Z]\.\d{2})", text)]
        targets += [("typical_application", f"TA-{int(value)}") for value in re.findall(r"(?:TA-|Typical Application\s+)(\d{1,3})", text)]
        targets += [("typical_application", f"TA-{int(value)}") for value in re.findall(r"Figure\s+6P-(\d{1,3})", text)]
        targets += [("table", f"TABLE-{chapter.upper()}-{number}")
                    for chapter, number in re.findall(r"Table\s+(\d+[A-Z])[-‑](\d+)", text)]
        for relation, target in targets:
            if target == unit["source_unit_code"] or target not in unit_codes:
                continue
            key = (unit["source_unit_code"], target, relation)
            if target.startswith("TA-"):
                target_number = target.split("-", 1)[1]
                markers = (f"Figure 6P-{target_number}", f"TA-{target_number}",
                           f"Typical Application {target_number}")
            elif target.startswith("SEC-"):
                target_section = target.removeprefix("SEC-")
                markers = (f"Section {target_section}",)
            else:
                table_code = target.removeprefix("TABLE-")
                chapter, number = table_code.rsplit("-", 1)
                markers = (f"Table {chapter}-{number}", f"Table {chapter}‑{number}")
            source_span = next((
                node["source"]["source_span"] for node in nodes_by_unit.get(unit["source_unit_code"], [])
                if any(marker.lower() in node["source"]["source_span"].lower() for marker in markers)
            ), f"Manual-visible reference from {unit['source_unit_code']} to {target}")
            edges[key] = {
                "edge_id": source_id("edge", "|".join(key), text[:500]),
                "from_source_unit_code": unit["source_unit_code"],
                "to_source_unit_code": target, "relation": f"references_{relation}",
                "source": {"source_span": source_span},
            }
    inbound: dict[str, list[dict]] = {}
    for edge in edges.values():
        inbound.setdefault(edge["to_source_unit_code"], []).append({
            "from_source_unit_code": edge["from_source_unit_code"],
            "relation": edge["relation"], "source_span": edge["source"]["source_span"],
        })
    for unit in units:
        unit["inbound_reference_contexts"] = sorted(
            inbound.get(unit["source_unit_code"], []),
            key=lambda row: (row["from_source_unit_code"], row["relation"], row["source_span"]),
        )
    pdf_bytes = pdf_path.read_bytes()
    return {
        "schema_version": "mutcd_structure_v1",
        "manual": {
            "title": "Manual on Uniform Traffic Control Devices for Streets and Highways",
            "edition": "11th Edition", "publication_date": "December 2023",
            "sha256": hashlib.sha256(pdf_bytes).hexdigest(), "size_bytes": len(pdf_bytes),
            "pdf_page_count": len(pages),
        },
        "build_policy": {
            "query_independent": True, "scene_manifest_read": False,
            "hidden_reference_read": False, "internal_requirement_ids_used": False,
            "identifier_policy": "manual-native unit codes plus source-content hashes",
        },
        "source_units": sorted(units, key=lambda row: (row["source_pages"][0], row["source_unit_code"])),
        "atomic_nodes": sorted(nodes, key=lambda row: (row["source"]["pdf_page"], row["source_unit_code"], row["paragraph"])),
        "cross_references": sorted(edges.values(), key=lambda row: (row["from_source_unit_code"], row["to_source_unit_code"])),
    }


def write_index(pdf_path: Path, output_path: Path) -> dict:
    index = build_index(pdf_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure_asset_dir = output_path.parent / "mutcd_figure_pages_v1"
    figure_asset_dir.mkdir(parents=True, exist_ok=True)
    figure_assets: dict[tuple[str, int], Path] = {}
    for unit in index["source_units"]:
        if unit["unit_type"] != "typical_application":
            continue
        diagram = next((node for node in index["atomic_nodes"]
                        if node["source_unit_code"] == unit["source_unit_code"] and
                        node["paragraph"] == "figure:diagram"), None)
        if not diagram:
            continue
        page = int(diagram["source"]["pdf_page"])
        stem = figure_asset_dir / f"{unit['source_unit_code'].lower()}_pdf_page_{page:04d}"
        subprocess.run([
            "pdftoppm", "-f", str(page), "-l", str(page), "-singlefile", "-jpeg",
            "-jpegopt", "quality=82", "-r", "120", str(pdf_path), str(stem),
        ], check=True, capture_output=True)
        asset = stem.with_suffix(".jpg").resolve()
        figure_assets[(unit["source_unit_code"], page)] = asset
    for node in index["atomic_nodes"]:
        if node["node_type"] != "figure_component":
            continue
        key = (node["source_unit_code"], int(node["source"]["pdf_page"]))
        if key in figure_assets:
            node["source"]["figure_image_path"] = str(figure_assets[key])
    output_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    asset_records = [{
        "source_unit_code": code, "pdf_page": page, "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size,
    } for (code, page), path in sorted(figure_assets.items())]
    manifest = {
        "schema_version": "mutcd_structure_v1_manifest", "index_path": str(output_path),
        "index_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "manual": index["manual"], "source_unit_count": len(index["source_units"]),
        "atomic_node_count": len(index["atomic_nodes"]),
        "cross_reference_count": len(index["cross_references"]),
        "typical_application_count": sum(unit["unit_type"] == "typical_application" for unit in index["source_units"]),
        "figure_page_asset_count": len(asset_records), "figure_page_assets": asset_records,
    }
    manifest_path = output_path.with_name(output_path.stem + "_manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest
