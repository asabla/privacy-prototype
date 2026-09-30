import sys
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import permutations
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

import backend.detector as module
from backend.detector import Detector, Span, _merge_overlapping_spans


@pytest.mark.parametrize("separator", ["\n", " "])
def test_name_overlap_cannot_expose_credential(separator):
    # Deliberately synthetic credential text.
    text = f"Regards,{separator}Alice Smith{separator}Password=example-value"
    result = Detector().detect(text)
    assert "example-value" not in result.redacted_text
    assert any(span.label == "secret" for span in result.detected_spans)


def test_transitive_overlaps_preserve_all_covered_characters():
    text = "abcdefghijklmno"
    matches = [
        Span("private_person", 0, 5, text[:5], "[PRIVATE_PERSON]"),
        Span("private_email", 3, 9, text[3:9], "[PRIVATE_EMAIL]"),
        Span("secret", 8, 12, text[8:12], "[SECRET]"),
        Span("private_date", 12, 15, text[12:], "[PRIVATE_DATE]"),
    ]
    for order in permutations(matches):
        spans = _merge_overlapping_spans(text, list(order))
        assert [(s.start, s.end, s.label) for s in spans] == [
            (0, 12, "secret"), (12, 15, "private_date")
        ]
        assert all(s.text == text[s.start:s.end] for s in spans)


@pytest.mark.parametrize("start,end", [(-1, 2), (2, 2), (0, 4)])
def test_invalid_model_offsets_fail_instead_of_exposing_text(start, end):
    with pytest.raises(ValueError, match="invalid span"):
        _merge_overlapping_spans("abc", [Span("secret", start, end, "", "[SECRET]")])


def test_unicode_offset_contract():
    text = "😀 alice@example.com 👩🏽‍💻"
    result = Detector().detect(text)
    assert result.redacted_text == "😀 [PRIVATE_EMAIL] 👩🏽‍💻"
    assert result.to_dict()["offset_unit"] == "unicode_code_points"
    assert [(s.start, s.end, s.text) for s in result.detected_spans] == [
        (2, 19, "alice@example.com")
    ]


def test_name_hint_leaves_greeting_and_next_line_intact():
    result = Detector().detect("Regards,\nAlice Smith\nTomorrow")
    assert result.redacted_text == "Regards,\n[PRIVATE_PERSON]\nTomorrow"


def test_concurrent_calls_share_one_detector(monkeypatch):
    start = Barrier(8)
    created = []

    def factory():
        instance = object()
        created.append(instance)
        time.sleep(0.03)  # Release the GIL during the simulated model load.
        return instance

    def get():
        start.wait(timeout=5)
        return module.get_detector()

    monkeypatch.setattr(module, "Detector", factory)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: get(), range(8)))
    assert len(created) == 1
    assert all(result is created[0] for result in results)


def test_opf_lazy_runtime_and_inference_are_serialized(monkeypatch):
    lock = Lock()
    active = peak = 0
    devices = []

    class FakeOPF:
        def __init__(self, *, device):
            devices.append(device)

        def redact(self, text):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return SimpleNamespace(to_dict=lambda: {
                "detected_spans": [], "redacted_text": text
            })

    monkeypatch.delenv("OPF_DEVICE", raising=False)
    monkeypatch.setitem(sys.modules, "opf", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "opf._api", SimpleNamespace(OPF=FakeOPF))
    detector = Detector()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(detector.detect, ["hello"] * 8))
    assert peak == 1
    assert devices == ["cpu"]
    assert all(result.engine == "opf" for result in results)


def test_opf_device_can_be_selected(monkeypatch):
    devices = []
    monkeypatch.setenv("OPF_DEVICE", "cuda")
    monkeypatch.setitem(sys.modules, "opf", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "opf._api", SimpleNamespace(
        OPF=lambda **kwargs: devices.append(kwargs["device"]) or object()
    ))
    assert Detector().engine == "opf"
    assert devices == ["cuda"]


def test_broken_opf_does_not_silently_select_heuristics(monkeypatch):
    def broken_opf(**kwargs):
        raise RuntimeError("Invalid OPF configuration")

    monkeypatch.setitem(sys.modules, "opf", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "opf._api", SimpleNamespace(OPF=broken_opf))
    with pytest.raises(RuntimeError, match="Invalid OPF configuration"):
        Detector()


def test_installed_opf_missing_its_api_does_not_select_heuristics(monkeypatch):
    monkeypatch.setitem(sys.modules, "opf", SimpleNamespace())
    with pytest.raises(ModuleNotFoundError):
        Detector()


def test_opf_overlaps_use_the_same_safe_redaction_contract(monkeypatch):
    text = "abcdefghijkl"
    spans = [
        Span("private_person", 0, 5, text[:5], "[PRIVATE_PERSON]"),
        Span("secret", 3, 12, text[3:], "[SECRET]"),
    ]
    fake_opf = SimpleNamespace(redact=lambda _: SimpleNamespace(to_dict=lambda: {
        "detected_spans": [span.to_dict() for span in spans],
        "redacted_text": "upstream rendering must not bypass normalization",
    }))
    monkeypatch.setitem(sys.modules, "opf", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "opf._api", SimpleNamespace(OPF=lambda **_: fake_opf))
    result = Detector().detect(text)
    assert result.engine == "opf"
    assert result.redacted_text == "[SECRET]"
    assert result.by_label == {"secret": 1}
    assert result.detected_spans[0].text == text
