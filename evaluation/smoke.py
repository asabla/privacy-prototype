"""Opt-in real OPF API check; fails immediately if the heuristic is selected."""

import json
import secrets

from fastapi.testclient import TestClient

from backend.detector import DetectionResult, Span
from backend.main import create_app
from backend.security import Settings
from evaluation.core import Case, score_case


def validate_scan(scan: dict) -> None:
    if scan["engine"] != "opf" or scan["offset_unit"] != "unicode_code_points":
        raise ValueError("Real OPF with Unicode code-point offsets is required")
    spans = [Span(**span) for span in scan["detected_spans"]]
    score_case(Case("api-smoke", scan["text"], ()), DetectionResult(
        engine="opf", text=scan["text"], detected_spans=spans, redacted_text=scan["redacted_text"],
    ))
    if scan["summary"]["span_count"] != len(spans):
        raise ValueError("Span summary does not match detector output")


def main() -> None:
    api_key = secrets.token_urlsafe(32)
    app = create_app(Settings(api_key=api_key))
    with TestClient(app, base_url="http://127.0.0.1",
                    headers={"Authorization": f"Bearer {api_key}"}) as client:
        engine = client.get("/api/engine")
        engine.raise_for_status()
        if engine.json()["engine"] != "opf":
            raise RuntimeError("Real OPF is required; the heuristic cannot satisfy this check")
        sample = "😀 Please contact Alice Smith at alice.smith@gmail.com. Her date of birth is 1990-01-02."
        response = client.post("/api/scan", json={"text": sample, "include_source": True})
        response.raise_for_status()
        scanned = response.json()
        if scanned["text"] != sample:
            raise ValueError("Scan response did not preserve the requested text")
        validate_scan(scanned)
        address_start = sample.index("alice.smith@gmail.com")
        if not any(s["label"] == "private_email" and s["start"] <= address_start
                   and s["end"] >= address_start + len("alice.smith@gmail.com")
                   for s in scanned["detected_spans"]):
            raise ValueError("The real model did not cover the synthetic email address")
        empty = client.post("/api/scan", json={"text": "", "include_source": True})
        empty.raise_for_status()
        validate_scan(empty.json())

        response = client.get("/api/scan-all")
        response.raise_for_status()
        corpus = response.json()
        source = client.get("/api/corpus")
        source.raise_for_status()
        expected_ids = {email["id"] for email in source.json()["emails"]}
        actual_ids = [result["email"]["id"] for result in corpus["results"]]
        if not expected_ids or set(actual_ids) != expected_ids or len(actual_ids) != len(expected_ids):
            raise ValueError("Scan-all did not process every synthetic email exactly once")
        for result in corpus["results"]:
            for part in ("subject", "body"):
                if result["scan"][part]["text"] != result["email"][part]:
                    raise ValueError("Scan-all response did not preserve the original email")
                validate_scan(result["scan"][part])
        workflows = [
            ("support_ticket", {"text": sample}),
            ("ai_prompt", {"text": 'Summarize this example: password="example words"; token=demo'}),
            ("email", {"sender": "Alice <alice@northwind.io>", "recipients": "Bob <bob@example.com>",
                       "subject": "Support request", "body": sample}),
        ]
        for use_case, fields in workflows:
            response = client.post("/api/prepare", json={"use_case": use_case, "fields": fields})
            response.raise_for_status()
            prepared = response.json()
            candidate = prepared["candidate"]
            if candidate["engine"] != "opf" or "alice.smith@gmail.com" in json.dumps(candidate):
                raise ValueError("Real OPF workflow did not minimize the synthetic email address")
            if use_case == "ai_prompt" and any(value in candidate["fields"]["text"] for value in ("example words", "demo")):
                raise ValueError("Credential policy did not cover the known synthetic model misses")
            payload = {"receipt": prepared["review"]["receipt"], "candidate": candidate, "confirmed": True}
            exported = client.post("/api/review/export", json=payload)
            exported.raise_for_status()
            if exported.json()["candidate"] != candidate:
                raise ValueError("Export did not preserve the reviewed candidate")
            if client.post("/api/review/export", json=payload).status_code != 410:
                raise ValueError("An export receipt was reusable")
        print(json.dumps({"engine": "opf", "unicode_sample": "passed", "empty_input": "passed",
                          "corpus_emails": len(actual_ids), "review_workflows": len(workflows), "status": "passed"}))


if __name__ == "__main__":
    main()
