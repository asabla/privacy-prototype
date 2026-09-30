# Run the reference reliably

Use one process for this single-operator reference. Pending reviews are in-memory
and process-bound; restarts, key rotation, and a different worker invalidate them.
The UI asks for a new analysis when a receipt is unavailable.

## Native service

```sh
make install
export SENTINEL_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
# Transfer the key to your clipboard before starting; never print or commit it.
SENTINEL_ENGINE=heuristic make serve
```

`make serve` binds `127.0.0.1:8000`, preloads inference, disables reload, access logs,
and forwarded-header trust, and caps concurrent connections at 16. `PORT` overrides
the port. `make run` remains the reload-enabled development command, with lazy
initialization unless `SENTINEL_PRELOAD=1` is set.

| Setting | Contract |
| --- | --- |
| `SENTINEL_ENGINE=auto` | Default; selects OPF when installed, otherwise the heuristic. Broken OPF never falls back. |
| `SENTINEL_ENGINE=heuristic` | Explicit synthetic demonstration engine, even when OPF is installed. |
| `SENTINEL_ENGINE=opf` | Requires OPF; missing package or invalid configuration fails startup. |
| `SENTINEL_PRELOAD=1` | Run non-sensitive synthetic inference before accepting traffic. `0` is lazy mode. Other values fail startup. |
| `SENTINEL_API_KEY` | Random URL-safe operator key, 32–256 characters. Unset disables submitted input. |
| `SENTINEL_ALLOWED_HOSTS` | Explicit lowercase hosts; defaults to loopback. Non-loopback requires a key and HTTPS. |

`GET /health` checks HTTP liveness. `GET /ready` returns `503 engine_not_ready`
until a nonempty inference succeeds, then `200` with the active engine. A failed
inference clears readiness; a later successful one restores it. Readiness proves
initialization and the last completed inference, not accuracy or spare capacity.
A failed preload prevents startup and emits a fixed diagnostic without the model's
exception value. Verify the configured engine, checkpoint and permissions locally.

The inference slot stays occupied until the model returns. Other scans get `429`
instead of building an unbounded inference queue. The server can also return `503`
at its connection limit. A hung native model call requires an operator restart;
this reference does not claim to safely interrupt arbitrary native inference.

## Container demonstration

The default container uses the heuristic and demonstrates the complete review
contract without model weights. The real-model override below retains the same
network boundary and review API.

```sh
export SENTINEL_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
# Copy the key to the workbench using your clipboard manager.
docker compose up --build --detach --wait
# Open http://127.0.0.1:8000/workbench and connect.
docker compose down
```

Compose requires the key. It publishes only the browser proxy on IPv4 loopback.
The processor runs UID/GID 10001 with a read-only root filesystem, a 16 MiB temporary filesystem, no Linux
capabilities, and no privilege escalation. It sets a 512 MiB memory limit, 64-process
limit, two-CPU cap, and disables core dumps. The image copies only the application
and locked runtime environment; no Git metadata, tests, secrets, or model cache
enter the build context. Python and uv images are pinned by version and digest.

The processor joins only an internal Docker network with no external route and
publishes no ports. An unprivileged NGINX proxy bridges the browser port to it;
Docker does not publish ports for an internal-only service. The proxy preserves
the browser Host header and disables access/error request logs, request/response
buffering, and proxy temporary response files. Its root filesystem is read-only,
its only bind mount is static configuration, and its temporary directories use RAM.
It runs UID/GID 101 with dropped capabilities, no privilege escalation, 64 MiB
memory, one CPU, and 32 processes. The proxy handles source text and is part of the
trusted boundary; it has an external network route, unlike the processor.

The host and Docker daemon remain trusted: an internal network is not isolation
from a privileged host. No persistent data volume is mounted. Docker diagnostic logs are bounded to
one 5 MB file with compression disabled; request access logs remain off. Stop/remove
the service when finished, and manage Docker's own logs and storage under host policy.

`make test-container` builds an independent project with a generated ephemeral key
and port, verifies runtime restrictions and an external connection failure, exercises
all three reviewed exports, rejects replay, records a burst of concurrent requests
and subsequent recovery, and proves
that a restart invalidates pending receipts. It also checks captured logs for its
synthetic sentinels, and removes its containers and network in a `finally` block.
CI runs this gate on Linux; local validation also exercises Docker on macOS/arm64.
The exact busy count depends on scheduling; a fast heuristic run can accept every
request. A separate deterministic test holds the inference slot and proves that
competing requests get `429`, then succeed after release.

## Real OPF container

Provision public model assets before accepting any input. This setup command uses
only the pinned public URLs in `ops/model_assets.py`; it does not use saved registry
credentials or send application data. Existing files are verified, never silently
replaced. Failed downloads are removed. The checkpoint revision is
`7ffa9a043d54d1be65afb281eddf0ffbe629385b`; all four checkpoint files and the
`o200k_base` tokenizer have fixed byte counts and SHA-256 digests.

```sh
export OPF_ASSETS_DIR="$PWD/.model-assets"
python3 -m ops.model_assets --download
python3 -m ops.model_assets                 # verify existing files, no network
export SENTINEL_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
# Transfer the key to the workbench through your clipboard; never print or commit it.
docker compose -f compose.yaml -f compose.opf.yaml up --build --detach --wait --wait-timeout 180
# Open http://127.0.0.1:8000/workbench and connect.
docker compose -f compose.yaml -f compose.opf.yaml down
```

Use Python 3.11 or newer for the standalone asset helper. The application uses
Python 3.14. The asset directory must be absolute, readable by UID 10001 and
available to the Docker daemon as a bind mount. The default `.model-assets/` is
ignored by Git and excluded from the image build context. A private host temporary
directory may not be shared with Docker; choose a shared local path instead of
changing the network or filesystem protections. The download command requires
network access during setup; verification and service startup do not.

The `opf` image target installs the pinned OPF package and Torch 2.14.0 CPU wheels
from the [official CPU index](https://download.pytorch.org/whl/cpu/torch/), using
[uv's explicit index selection](https://docs.astral.sh/uv/guides/integration/pytorch/).
Linux GPU libraries are not installed. Git and uv stay in the
build stage. Model weights remain outside the image and are mounted read-only at
`/models`. Startup verifies every asset digest before model preload; missing or
changed assets stop the process. It requires OPF, forces CPU and offline Hugging
Face settings, and uses the preloaded tokenizer cache. No runtime download or
heuristic fallback is allowed by this path.

The override sets an 8 GiB memory limit and 128-process limit; the two-CPU cap,
read-only root, 16 MiB temporary filesystem, non-root user, dropped capabilities,
disabled core dumps and internal-only processor network are inherited. These are
the tested resource settings, not minimum requirements or a throughput guarantee.
The host and proxy remain trusted. Host administrators can still read or change
mounted model files and inspect process memory.

```sh
make test-container-opf
```

This opt-in gate verifies real model readiness, CPU-only imports, read-only model
mounts, blocked external connections, all three review/export workflows, multiline
credential coverage, burst rejection/recovery, receipt invalidation after restart,
and absence of test inputs in container logs. It removes its temporary Compose
project. Regular Linux CI builds the CPU image and proves that offline startup with
missing assets fails; it does not download model weights or claim inference coverage.
The complete gate was run against the real checkpoint on Linux/arm64 from this
macOS checkout. GPU execution is outside the validated path.

Model provenance: [pinned checkpoint](https://huggingface.co/openai/privacy-filter/tree/7ffa9a043d54d1be65afb281eddf0ffbe629385b/original),
[public tokenizer](https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken).

## Native OPF without network access

Install the pinned optional dependencies with `make install-opf`. In a controlled
setup phase, populate the model checkpoint and tokenizer cache using synthetic
input only. Fix the checkpoint revision and retain its provenance for repeatable
comparisons. This reference was checked with OpenAI's checkpoint revision
`7ffa9a043d54d1be65afb281eddf0ffbe629385b`. Provisioning can contact package and
model registries; user input must not be present during that phase.

```sh
export OPF_CHECKPOINT=/absolute/path/to/checkpoint/original
export TIKTOKEN_CACHE_DIR=/absolute/path/to/tokenizer-cache
export HF_HOME=/absolute/path/to/huggingface-cache
export OPF_DEVICE=cpu
export HF_HUB_OFFLINE=1 HF_HUB_DISABLE_IMPLICIT_TOKEN=1 HF_HUB_DISABLE_TELEMETRY=1
SENTINEL_ENGINE=opf make serve
```

The paths must already exist and be readable by the operator. The model's constructor
alone does not initialize its lazy runtime; `make serve` executes inference before
accepting traffic. Missing assets fail instead of selecting the heuristic.

For a repeatable acceptance check, first provision the isolated `OPF_TEST_ENV` with
`make test-opf`. With its dependencies, checkpoint, and tokenizer cache available,
run `make test-opf-offline` using the same environment and paths. That command makes
uv offline, disables Hugging Face network use, denies Python TCP/UDP connections
and DNS calls, preloads the real model, and exercises the 25 synthetic emails plus
all three review/export flows. It does not substitute for an operating-system
egress policy over native libraries. Apply a host firewall or equivalent network
boundary before accepting sensitive input in a deployed real-model service.

## Hosted extension

The provided commands and Compose file are for local use. A hosted adaptation needs
TLS, controlled proxy trust, real user identities and authorization, tenant isolation,
secret distribution, and operational retention controls. Do not add workers behind
a load balancer while relying on process-local receipts. See the service-boundary
and review-contract documents before changing these boundaries.

The container design follows the [uv Docker guide](https://docs.astral.sh/uv/guides/integration/docker/),
[Compose service controls](https://docs.docker.com/reference/compose-file/services/),
and [internal network definition](https://docs.docker.com/reference/compose-file/networks/).
