"""FastAPI server for the privacy-detector PoC."""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.corpus import EMPLOYEES, INTERNAL_DOMAINS, get_corpus
from backend.detector import LABELS, get_detector
from backend.security import MAX_TEXT_CHARS, ServiceBoundary, Settings, error_response
from backend.review import (
    RECEIPT_TTL_SECONDS, WARNINGS, ExportRequest, PrepareRequest, ReceiptRequest,
    ReviewError, ReviewStore, prepare,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_detector()
    try:
        yield
    finally:
        app.state.reviews.clear()


router = APIRouter()

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=MAX_TEXT_CHARS)
    include_source: StrictBool = False


@contextmanager
def inference_slot(request: Request):
    gate = request.app.state.inference_gate
    if not gate.acquire(blocking=False):
        raise HTTPException(429)
    try:
        yield
    finally:
        gate.release()


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


@router.get("/api/engine")
def engine_info() -> dict[str, Any]:
    d = get_detector()
    return {
        "engine": d.engine,
        "detail": d.engine_detail,
        "labels": LABELS,
    }


@router.get("/api/config")
def config(request: Request) -> dict[str, Any]:
    return {
        "internal_domains": INTERNAL_DOMAINS,
        "employees": EMPLOYEES,
        "labels": LABELS,
        "input_enabled": request.app.state.settings.api_key is not None,
        "max_text_chars": MAX_TEXT_CHARS,
    }


@router.get("/api/corpus")
def corpus() -> dict[str, Any]:
    return {"emails": [e.to_dict() for e in get_corpus()]}


@router.post("/api/scan")
def scan(req: ScanRequest, request: Request) -> dict[str, Any]:
    with inference_slot(request):
        result = get_detector().detect(req.text).to_dict()
    if not req.include_source:
        result.pop("text")
        for span in result["detected_spans"]:
            span.pop("text")
    return result


@router.post("/api/prepare")
def prepare_for_review(req: PrepareRequest, request: Request) -> dict[str, Any]:
    with inference_slot(request):
        candidate, findings, summary = prepare(req, get_detector())
        receipt = request.app.state.reviews.issue(candidate, summary)
    return {"schema_version": 1, "offset_unit": "unicode_code_points",
            "candidate": candidate.model_dump(), "findings": findings, "summary": summary,
            "review": {"receipt": receipt, "expires_in_seconds": RECEIPT_TTL_SECONDS},
            "warnings": WARNINGS}


@router.post("/api/review/export")
def export_review(req: ExportRequest, request: Request) -> dict[str, Any]:
    return request.app.state.reviews.export(req.receipt, req.candidate)


@router.post("/api/review/discard")
def discard_review(req: ReceiptRequest, request: Request) -> dict[str, bool]:
    request.app.state.reviews.discard(req.receipt)
    return {"discarded": True}


@router.get("/api/review/events")
def review_events(request: Request) -> dict[str, Any]:
    return {"events": request.app.state.reviews.events(), "retention": "last_128_until_restart"}


@router.get("/api/scan-all")
def scan_all(request: Request) -> dict[str, Any]:
    with inference_slot(request):
        return _scan_all()


def _scan_all() -> dict[str, Any]:
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    app = FastAPI(title="Sentinel privacy reference", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.inference_gate = BoundedSemaphore(1)
    app.state.reviews = ReviewStore()
    app.add_middleware(ServiceBoundary, settings=settings)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return error_response(422, "invalid_request")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        codes = {404: "not_found", 405: "method_not_allowed", 429: "processing_busy"}
        return error_response(exc.status_code, codes.get(exc.status_code, "request_rejected"))

    @app.exception_handler(ReviewError)
    async def review_error(request: Request, exc: ReviewError):
        return error_response(exc.status, exc.code)

    app.include_router(router)
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()
