"""FastAPI server for the privacy-detector PoC."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.corpus import EMPLOYEES, INTERNAL_DOMAINS, get_corpus
from backend.detector import LABELS, get_detector


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_detector()
    yield


app = FastAPI(title="Privacy Detector PoC", lifespan=lifespan)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


class ScanRequest(BaseModel):
    text: str


def _domain_of(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def _is_internal(address: str) -> bool:
    return _domain_of(address) in INTERNAL_DOMAINS


def _classify_email(sender: str, recipients: list[str]) -> dict[str, Any]:
    sender_internal = _is_internal(sender)
    rcpt_internal = [_is_internal(r) for r in recipients]
    all_rcpt_internal = all(rcpt_internal) if rcpt_internal else False
    any_rcpt_internal = any(rcpt_internal) if rcpt_internal else False
    external_domains = sorted(
        {
            _domain_of(r)
            for r, internal in zip(recipients, rcpt_internal)
            if not internal
        }
        | ({_domain_of(sender)} if not sender_internal else set())
    )
    return {
        "sender_internal": sender_internal,
        "all_recipients_internal": all_rcpt_internal,
        "any_recipient_internal": any_rcpt_internal,
        "fully_internal": sender_internal and all_rcpt_internal,
        "crosses_boundary": any(sender_internal != internal for internal in rcpt_internal),
        "external_domains": external_domains,
    }


def _known_employee_hits(text: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    lowered = text.lower()
    for emp in EMPLOYEES:
        for needle, kind in ((emp["name"], "name"), (emp["email"], "email")):
            idx = lowered.find(needle.lower())
            if idx != -1:
                hits.append(
                    {
                        "start": idx,
                        "end": idx + len(needle),
                        "text": text[idx : idx + len(needle)],
                        "kind": kind,
                        "employee": emp["name"],
                        "role": emp["role"],
                    }
                )
    return hits


@app.get("/api/engine")
def engine_info() -> dict[str, Any]:
    d = get_detector()
    return {
        "engine": d.engine,
        "detail": d.engine_detail,
        "labels": LABELS,
    }


@app.get("/api/config")
def config() -> dict[str, Any]:
    return {
        "internal_domains": INTERNAL_DOMAINS,
        "employees": EMPLOYEES,
        "labels": LABELS,
    }


@app.get("/api/corpus")
def corpus() -> dict[str, Any]:
    return {"emails": [e.to_dict() for e in get_corpus()]}


@app.post("/api/scan")
def scan(req: ScanRequest) -> dict[str, Any]:
    result = get_detector().detect(req.text)
    return result.to_dict()


@app.get("/api/scan-all")
def scan_all() -> dict[str, Any]:
    det = get_detector()
    results = []
    for e in get_corpus():
        scanned_body = det.detect(e.body).to_dict()
        scanned_subject = det.detect(e.subject).to_dict()
        classification = _classify_email(e.sender, e.recipients)
        employees_referenced = _known_employee_hits(e.body + " " + e.subject)
        # Dedupe employees by name, keep distinct kinds.
        uniq: dict[str, dict[str, Any]] = {}
        for h in employees_referenced:
            uniq.setdefault(h["employee"], {"employee": h["employee"], "role": h["role"], "kinds": set()})
            uniq[h["employee"]]["kinds"].add(h["kind"])
        employees_list = [
            {"employee": v["employee"], "role": v["role"], "kinds": sorted(v["kinds"])}
            for v in uniq.values()
        ]

        total_spans = len(scanned_body["detected_spans"]) + len(scanned_subject["detected_spans"])
        by_label: dict[str, int] = {}
        for s in scanned_body["detected_spans"] + scanned_subject["detected_spans"]:
            by_label[s["label"]] = by_label.get(s["label"], 0) + 1

        results.append(
            {
                "email": e.to_dict(),
                "classification": classification,
                "employees_referenced": employees_list,
                "scan": {
                    "body": scanned_body,
                    "subject": scanned_subject,
                    "span_count": total_spans,
                    "by_label": by_label,
                    "is_sensitive": total_spans > 0,
                },
            }
        )

    # Aggregates for the dashboard.
    total = len(results)
    inbound = sum(1 for r in results if r["email"]["direction"] == "inbound")
    outbound = sum(1 for r in results if r["email"]["direction"] == "outbound")
    internal = sum(1 for r in results if r["email"]["direction"] == "internal")
    sensitive = sum(1 for r in results if r["scan"]["is_sensitive"])
    crossing = sum(1 for r in results if r["classification"]["crosses_boundary"])
    leaks_out = sum(
        1
        for r in results
        if r["scan"]["is_sensitive"]
        and r["email"]["direction"] == "outbound"
        and not r["classification"]["all_recipients_internal"]
    )
    label_totals: dict[str, int] = {}
    for r in results:
        for label, n in r["scan"]["by_label"].items():
            label_totals[label] = label_totals.get(label, 0) + n

    return {
        "engine": get_detector().engine,
        "engine_detail": get_detector().engine_detail,
        "aggregates": {
            "total": total,
            "inbound": inbound,
            "outbound": outbound,
            "internal": internal,
            "sensitive": sensitive,
            "sensitive_inbound": sum(
                1 for r in results if r["scan"]["is_sensitive"] and r["email"]["direction"] == "inbound"
            ),
            "sensitive_outbound": sum(
                1 for r in results if r["scan"]["is_sensitive"] and r["email"]["direction"] == "outbound"
            ),
            "sensitive_internal": sum(
                1 for r in results if r["scan"]["is_sensitive"] and r["email"]["direction"] == "internal"
            ),
            "crossing_boundary": crossing,
            "leaks_out": leaks_out,
            "by_label": label_totals,
        },
        "results": results,
    }


# Serve the static frontend.
if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")
