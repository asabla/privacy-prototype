import asyncio
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

import backend.detector as detector
from backend.main import create_app
from backend.security import MAX_BODY_BYTES, MAX_TEXT_CHARS, SECURITY_HEADERS, Settings


@pytest.fixture
def app():
    return create_app(Settings(api_key=secrets.token_urlsafe(32)))


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1", headers={
        "Authorization": f"Bearer {app.state.settings.api_key}",
    }) as client:
        yield client


def test_input_is_disabled_until_configured():
    with TestClient(create_app(Settings()), base_url="http://127.0.0.1") as client:
        assert client.get("/api/config").json()["input_enabled"] is False
        response = client.post("/api/scan", json={"text": "private input"})
        assert response.status_code == 503
        assert response.json() == {"error": {"code": "input_disabled"}}
        assert client.get("/api/scan-all").status_code == 200


def test_authentication_and_minimized_response(client):
    source = "Contact alice@example.com"
    for auth in [None, "Bearer wrong", "Basic wrong", "Bearer "]:
        headers = {} if auth is None else {"Authorization": auth}
        with TestClient(client.app, base_url="http://127.0.0.1") as unauthenticated:
            response = unauthenticated.post("/api/scan", json={"text": source}, headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert source not in response.text
    response = client.post("/api/scan", json={"text": source})
    assert response.status_code == 200
    data = response.json()
    assert "text" not in data
    assert "text" not in data["detected_spans"][0]
    assert "alice@example.com" not in response.text
    inspected = client.post("/api/scan", json={"text": source, "include_source": True}).json()
    assert inspected["text"] == source
    assert inspected["detected_spans"][0]["text"] == "alice@example.com"
    duplicate = client.post("/api/scan", json={"text": source}, headers=[
        ("Authorization", "Bearer wrong"), ("Authorization", client.headers["Authorization"]),
    ])
    assert duplicate.status_code == 401


@pytest.mark.parametrize("payload", [
    {"text": {"sensitive_sentinel": "private"}},
    {"text": "x", "sensitive_sentinel": "private"},
    {"text": "sensitive_sentinel", "include_source": "true"},
    {"text": "sensitive_sentinel" * MAX_TEXT_CHARS},
])
def test_validation_never_reflects_input(client, payload, caplog, capsys):
    response = client.post("/api/scan", json=payload)
    assert response.status_code in (413, 422)
    assert "sensitive_sentinel" not in response.text
    assert "sensitive_sentinel" not in caplog.text + str(capsys.readouterr())


def test_malformed_json_and_unsupported_bodies(client):
    response = client.post("/api/scan", content='{"sensitive_sentinel":',
                           headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert "sensitive_sentinel" not in response.text
    assert client.post("/api/scan", content="text=private").status_code == 415
    assert client.post("/api/scan", json={"text": "private"},
                       headers={"content-encoding": "gzip"}).status_code == 415


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://localhost",
                                    "http://127.0.0.1:9000"])
def test_foreign_origins_rejected(client, origin):
    response = client.post("/api/scan", json={"text": "private"}, headers={"Origin": origin})
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_same_origin_and_host_validation(client):
    assert client.post("/api/scan", json={"text": ""}, headers={
        "Origin": "http://127.0.0.1",
    }).status_code == 200
    for host in ["evil.example", "localhost.evil.example", "localhost@evil.example",
                 "localhost:invalid", "localhost/anything", "[::1"]:
        assert client.get("/", headers={"Host": host}).status_code == 400
    assert client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/", headers={"Host": "[::1]:8000"}).status_code == 200


@pytest.mark.parametrize("path,status", [("/", 200), ("/health", 200),
                                         ("/missing", 404), ("/docs", 404), ("/api/engine", 200)])
def test_security_headers_on_success_and_failure(client, path, status):
    response = client.get(path)
    assert response.status_code == status
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


def test_inference_failure_is_sanitized_and_capacity_recovers(client, monkeypatch, caplog, capsys):
    model = detector.get_detector()
    original = model.detect

    def fail(text):
        raise ValueError("sensitive_sentinel in model exception")

    monkeypatch.setattr(model, "detect", fail)
    response = client.post("/api/scan", json={"text": "sensitive_sentinel"})
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "processing_failed"}}
    assert response.headers["cache-control"] == "no-store"
    assert "sensitive_sentinel" not in caplog.text + str(capsys.readouterr()) + response.text
    monkeypatch.setattr(model, "detect", original)
    assert client.post("/api/scan", json={"text": ""}).status_code == 200


def test_concurrent_inference_rejected_without_queueing(client, monkeypatch):
    entered, release = Event(), Event()
    model = detector.get_detector()
    original = model.detect

    def slow(text):
        entered.set()
        assert release.wait(5)
        return original(text)

    monkeypatch.setattr(model, "detect", slow)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(client.post, "/api/scan", json={"text": ""})
        try:
            assert entered.wait(5)
            for method, path, kwargs in [(client.post, "/api/scan", {"json": {"text": ""}}),
                                         (client.get, "/api/scan-all", {})]:
                response = method(path, **kwargs)
                assert response.status_code == 429
                assert response.headers["retry-after"] == "1"
            assert client.get("/health").status_code == 200
        finally:
            release.set()
        assert first.result().status_code == 200
    assert client.post("/api/scan", json={"text": ""}).status_code == 200


async def asgi_request(app, chunks, headers=(), authenticated=True):
    sent = []
    reads = 0

    async def receive():
        nonlocal reads
        if not chunks:
            raise AssertionError("Unauthorized requests must not read a body")
        chunk = chunks.pop(0)
        reads += 1
        return {"type": "http.request", "body": chunk, "more_body": bool(chunks)}

    async def send(message):
        sent.append(message)

    base_headers = [(b"host", b"127.0.0.1"), (b"content-type", b"application/json")]
    if authenticated:
        base_headers.append((b"authorization", f"Bearer {app.state.settings.api_key}".encode()))
    await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
               "method": "POST", "scheme": "http", "path": "/api/scan", "query_string": b"",
               "root_path": "", "headers": base_headers + list(headers),
               "client": ("127.0.0.1", 1000), "server": ("127.0.0.1", 80)}, receive, send)
    return sent, reads


def test_streamed_size_is_bounded_even_without_content_length(app):
    messages, reads = asyncio.run(asgi_request(app, [b" " * 32_768] * 3))
    assert messages[0]["status"] == 413
    assert reads == 3
    messages, _ = asyncio.run(asgi_request(app, [json.dumps({"text": ""}).encode()]))
    assert messages[0]["status"] == 200


def test_auth_precedes_body_read_and_declared_length_is_checked(app):
    messages, reads = asyncio.run(asgi_request(app, [], authenticated=False))
    assert messages[0]["status"] == 401 and reads == 0
    for length, status in [(str(MAX_BODY_BYTES + 1).encode(), 413), (b"-1", 400), (b"bad", 400)]:
        messages, reads = asyncio.run(asgi_request(app, [], [(b"content-length", length)]))
        assert messages[0]["status"] == status and reads == 0
    messages, _ = asyncio.run(asgi_request(app, [b"{}"], [(b"content-length", b"1")]))
    assert messages[0]["status"] == 400


def test_settings_fail_closed_without_exposing_values(monkeypatch):
    monkeypatch.setenv("SENTINEL_API_KEY", "invalid_sensitive_sentinel")
    with pytest.raises(ValueError) as exc:
        Settings.from_env()
    assert "invalid_sensitive_sentinel" not in str(exc.value)
    assert "invalid_sensitive_sentinel" not in repr(Settings(api_key=secrets.token_urlsafe(32)))
    for hosts in [("*",), (), ("localhost:8000",), ("example.com",)]:
        with pytest.raises(ValueError):
            Settings(allowed_hosts=hosts)


def test_non_loopback_requires_https_and_authentication():
    key = secrets.token_urlsafe(32)
    app = create_app(Settings(api_key=key, allowed_hosts=("reference.example",)))
    with TestClient(app, base_url="http://reference.example") as client:
        assert client.get("/api/config").status_code == 400
    with TestClient(app, base_url="https://reference.example") as client:
        assert client.get("/api/config").status_code == 401
        assert client.get("/api/config", headers={"Authorization": f"Bearer {key}"}).status_code == 200
