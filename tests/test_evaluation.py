from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.detector import DetectionResult, Detector, Span
from evaluation.core import Case, check_baseline, evaluate, load_cases, score_case
from evaluation.smoke import validate_scan


def test_annotations_follow_unicode_code_points_and_repeated_entities(tmp_path):
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps({"schema_version": 1, "cases": [{"id": "repeated", "segments": [
        "😀 ", {"label": "private_person", "text": "Alex"}, " and ",
        {"label": "private_person", "text": "Alex"},
    ]}]}))
    cases, digest = load_cases(dataset)
    assert cases == [Case("repeated", "😀 Alex and Alex", (("private_person", 2, 6), ("private_person", 11, 15)))]
    assert len(digest) == 64


@pytest.mark.parametrize("cases", [
    [],
    [{"id": "duplicate", "segments": []}, {"id": "duplicate", "segments": []}],
    [{"id": "unknown", "segments": [{"label": "invented", "text": "value"}]}],
    [{"id": "empty-annotation", "segments": [{"label": "secret", "text": ""}]}],
])
def test_invalid_annotations_fail(tmp_path, cases):
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps({"schema_version": 1, "cases": cases}))
    with pytest.raises(ValueError):
        load_cases(dataset)


def test_partial_and_wrong_label_matches_do_not_count_as_exact_detection():
    case = Case("partial", "abc def", (("secret", 0, 3), ("private_person", 4, 7)))
    scan = DetectionResult(text=case.text, detected_spans=[
        Span("secret", 0, 2, "ab", "[SECRET]"),
        Span("private_email", 4, 7, "def", "[PRIVATE_EMAIL]"),
    ], redacted_text="[SECRET]c [PRIVATE_EMAIL]")
    score = score_case(case, scan)
    assert (score["true_positives"], score["false_positives"], score["false_negatives"]) == (0, 2, 2)
    assert score["sensitive_characters"] == 6
    assert score["unredacted_sensitive_characters"] == 1
    assert score["extra_redacted_characters"] == 0


def test_over_redaction_and_empty_denominators_are_explicit():
    case = Case("negative", "a b", ())
    score = score_case(case, DetectionResult(text=case.text, detected_spans=[
        Span("private_person", 0, 3, "a b", "[PRIVATE_PERSON]")
    ], redacted_text="[PRIVATE_PERSON]"))
    assert score["false_positives"] == 1
    assert score["extra_redacted_characters"] == 3
    assert score["recall"] is None
    report = evaluate([Case("empty", "", ())], Detector(engine="heuristic"), "digest")
    assert report["exact_spans"]["precision"] is None
    assert report["redaction"]["sensitive_character_coverage"] is None


def test_claimed_spans_with_unredacted_output_fail_evaluation():
    case = Case("leak", "alice@example.com", (("private_email", 0, 17),))
    scan = DetectionResult(text=case.text, detected_spans=[
        Span("private_email", 0, 17, case.text, "[PRIVATE_EMAIL]")
    ], redacted_text=case.text)
    with pytest.raises(ValueError, match="Redacted output"):
        score_case(case, scan)


def test_baseline_checks_each_case_and_allows_improvements():
    baseline = {"schema_version": 1, "engine": "heuristic", "dataset_sha256": "digest", "cases": [
        {"id": "case", "false_positives": 1, "false_negatives": 1,
         "unredacted_sensitive_characters": 3, "extra_redacted_characters": 4}
    ]}
    report = deepcopy(baseline)
    report["cases"][0]["false_positives"] = 0
    assert check_baseline(report, baseline) == []
    report["cases"][0]["unredacted_sensitive_characters"] = 4
    assert check_baseline(report, baseline) == ["case: unredacted_sensitive_characters increased from 3 to 4"]
    report["dataset_sha256"] = "changed"
    assert "dataset_sha256" in check_baseline(report, baseline)[0]


def test_explicit_heuristic_does_not_import_opf(monkeypatch):
    def unexpected_import(name):
        raise AssertionError("Heuristic evaluation must not import the model")

    monkeypatch.setattr("backend.detector.import_module", unexpected_import)
    assert Detector(engine="heuristic").detect("hello").engine == "heuristic"


def test_explicit_opf_cannot_fall_back():
    with pytest.raises(RuntimeError, match="OPF is required"):
        Detector(engine="opf")
    with pytest.raises(ValueError, match="Unknown detection engine"):
        Detector(engine="typo")


def test_report_cannot_silently_mix_engines():
    detector = SimpleNamespace(engine="opf", detect=lambda text: DetectionResult(text=text, redacted_text=text))
    with pytest.raises(ValueError, match="changed engines"):
        evaluate([Case("empty", "", ())], detector, "digest")


def test_smoke_validation_rejects_heuristic_results():
    with pytest.raises(ValueError, match="Real OPF"):
        validate_scan(Detector(engine="heuristic").detect("hello").to_dict())


def test_reviewed_heuristic_baseline():
    root = Path(__file__).resolve().parents[1] / "evaluation"
    cases, digest = load_cases(root / "cases.json")
    baseline = json.loads((root / "heuristic-baseline.json").read_text())
    report = evaluate(cases, Detector(engine="heuristic"), digest)
    assert check_baseline(report, baseline) == []
