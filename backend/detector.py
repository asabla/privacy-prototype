"""PII detection wrapper.

Uses OpenAI's `opf` (https://github.com/openai/privacy-filter) when installed.
Falls back to a regex-based heuristic detector that returns the same JSON
shape so the PoC runs out of the box. The frontend shows which engine is
active so the distinction is visible.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from importlib import import_module
from threading import Lock
from typing import Any


LABELS = [
    "private_person",
    "private_email",
    "private_phone",
    "private_address",
    "private_url",
    "private_date",
    "account_number",
    "secret",
]


@dataclass
class Span:
    label: str
    start: int
    end: int
    text: str
    placeholder: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "placeholder": self.placeholder,
        }


@dataclass
class DetectionResult:
    schema_version: int = 1
    engine: str = "heuristic"
    text: str = ""
    detected_spans: list[Span] = field(default_factory=list)
    redacted_text: str = ""

    @property
    def by_label(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self.detected_spans:
            counts[s.label] = counts.get(s.label, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "offset_unit": "unicode_code_points",
            "engine": self.engine,
            "summary": {
                "span_count": len(self.detected_spans),
                "by_label": self.by_label,
            },
            "text": self.text,
            "detected_spans": [s.to_dict() for s in self.detected_spans],
            "redacted_text": self.redacted_text,
        }


class Detector:
    """Detects PII. Prefers real `opf` if available, falls back to heuristic."""

    def __init__(self, engine: str = "auto") -> None:
        if engine not in {"auto", "heuristic", "opf"}:
            raise ValueError(f"Unknown detection engine: {engine}")
        self._opf = None
        self._inference_lock = Lock()
        self.engine = "heuristic"
        self.engine_detail = "Regex heuristic (demo mode)"
        if engine == "heuristic":
            return
        try:
            import_module("opf")
        except ModuleNotFoundError as exc:
            if exc.name != "opf":
                raise
            if engine == "opf":
                raise RuntimeError("OPF is required but is not installed. Run make install-opf.") from exc
            return

        from opf._api import OPF  # type: ignore[import-not-found]

        self._opf = OPF(device=os.environ.get("OPF_DEVICE", "cpu"))
        self.engine = "opf"
        self.engine_detail = "OpenAI Privacy Filter (opf)"

    def detect(self, text: str) -> DetectionResult:
        if self._opf is not None:
            # OPF lazily initializes its runtime and decoder on the first scan.
            with self._inference_lock:
                return self._detect_opf(text)
        return self._detect_heuristic(text)

    def _detect_opf(self, text: str) -> DetectionResult:
        raw = self._opf.redact(text).to_dict()  # type: ignore[union-attr]
        spans = [
            Span(
                label=s["label"],
                start=s["start"],
                end=s["end"],
                text=s["text"],
                placeholder=s.get("placeholder", f"[{s['label'].upper()}]"),
            )
            for s in raw.get("detected_spans", [])
        ]
        spans = _merge_overlapping_spans(text, spans)
        return DetectionResult(
            engine="opf",
            text=text,
            detected_spans=spans,
            redacted_text=_apply_redaction(text, spans),
        )

    def _detect_heuristic(self, text: str) -> DetectionResult:
        spans: list[Span] = []
        for label, pattern in HEURISTIC_PATTERNS:
            for match in pattern.finditer(text):
                group = 1 if pattern is _NAME_HINT else 0
                matched = match.group(group)
                spans.append(
                    Span(
                        label=label,
                        start=match.start(group),
                        end=match.end(group),
                        text=matched,
                        placeholder=f"[{label.upper()}]",
                    )
                )
        pruned = _merge_overlapping_spans(text, spans)

        redacted = _apply_redaction(text, pruned)
        return DetectionResult(
            engine="heuristic",
            text=text,
            detected_spans=pruned,
            redacted_text=redacted,
        )


def _merge_overlapping_spans(text: str, spans: list[Span]) -> list[Span]:
    """Preserve the union of every match, prioritizing secrets within overlaps."""
    merged: list[Span] = []
    cluster: list[Span] = []
    start = end = 0

    def flush() -> None:
        representative = min(
            cluster,
            key=lambda s: (s.label != "secret", -(s.end - s.start), s.start, s.label),
        )
        merged.append(Span(representative.label, start, end, text[start:end], representative.placeholder))

    for span in sorted(spans, key=lambda s: (s.start, s.end)):
        if not 0 <= span.start < span.end <= len(text):
            raise ValueError("Detector returned an invalid span range")
        if cluster and span.start >= end:
            flush()
            cluster = []
        if not cluster:
            start = span.start
            end = span.end
        else:
            end = max(end, span.end)
        cluster.append(span)
    if cluster:
        flush()
    return merged


def _apply_redaction(text: str, spans: list[Span]) -> str:
    out: list[str] = []
    cursor = 0
    for s in sorted(spans, key=lambda x: x.start):
        out.append(text[cursor:s.start])
        out.append(s.placeholder)
        cursor = s.end
    out.append(text[cursor:])
    return "".join(out)


# Heuristic patterns — intentionally broad. Real `opf` does far better.
# We bias for recall so the demo surfaces a realistic amount of PII.
_NAME_HINT = re.compile(
    r"\b(?:Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.|"
    r"I am|My name is|Regards,|Sincerely,|Best,|Cheers,|Thanks,|Thank you,|From:|To:|Dear)\s*"
    r"([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,2})"
)

_NAME_LOOSE = re.compile(r"\b[A-Z][a-z]{2,}[ \t]+[A-Z][a-z]{2,}\b")

HEURISTIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Secrets first — catch credentials and API-key shapes before generic rules.
    (
        "secret",
        re.compile(
            r"(?i)\b(?:sk-[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{20,}|"
            r"AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|"
            r"Bearer\s+[A-Za-z0-9._\-]{20,}|"
            r"(?:api[_-]?key|token|password|passwd|secret)\s*[:=]\s*[^\s,;]{6,})"
        ),
    ),
    (
        "account_number",
        re.compile(
            r"\b(?:"
            r"(?:\d[ -]?){13,19}"          # credit card-ish (13-19 digits)
            r"|\d{3}-\d{2}-\d{4}"           # US SSN
            r"|[A-Z]{2}\d{2}[A-Z0-9]{10,30}" # IBAN
            r"|\d{9,12}"                     # plain account/routing numbers
            r")\b"
        ),
    ),
    (
        "private_email",
        re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    ),
    (
        "private_phone",
        re.compile(
            r"(?:(?<=\s)|(?<=^))"
            r"(?:\+?\d{1,3}[\s.-]?)?"
            r"(?:\(\d{2,4}\)[\s.-]?|\d{2,4}[\s.-])"
            r"\d{3,4}[\s.-]?\d{3,4}"
            r"(?=[\s.,;:]|$)"
        ),
    ),
    (
        "private_url",
        re.compile(r"https?://[^\s<>\"']+"),
    ),
    (
        "private_date",
        re.compile(
            r"\b(?:"
            r"\d{4}-\d{2}-\d{2}"
            r"|\d{1,2}/\d{1,2}/\d{2,4}"
            r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}"
            r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}"
            r")\b"
        ),
    ),
    (
        "private_address",
        re.compile(
            r"\b\d{1,5}\s+[A-Z][A-Za-z.]+(?:\s+[A-Z][A-Za-z.]+){0,4}"
            r"\s+(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|"
            r"Lane|Ln\.?|Drive|Dr\.?|Court|Ct\.?|Way|Plaza|Terrace|Parkway|Pkwy\.?|Circle)\b"
            r"(?:,\s*(?:Apt\.?|Suite|Ste\.?|Unit)\s*\d+)?"
        ),
    ),
    ("private_person", _NAME_HINT),
    ("private_person", _NAME_LOOSE),
]


_detector: Detector | None = None
_detector_lock = Lock()


def get_detector() -> Detector:
    global _detector
    with _detector_lock:
        if _detector is None:
            _detector = Detector()
        return _detector
