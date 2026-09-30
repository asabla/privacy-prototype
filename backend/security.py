"""Small, explicit service boundary for the single-operator reference app."""

from __future__ import annotations

import asyncio
import hmac
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

MAX_BODY_BYTES = 65_536
MAX_TEXT_CHARS = 16_000
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
PUBLIC_API = {"/api/engine", "/api/config", "/api/corpus", "/api/scan-all"}
SECURITY_HEADERS = {
    "cache-control": "no-store",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "content-security-policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'",
}


@dataclass(frozen=True)
class Settings:
    api_key: str | None = field(default=None, repr=False)
    allowed_hosts: tuple[str, ...] = LOCAL_HOSTS

    def __post_init__(self) -> None:
        if self.api_key is not None and not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", self.api_key):
            raise ValueError("SENTINEL_API_KEY must be a random URL-safe value of 32 to 256 characters")
        if not self.allowed_hosts or any(
            host != "::1" and not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
            for host in self.allowed_hosts
        ):
            raise ValueError("SENTINEL_ALLOWED_HOSTS must contain explicit lowercase hostnames without ports")
        if any(host not in LOCAL_HOSTS for host in self.allowed_hosts) and self.api_key is None:
            raise ValueError("Non-loopback hosts require SENTINEL_API_KEY and HTTPS")

    @classmethod
    def from_env(cls) -> Settings:
        hosts = os.environ.get("SENTINEL_ALLOWED_HOSTS")
        return cls(
            api_key=os.environ.get("SENTINEL_API_KEY"),
            allowed_hosts=tuple(h.strip() for h in hosts.split(",")) if hosts is not None else LOCAL_HOSTS,
        )


def error_response(status: int, code: str) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
    if status == 429:
        headers["Retry-After"] = "1"
    return JSONResponse({"error": {"code": code}}, status_code=status, headers=headers)


class ServiceBoundary:
    """Validate before reading bodies; never serialize or log request exceptions."""

    def __init__(self, app, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def secure_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = [(k, v) for k, v in message.get("headers", [])
                           if k.decode("latin-1").lower() not in SECURITY_HEADERS]
                headers += [(k.encode(), v.encode()) for k, v in SECURITY_HEADERS.items()]
                message = {**message, "headers": headers}
            await send(message)

        async def reject(status, code):
            await error_response(status, code)(scope, receive, secure_send)

        headers: dict[bytes, list[bytes]] = {}
        for name, value in scope["headers"]:
            headers.setdefault(name.lower(), []).append(value)

        def single(name: bytes) -> str | None:
            values = headers.get(name, [])
            return values[0].decode("latin-1") if len(values) == 1 else None

        host = single(b"host")
        try:
            authority = urlsplit("//" + (host or ""))
            valid_host = bool(re.fullmatch(r"(?:[A-Za-z0-9.-]+|\[::1\])(?::[0-9]{1,5})?", host or ""))
            valid_host = valid_host and authority.hostname in self.settings.allowed_hosts
            valid_host = valid_host and not (authority.username or authority.password or authority.path
                                            or authority.query or authority.fragment)
            # Evaluate the port too: malformed ports must fail without reflecting the value.
            _ = authority.port
        except ValueError:
            valid_host = False
        if not valid_host:
            await reject(400, "invalid_host")
            return
        if authority.hostname not in LOCAL_HOSTS and scope["scheme"] != "https":
            await reject(400, "https_required")
            return
        if b"origin" in headers:
            origin = single(b"origin")
            expected = f'{scope["scheme"]}://{host}'
            if origin != expected:
                await reject(403, "origin_rejected")
                return
        if single(b"sec-fetch-site") not in (None, "same-origin", "none"):
            await reject(403, "origin_rejected")
            return

        path = scope["path"]
        protected = path.startswith("/api/") and not (
            path in PUBLIC_API and scope["method"] in ("GET", "HEAD")
        )
        # A remotely hosted fixture service also requires the configured principal.
        protected = protected or (path.startswith("/api/") and authority.hostname not in LOCAL_HOSTS)
        if protected:
            if self.settings.api_key is None:
                await reject(503, "input_disabled")
                return
            auth = single(b"authorization") or ""
            scheme, _, value = auth.partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(
                value.encode("latin-1"), self.settings.api_key.encode("ascii")
            ):
                await reject(401, "authentication_required")
                return

        if scope["method"] in ("POST", "PUT", "PATCH"):
            content_type = (single(b"content-type") or "").partition(";")[0].strip().lower()
            if content_type != "application/json" or b"content-encoding" in headers:
                await reject(415, "json_required")
                return
            length = single(b"content-length")
            if b"content-length" in headers and (length is None or not length.isascii() or not length.isdecimal()):
                await reject(400, "invalid_length")
                return
            if length is not None and (len(length) > 8 or int(length) > MAX_BODY_BYTES):
                await reject(413, "body_too_large")
                return
            # Buffer only a bounded body before FastAPI's JSON decoder can see it.
            body = bytearray()
            try:
                async with asyncio.timeout(10):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        chunk = message.get("body", b"")
                        if len(body) + len(chunk) > MAX_BODY_BYTES:
                            await reject(413, "body_too_large")
                            return
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                await reject(408, "body_timeout")
                return
            if length is not None and len(body) != int(length):
                await reject(400, "invalid_length")
                return
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            app_receive = bounded_receive
        else:
            app_receive = receive
        try:
            await self.app(scope, app_receive, secure_send)
        except Exception:
            # Library exception strings may contain input. Do not re-raise them to
            # the server logger. Responses in this app are not streamed from inference.
            if not started:
                await reject(503, "processing_failed")
