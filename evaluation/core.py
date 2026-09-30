"""Score labelled spans and character coverage without retaining message text."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re

from backend.detector import LABELS, DetectionResult


@dataclass(frozen=True)
class Case:
    id: str
    text: str
    expected: tuple[tuple[str, int, int], ...]
    groups: tuple[str, ...] = ()


def load_cases(path: Path) -> tuple[list[Case], str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    if data.get("schema_version") != 1 or not data.get("cases"):
        raise ValueError("Expected a non-empty schema_version 1 evaluation dataset")
    cases = []
    seen = set()
    for item in data["cases"]:
        case_id = item["id"]
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError("Case IDs must be unique non-empty strings")
        seen.add(case_id)
        text = ""
        expected = []
        for segment in item["segments"]:
            if isinstance(segment, str):
                text += segment
                continue
            label, value = segment["label"], segment["text"]
            if label not in LABELS or not isinstance(value, str) or not value:
                raise ValueError(f"Invalid annotated segment in {case_id}")
            expected.append((label, len(text), len(text) + len(value)))
            text += value
        groups = item.get("groups", [])
        if (not isinstance(groups, list) or any(not isinstance(group, str)
                or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", group) for group in groups)
                or len(set(groups)) != len(groups)):
            raise ValueError(f"Invalid evaluation groups in {case_id}")
        cases.append(Case(case_id, text, tuple(expected), tuple(groups)))
    return cases, sha256(raw).hexdigest()


def metrics(tp: int, fp: int, fn: int) -> dict:
    return {
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "precision": round(tp / (tp + fp), 6) if tp + fp else None,
        "recall": round(tp / (tp + fn), 6) if tp + fn else None,
    }


def score_case(case: Case, result: DetectionResult) -> dict:
    if result.text != case.text:
        raise ValueError(f"Detector changed source text in {case.id}")
    predicted = set()
    cursor = 0
    redacted = []
    for span in result.detected_spans:
        if (span.label not in LABELS or not cursor <= span.start < span.end <= len(case.text)
                or span.text != case.text[span.start:span.end]):
            raise ValueError(f"Invalid detector span in {case.id}")
        redacted.extend((case.text[cursor:span.start], span.placeholder))
        cursor = span.end
        predicted.add((span.label, span.start, span.end))
    redacted.append(case.text[cursor:])
    if result.redacted_text != "".join(redacted):
        raise ValueError(f"Redacted output does not match detector spans in {case.id}")

    expected = set(case.expected)
    expected_chars = {i for _, start, end in expected for i in range(start, end)}
    predicted_chars = {i for _, start, end in predicted for i in range(start, end)}
    return {
        "id": case.id,
        **metrics(len(expected & predicted), len(predicted - expected), len(expected - predicted)),
        "sensitive_characters": len(expected_chars),
        "unredacted_sensitive_characters": len(expected_chars - predicted_chars),
        "extra_redacted_characters": len(predicted_chars - expected_chars),
        "by_label": {
            label: metrics(
                sum(s[0] == label for s in expected & predicted),
                sum(s[0] == label for s in predicted - expected),
                sum(s[0] == label for s in expected - predicted),
            )
            for label in LABELS
        },
    }


def evaluate(cases: list[Case], detector, dataset_digest: str) -> dict:
    scores = []
    for case in cases:
        result = detector.detect(case.text)
        if result.engine != detector.engine:
            raise ValueError(f"Detector changed engines in {case.id}")
        scores.append(score_case(case, result))
    counts = ("true_positives", "false_positives", "false_negatives")
    sensitive = sum(row["sensitive_characters"] for row in scores)
    uncovered = sum(row["unredacted_sensitive_characters"] for row in scores)
    report = {
        "schema_version": 1,
        "engine": detector.engine,
        "dataset_sha256": dataset_digest,
        "case_count": len(scores),
        "exact_spans": metrics(*(sum(row[key] for row in scores) for key in counts)),
        "redaction": {
            "sensitive_characters": sensitive,
            "unredacted_sensitive_characters": uncovered,
            "extra_redacted_characters": sum(row["extra_redacted_characters"] for row in scores),
            "sensitive_character_coverage": round((sensitive - uncovered) / sensitive, 6) if sensitive else None,
        },
        "by_label": {
            label: metrics(*(sum(row["by_label"][label][key] for row in scores) for key in counts))
            for label in LABELS
        },
        "cases": [{k: v for k, v in row.items() if k != "by_label"} for row in scores],
    }
    # A case can belong to multiple slices. Slice counts must not be added together.
    report["groups"] = {}
    for group in sorted({group for case in cases for group in case.groups}):
        rows = [score for case, score in zip(cases, scores) if group in case.groups]
        report["groups"][group] = {
            "case_count": len(rows),
            "exact_spans": metrics(*(sum(row[key] for row in rows) for key in counts)),
            "sensitive_characters": sum(row["sensitive_characters"] for row in rows),
            "unredacted_sensitive_characters": sum(row["unredacted_sensitive_characters"] for row in rows),
            "extra_redacted_characters": sum(row["extra_redacted_characters"] for row in rows),
        }
    return report


ERROR_COUNTS = ("false_positives", "false_negatives", "unredacted_sensitive_characters", "extra_redacted_characters")


def check_baseline(report: dict, baseline: dict) -> list[str]:
    """Prevent any individual case from worsening; improvements are allowed."""
    for key in ("schema_version", "engine", "dataset_sha256"):
        if report[key] != baseline.get(key):
            return [f"Baseline {key} does not match; review the dataset and baseline explicitly"]
    previous = {row["id"]: row for row in baseline["cases"]}
    if set(previous) != {row["id"] for row in report["cases"]}:
        return ["Baseline case IDs do not match"]
    return [
        f"{row['id']}: {key} increased from {previous[row['id']][key]} to {row[key]}"
        for row in report["cases"] for key in ERROR_COUNTS
        if row[key] > previous[row["id"]][key]
    ]
