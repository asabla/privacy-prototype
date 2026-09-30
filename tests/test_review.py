import copy
import json
import secrets
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.detector import DetectionResult, Detector, Span
from backend.main import create_app
from backend.review import (
    MAX_PENDING_REVIEWS, RECEIPT_TTL_SECONDS, PrepareRequest,
    ReviewError, ReviewStore, prepare,
)
from backend.security import Settings


@pytest.fixture
def client():
    key = secrets.token_urlsafe(32)
    app = create_app(Settings(api_key=key))
    with TestClient(app, base_url="http://127.0.0.1",
                    headers={"Authorization": f"Bearer {key}"}) as client:
        yield client


def prepared(client, use_case="support_ticket", text="Contact alice@example.com", **extra):
    fields = extra.pop("fields", {"text": text})
    response = client.post("/api/prepare", json={"use_case": use_case, "fields": fields, **extra})
    assert response.status_code == 200, response.json()
    return response.json()


def export_payload(result):
    return {"receipt": result["review"]["receipt"], "candidate": result["candidate"], "confirmed": True}


@pytest.mark.parametrize("use_case", ["support_ticket", "ai_prompt", "email"])
def test_prepare_review_export_all_use_cases(client, use_case):
    fields = {"text": "😀 Contact alice@example.com twice: alice@example.com."}
    if use_case == "email":
        fields = {"sender": "Alice <alice@northwind.io>", "recipients": "Bob <bob@example.com>",
                  "subject": "Question from alice@example.com", "body": "Contact alice@example.com."}
    result = prepared(client, use_case, fields=fields)
    candidate = result["candidate"]
    assert candidate["policy_version"] == "2026-09-30.1"
    assert candidate["engine"] == "heuristic"
    assert result["offset_unit"] == "unicode_code_points"
    assert "alice@example.com" not in json.dumps(result)
    assert all("text" not in finding for finding in result["findings"])
    if use_case == "email":
        assert candidate["fields"]["sender"] == "[SENDER_REMOVED]"
        assert candidate["fields"]["recipients"] == "[RECIPIENTS_REMOVED]"
        assert candidate["routing"] == {"recipient_count": 1, "crosses_example_boundary": True,
                                         "all_recipients_internal": False}
        assert "bob@example.com" not in json.dumps(result)
    else:
        assert candidate["fields"]["text"].count("[PRIVATE_EMAIL_1]") == 2
        assert result["findings"][0]["start"] == 10
    exported = client.post("/api/review/export", json=export_payload(result))
    assert exported.status_code == 200
    assert exported.json()["candidate"] == candidate
    assert exported.json()["reviewed"] is True
    assert client.post("/api/review/export", json=export_payload(result)).status_code == 410


def test_explicit_review_required(client):
    result = prepared(client)
    payload = export_payload(result)
    for confirmation in [False, "true", 1, None]:
        payload["confirmed"] = confirmation
        assert client.post("/api/review/export", json=payload).status_code == 422
    del payload["confirmed"]
    assert client.post("/api/review/export", json=payload).status_code == 422
    assert client.post("/api/review/export", json=export_payload(result)).status_code == 200


@pytest.mark.parametrize("change", ["text", "engine", "use_case", "routing", "policy_version"])
def test_candidate_tampering_fails_and_original_remains_reviewable(client, change):
    result = prepared(client)
    payload = copy.deepcopy(export_payload(result))
    if change == "text":
        payload["candidate"]["fields"]["text"] = "unreviewed_sensitive_sentinel"
    elif change == "routing":
        payload["candidate"]["routing"] = {"recipient_count": 1, "crosses_example_boundary": False,
                                             "all_recipients_internal": True}
    else:
        payload["candidate"][change] = {"engine": "opf", "use_case": "ai_prompt", "policy_version": "other"}[change]
    response = client.post("/api/review/export", json=payload)
    assert response.status_code in (409, 422)
    assert "unreviewed_sensitive_sentinel" not in response.text
    assert client.post("/api/review/export", json=export_payload(result)).status_code == 200


def test_expiration_discard_and_process_restart_invalidate_receipts(client):
    now = [1.0]
    client.app.state.reviews = ReviewStore(clock=lambda: now[0])
    result = prepared(client)
    now[0] += RECEIPT_TTL_SECONDS
    assert client.post("/api/review/export", json=export_payload(result)).status_code == 410
    result = prepared(client)
    assert client.post("/api/review/discard", json={"receipt": result["review"]["receipt"]}).status_code == 200
    assert client.post("/api/review/export", json=export_payload(result)).status_code == 410
    result = prepared(client)
    client.app.state.reviews.clear()
    assert client.post("/api/review/export", json=export_payload(result)).status_code == 410


def test_receipts_do_not_cross_service_instances(client):
    result = prepared(client)
    client.app.state.reviews = ReviewStore()
    response = client.post("/api/review/export", json=export_payload(result))
    assert response.status_code == 410


def test_concurrent_export_succeeds_once(client):
    result = prepared(client)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(client.post, "/api/review/export", json=export_payload(result)) for _ in range(2)]
        assert sorted(f.result().status_code for f in futures) == [200, 410]


def test_manual_masks_use_unicode_and_preserve_automatic_coverage(client):
    text = "😀 Åsa met alice@example.com"
    result = prepared(client, text=text, manual_masks=[{"field": "text", "start": 2, "end": 5}])
    assert result["candidate"]["fields"]["text"] == "😀 [MANUAL_1] met [PRIVATE_EMAIL_1]"
    assert result["summary"]["manual_mask_count"] == 1
    assert result["findings"][0]["sources"] == ["manual"]
    # An overlapping added mask cannot shorten an automatic email finding.
    result = prepared(client, text=text, manual_masks=[{"field": "text", "start": 6, "end": 15}])
    assert "alice" not in result["candidate"]["fields"]["text"]
    assert result["findings"][0]["start"] == 6
    assert result["findings"][0]["end"] == len(text)


@pytest.mark.parametrize("mask", [
    {"field": "body", "start": 0, "end": 1}, {"field": "text", "start": 2, "end": 1},
    {"field": "text", "start": -1, "end": 1}, {"field": "text", "start": 0, "end": 999},
    {"field": "text", "start": True, "end": 1},
])
def test_invalid_manual_masks_are_rejected_without_echoing_input(client, mask):
    response = client.post("/api/prepare", json={"use_case": "support_ticket", "fields": {"text": "sensitive_sentinel"},
                                                 "manual_masks": [mask]})
    assert response.status_code == 422
    assert "sensitive_sentinel" not in response.text
    assert client.app.state.reviews.events() == []


@pytest.mark.parametrize("fields", [
    {"sender": "Alice <alice@northwind.io>", "recipients": "broken"},
    {"sender": "alice@northwind.io\r\nBcc: eve@example.com", "recipients": "bob@example.com"},
    {"sender": "alice@northwind.io, eve@example.com", "recipients": "bob@example.com"},
])
def test_malformed_email_routing_fails_closed(client, fields):
    response = client.post("/api/prepare", json={"use_case": "email", "fields": {**fields, "subject": "", "body": "private"}})
    assert response.status_code == 422
    assert "private" not in response.text


def test_policy_masks_credentials_even_when_model_has_no_findings():
    class MissedModel:
        engine = "opf"

        def detect(self, text):
            return DetectionResult(engine=self.engine, text=text, redacted_text=text)

    # Deliberately synthetic phrases and short values; no working credential.
    text = 'password="example words"; token=demo; Password: abc'
    req = PrepareRequest(use_case="ai_prompt", fields={"text": text})
    candidate, findings, _ = prepare(req, MissedModel())
    assert candidate.fields["text"] == "[SECRET_1]; [SECRET_2]; [SECRET_3]"
    assert len(findings) == 3
    assert all(s["sources"] == ["credential_rule"] for s in findings)
    assert all(s["label"] == "secret" for s in findings)


def test_invalid_model_spans_cannot_produce_exportable_result():
    class BrokenModel:
        engine = "opf"

        def detect(self, text):
            return DetectionResult(engine=self.engine, text=text, detected_spans=[
                Span("private_email", 0, len(text), "different", "[EMAIL]"),
            ])

    with pytest.raises(ReviewError):
        prepare(PrepareRequest(use_case="ai_prompt", fields={"text": "sensitive_sentinel"}), BrokenModel())


def test_repeated_placeholders_are_consistent_within_request_and_reset_between_requests(client):
    first = prepared(client, "ai_prompt", "alice@example.com bob@example.com alice@example.com")
    assert first["candidate"]["fields"]["text"] == "[PRIVATE_EMAIL_1] [PRIVATE_EMAIL_2] [PRIVATE_EMAIL_1]"
    second = prepared(client, "ai_prompt", "bob@example.com")
    assert second["candidate"]["fields"]["text"] == "[PRIVATE_EMAIL_1]"


def test_existing_placeholder_text_cannot_be_confused_with_a_new_mask(client):
    result = prepared(client, text="[PRIVATE_EMAIL_1] alice@example.com")
    assert result["candidate"]["fields"]["text"] == "[PRIVATE_EMAIL_1] [PRIVATE_EMAIL_2]"


def test_unexportable_candidate_fails_without_issuing_receipt(client):
    response = client.post("/api/prepare", json={"use_case": "ai_prompt", "fields": {"text": "😀" * 6000}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "candidate_too_large"
    assert client.app.state.reviews.events() == []


def test_empty_and_excessive_combined_input_rejected(client):
    assert client.post("/api/prepare", json={"use_case": "ai_prompt", "fields": {"text": "  "}}).status_code == 422
    response = client.post("/api/prepare", json={"use_case": "email", "fields": {
        "sender": "a@example.com", "recipients": "b@example.com", "subject": "x" * 8000, "body": "y" * 8000,
    }})
    assert response.status_code == 422


def test_storage_and_events_do_not_retain_source_or_candidate(client):
    source = "unmatched_sensitive_sentinel alice@example.com"
    result = prepared(client, text=source)
    store = client.app.state.reviews
    # This sentinel is intentionally missed. Even candidate text must not persist.
    assert "unmatched_sensitive_sentinel" in result["candidate"]["fields"]["text"]
    assert "unmatched_sensitive_sentinel" not in repr(store.__dict__)
    assert "alice@example.com" not in repr(store.__dict__)
    assert client.post("/api/review/export", json=export_payload(result)).status_code == 200
    events = client.get("/api/review/events").json()["events"]
    assert [e["action"] for e in events] == ["prepared", "exported"]
    assert "unmatched_sensitive_sentinel" not in json.dumps(events)
    assert result["review"]["receipt"] not in json.dumps(events)
    assert "fields" not in json.dumps(events)


def test_receipt_and_event_storage_are_bounded():
    now = [1.0]
    store = ReviewStore(clock=lambda: now[0])
    candidate, _, summary = prepare(PrepareRequest(use_case="support_ticket", fields={"text": "hello"}), Detector("heuristic"))
    for _ in range(MAX_PENDING_REVIEWS):
        store.issue(candidate, summary)
    with pytest.raises(ReviewError) as exc:
        store.issue(candidate, summary)
    assert exc.value.code == "review_capacity_reached"
    assert len(store.events()) == 128
    now[0] += RECEIPT_TTL_SECONDS
    assert store.issue(candidate, summary)
    assert len(store._pending) == 1


def test_all_review_routes_require_authentication(client):
    client.headers.pop("Authorization")
    for route in ["/api/prepare", "/api/review/export", "/api/review/discard"]:
        assert client.post(route, json={}).status_code == 401
    assert client.get("/api/review/events").status_code == 401
