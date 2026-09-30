"""Versioned minimization policies and transient, one-use review receipts."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from email.headerregistry import Address
from email.utils import getaddresses
from threading import Lock
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from backend.corpus import INTERNAL_DOMAINS
from backend.detector import LABELS, Detector, HEURISTIC_PATTERNS, Span, _apply_redaction, _merge_overlapping_spans
from backend.security import MAX_BODY_BYTES, MAX_TEXT_CHARS

POLICY_VERSION = "2026-09-30.1"
RECEIPT_TTL_SECONDS = 600
MAX_PENDING_REVIEWS = 256
MAX_FINDINGS = 512
UseCase = Literal["support_ticket", "ai_prompt", "email"]
FieldName = Literal["text", "sender", "recipients", "subject", "body"]
TextValue = Annotated[str, Field(max_length=MAX_TEXT_CHARS)]
CandidateValue = Annotated[str, Field(max_length=32_768)]
WARNINGS = [
    "Detection can miss sensitive content. Review every field before exporting.",
    "Placeholders reduce exposure; they do not guarantee anonymity.",
    "Nothing is sent to an email recipient or an external AI provider.",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManualMask(Contract):
    field: FieldName
    start: int = Field(strict=True, ge=0, le=MAX_TEXT_CHARS)
    end: int = Field(strict=True, ge=1, le=MAX_TEXT_CHARS)


class PrepareRequest(Contract):
    use_case: UseCase
    fields: dict[FieldName, TextValue] = Field(max_length=4)
    manual_masks: list[ManualMask] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def check_fields(self):
        expected = {"sender", "recipients", "subject", "body"} if self.use_case == "email" else {"text"}
        if set(self.fields) != expected or sum(map(len, self.fields.values())) > MAX_TEXT_CHARS:
            raise ValueError("Invalid fields or total input length")
        if not any(value.strip() for value in self.fields.values()):
            raise ValueError("Input is empty")
        for mask in self.manual_masks:
            if mask.field not in self.fields or not 0 <= mask.start < mask.end <= len(self.fields[mask.field]):
                raise ValueError("Invalid manual mask range")
        return self


class RoutingSummary(Contract):
    recipient_count: int = Field(strict=True, ge=1, le=20)
    crosses_example_boundary: StrictBool
    all_recipients_internal: StrictBool


class Candidate(Contract):
    use_case: UseCase
    policy_version: Literal["2026-09-30.1"] = POLICY_VERSION
    engine: Literal["heuristic", "opf"]
    fields: dict[FieldName, CandidateValue] = Field(max_length=4)
    routing: RoutingSummary | None = None


class ReceiptRequest(Contract):
    receipt: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ExportRequest(ReceiptRequest):
    candidate: Candidate
    confirmed: StrictBool

    @model_validator(mode="after")
    def require_review(self):
        if not self.confirmed:
            raise ValueError("Review confirmation required")
        return self


class ReviewError(Exception):
    """A constant, non-sensitive error code, never a model exception message."""

    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code
        super().__init__(code)


def _routing(fields: dict[str, str]) -> RoutingSummary:
    def parse(value: str) -> list[str]:
        if not value.strip() or any(c in value for c in "\r\n\x00"):
            raise ReviewError(422, "invalid_email_routing")
        try:
            pairs = getaddresses([value], strict=True)
            if not pairs or len(pairs) > 20:
                raise ValueError()
            addresses = [Address(addr_spec=addr) for _, addr in pairs]
            if any(not addr.username or not addr.domain for addr in addresses):
                raise ValueError()
            return [addr.domain.lower() for addr in addresses]
        except (ValueError, IndexError):
            raise ReviewError(422, "invalid_email_routing") from None

    senders, recipients = parse(fields["sender"]), parse(fields["recipients"])
    if len(senders) != 1:
        raise ReviewError(422, "invalid_email_routing")
    sender_internal = senders[0] in INTERNAL_DOMAINS
    internal = [domain in INTERNAL_DOMAINS for domain in recipients]
    return RoutingSummary(recipient_count=len(recipients),
                          crosses_example_boundary=any(sender_internal != value for value in internal),
                          all_recipients_internal=all(internal))


# Supplement model output with deterministic credential rules, including short and
# quoted assignments. These are policy safeguards, separate from model evaluation.
_CREDENTIAL_SHAPE = next(pattern for label, pattern in HEURISTIC_PATTERNS if label == "secret")
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|token|password|passwd|secret)\s*[:=]\s*"
    r"(?:\"[^\"\r\n]+\"|'[^'\r\n]+'|[^\s,;]+)"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:[A-Z]+ )?PRIVATE KEY-----|$)")


def prepare(req: PrepareRequest, detector: Detector) -> tuple[Candidate, list[dict], dict]:
    routing = _routing(req.fields) if req.use_case == "email" else None
    output: dict[str, str] = {}
    findings: list[dict] = []
    identities: dict[tuple[str, str], str] = {}
    counters: Counter = Counter()
    all_input = "\n".join(req.fields.values())
    field_order = ("sender", "recipients", "subject", "body") if req.use_case == "email" else ("text",)
    for field in field_order:
        text = req.fields[field]
        if field in ("sender", "recipients"):
            # Remove whole headers: names, addresses, comments, and routing syntax.
            output[field] = f"[{field.upper()}_REMOVED]"
            findings.append({"field": field, "label": "private_email", "start": 0, "end": len(text),
                             "placeholder": output[field], "sources": ["routing_policy"]})
            continue
        raw = detector.detect(text)
        if raw.text != text or raw.engine != detector.engine:
            raise ReviewError(503, "invalid_detector_result")
        spans = list(raw.detected_spans)
        if any(s.label not in LABELS or text[s.start:s.end] != s.text for s in spans):
            raise ReviewError(503, "invalid_detector_result")
        origins = [(s.start, s.end, "detector") for s in spans]
        for pattern in (_CREDENTIAL_SHAPE, _CREDENTIAL_ASSIGNMENT, _PRIVATE_KEY):
            for match in pattern.finditer(text):
                spans.append(Span("secret", match.start(), match.end(), match.group(), ""))
                origins.append((match.start(), match.end(), "credential_rule"))
        for mask in req.manual_masks:
            if mask.field == field:
                spans.append(Span("manual", mask.start, mask.end, text[mask.start:mask.end], ""))
                origins.append((mask.start, mask.end, "manual"))
        if len(spans) > MAX_FINDINGS:
            raise ReviewError(422, "too_many_findings")
        merged = _merge_overlapping_spans(text, spans)
        for span in merged:
            # Number within this request only. Never keep a reversible mapping server-side.
            identity = (span.label, text[span.start:span.end])
            if identity not in identities:
                while True:
                    counters[span.label] += 1
                    placeholder = f"[{span.label.upper()}_{counters[span.label]}]"
                    if placeholder not in all_input:
                        identities[identity] = placeholder
                        break
            span.placeholder = identities[identity]
            findings.append({"field": field, "label": span.label, "start": span.start, "end": span.end,
                             "placeholder": span.placeholder,
                             "sources": sorted({origin for start, end, origin in origins
                                                if start < span.end and end > span.start})})
        output[field] = _apply_redaction(text, merged)
    candidate = Candidate(use_case=req.use_case, engine=detector.engine, fields=output, routing=routing)
    # The exact candidate must fit back through the bounded export endpoint,
    # including when a client uses ASCII JSON escapes for Unicode characters.
    export_body = {"receipt": "x" * 43, "candidate": candidate.model_dump(), "confirmed": True}
    if len(json.dumps(export_body, ensure_ascii=True).encode()) > MAX_BODY_BYTES:
        raise ReviewError(422, "candidate_too_large")
    summary = {"span_count": len(findings), "by_label": dict(Counter(s["label"] for s in findings)),
               "manual_mask_count": len(req.manual_masks)}
    return candidate, findings, summary


@dataclass(frozen=True)
class PendingReview:
    fingerprint: bytes
    expires: float
    use_case: str
    engine: str
    span_count: int
    manual_mask_count: int


class ReviewStore:
    """Store only keyed fingerprints and metadata; no source or candidate text."""

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._key = secrets.token_bytes(32)
        self._pending: dict[str, PendingReview] = {}
        self._events: deque[dict] = deque(maxlen=128)
        self._lock = Lock()

    def _fingerprint(self, candidate: Candidate) -> bytes:
        body = json.dumps(candidate.model_dump(), sort_keys=True, ensure_ascii=True,
                          separators=(",", ":"), allow_nan=False).encode()
        return hmac.digest(self._key, body, hashlib.sha256)

    def _prune(self):
        now = self._clock()
        self._pending = {token: record for token, record in self._pending.items() if record.expires > now}

    def _event(self, action: str, record: PendingReview):
        self._events.append({"event_id": secrets.token_hex(12),
                             "at": datetime.now(timezone.utc).isoformat(),
                             "actor": "configured_operator", "action": action,
                             "use_case": record.use_case, "engine": record.engine,
                             "policy_version": POLICY_VERSION, "span_count": record.span_count,
                             "manual_mask_count": record.manual_mask_count})

    def issue(self, candidate: Candidate, summary: dict) -> str:
        with self._lock:
            self._prune()
            if len(self._pending) >= MAX_PENDING_REVIEWS:
                raise ReviewError(429, "review_capacity_reached")
            token = secrets.token_urlsafe(32)
            record = PendingReview(self._fingerprint(candidate), self._clock() + RECEIPT_TTL_SECONDS,
                                   candidate.use_case, candidate.engine, summary["span_count"],
                                   summary["manual_mask_count"])
            self._pending[token] = record
            self._event("prepared", record)
            return token

    def export(self, token: str, candidate: Candidate) -> dict:
        with self._lock:
            self._prune()
            record = self._pending.get(token)
            if record is None:
                raise ReviewError(410, "review_unavailable")
            if not hmac.compare_digest(record.fingerprint, self._fingerprint(candidate)):
                raise ReviewError(409, "candidate_changed")
            del self._pending[token]
            self._event("exported", record)
            return {"schema_version": 1, "reviewed": True, "candidate": candidate.model_dump(),
                    "notice": "Human-reviewed minimization; not a guarantee of anonymity."}

    def discard(self, token: str):
        with self._lock:
            self._prune()
            record = self._pending.pop(token, None)
            if record is not None:
                self._event("discarded", record)

    def events(self) -> list[dict]:
        with self._lock:
            self._prune()
            return list(self._events)

    def clear(self):
        with self._lock:
            self._pending.clear()
            self._events.clear()
            self._key = secrets.token_bytes(32)
