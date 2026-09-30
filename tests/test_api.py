import pytest
from fastapi.testclient import TestClient

import backend.detector as detector
from backend.main import _classify_email, app


@pytest.mark.parametrize("sender,recipients,crosses", [
    ("a@northwind.io", ["b@northwind.io"], False),
    ("a@northwind.io", ["b@example.com"], True),
    ("a@example.com", ["b@northwind.io"], True),
    ("a@example.com", ["b@example.net"], False),
    ("a@example.com", ["b@northwind.io", "c@example.net"], True),
    ("a@northwind.io", ["b@northwind.io", "c@example.net"], True),
    ("a@NORTHWIND.IO", ["b@northwind-corp.com"], False),
    ("a@northwind.io", [], False),
    ("a@example.com", [], False),
])
def test_boundary_crossings(sender, recipients, crosses):
    assert _classify_email(sender, recipients)["crosses_boundary"] is crosses


def test_detector_is_ready_before_requests():
    assert detector._detector is None
    with TestClient(app) as client:
        initialized = detector._detector
        assert initialized is not None
        assert client.get("/api/engine").json()["engine"] == "heuristic"
        assert detector._detector is initialized


def test_scan_api_redacts_sensitive_text_and_defines_offsets():
    with TestClient(app) as client:
        response = client.post("/api/scan", json={"text": "😀 alice@example.com"})
        assert response.status_code == 200
        data = response.json()
        assert data["offset_unit"] == "unicode_code_points"
        assert data["redacted_text"] == "😀 [PRIVATE_EMAIL]"
        assert data["summary"]["by_label"] == {"private_email": 1}
        assert client.post("/api/scan", json={"text": ""}).json()["redacted_text"] == ""
        assert client.post("/api/scan", json={}).status_code == 422


def test_corpus_aggregates_and_served_assets():
    with TestClient(app) as client:
        for path in ["/", "/assets/app.js", "/assets/rendering.js", "/assets/styles.css"]:
            assert client.get(path).status_code == 200
        corpus = client.get("/api/corpus").json()["emails"]
        data = client.get("/api/scan-all").json()
        assert len(data["results"]) == len(corpus) == data["aggregates"]["total"]
        assert len({r["email"]["id"] for r in data["results"]}) == len(corpus)
        labels = {}
        for result in data["results"]:
            for part in ["body", "subject"]:
                scan = result["scan"][part]
                end = 0
                for span in scan["detected_spans"]:
                    assert end <= span["start"] < span["end"] <= len(scan["text"])
                    assert scan["text"][span["start"]:span["end"]] == span["text"]
                    end = span["end"]
                    labels[span["label"]] = labels.get(span["label"], 0) + 1
        assert data["aggregates"]["by_label"] == labels
