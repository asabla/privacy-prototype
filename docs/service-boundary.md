# Submitted-text service boundary

The inbox at `/` uses only repository fixtures. On loopback, `/api/engine`,
`/api/config`, `/api/corpus`, and `/api/scan-all` are public read endpoints.
`/api/scan` accepts arbitrary text and requires a configured operator key. Without
one it returns `503 input_disabled`; missing or invalid credentials return `401`.
No query-string credentials, cookies, or browser persistence are used.

## Local setup

Create an ephemeral key in the shell and start the server without printing it:

```sh
export SENTINEL_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
make run
```

Use the key from the same environment in a client. This Python example sends a
synthetic value without putting the key in command arguments or printing it:

```sh
uv run --no-sync python - <<'PY'
import json, os, urllib.request
request = urllib.request.Request(
    "http://127.0.0.1:8000/api/scan",
    data=json.dumps({"text": "Contact alice@example.com"}).encode(),
    headers={"Authorization": "Bearer " + os.environ["SENTINEL_API_KEY"],
             "Content-Type": "application/json"},
)
with urllib.request.urlopen(request) as response:
    print(response.read().decode())
PY
```

The key represents one operator, with no roles or tenant separation. Use a secret
manager for deployment, rotate the key by restarting, and do not commit it in a
configuration file. An environment variable is available to the process and
privileged local operators; it is not a hardware-protected credential store.

## Input and response contract

`POST /api/scan` accepts JSON `{ "text": "...", "include_source": false }`.
Unknown fields and non-boolean inspection flags are rejected. The default response
has engine, label counts, Unicode code-point ranges, placeholders, and redacted
text. It excludes the `text` field and each span's original matched `text`.
Authenticated diagnostic clients may explicitly set `include_source: true` to
receive those fields. The fixture API and local `make scan` command include source
values by design. Never direct their output to a shared log containing real data.

The redacted result can still contain sensitive content the detector missed. This
endpoint is not a reviewed export or an assertion that sharing is safe. Downstream
applications must keep the result in the same sensitive-data boundary until review.

Requests are limited to 65,536 body bytes and 16,000 Unicode code points per scan.
Both declared length and streamed bytes are checked before JSON decoding, with a
10-second body-read deadline. Compressed bodies and non-JSON input are rejected.
One inference operation runs per process; competing scans, including fixture
batches, return `429 processing_busy` with `Retry-After: 1`. The provided server
command caps concurrent connections at 16. A running model call is not abandoned
on a timeout while another request starts; it retains the inference slot until it
returns. A stuck model requires an operator restart. Use one worker for this reference.

Errors return fixed codes and never validation values or model exception strings.
API errors include `invalid_request`, `authentication_required`, `body_too_large`,
`origin_rejected`, and `processing_failed`. The application does not log request
bodies, keys, or inference exception strings. The supplied run command disables
access logs so URLs cannot become a secondary input channel. Reverse proxies,
APM agents, model libraries, crash dumps, swap, terminal output, and infrastructure
logs need their own operational controls; the application cannot sanitize them.

## Browser and host protections

Default allowed hosts are `127.0.0.1`, `localhost`, and `::1`. Unexpected hosts,
foreign origins, and cross-site browser fetches are rejected. Browser requests must
use the same scheme, host, and port as the page. There is no wildcard CORS access.
All application responses carry `Cache-Control: no-store`, a self-only script and
connection policy, anti-framing, no-referrer, and MIME-sniffing protections. Inline
styles remain allowed for the existing inbox UI; inline scripts are disallowed.
Interactive API documentation is disabled to avoid external CDN assets.

For an explicitly configured host, set `SENTINEL_ALLOWED_HOSTS` to comma-separated
hostnames without schemes, wildcards, or ports. A non-loopback host requires a key
and HTTPS, and every API endpoint then requires authentication. Terminate TLS in a
controlled reverse proxy and configure Uvicorn to trust forwarding headers only
from that proxy. Do not expose the default development server to the network.
The existing fixture dashboard is a loopback demo and does not supply a key.

`GET /health` proves the HTTP service is responding. `GET /ready` requires a
successful nonempty inference and resets after inference failure. `make serve`
preloads inference before accepting traffic; see [runtime operation](runtime.md).
Raw text has no database
or application disk persistence; Python and model memory are not securely erased
after a request. Treat the machine as part of the sensitive-data boundary.

## Verification

`make check` covers missing/invalid/duplicate authentication, explicit inspection,
safe validation and inference errors, streamed and declared body limits, host and
origin rejection, HTTPS enforcement, security headers, and concurrent processing
with recovery. `make test-opf` uses a generated in-memory key and explicitly opts
into source inspection for its real-model consistency checks.
