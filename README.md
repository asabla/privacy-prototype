# Sentinel — Email Privacy Scanner

A small proof-of-concept that watches a synthetic corporate inbox and flags messages carrying sensitive data before they leave the building. Every message is classified by direction (inbound / outbound / internal), domain ownership, and the PII spans found in the body and subject.

Detection runs through [OpenAI's Privacy Filter (`opf`)](https://github.com/openai/privacy-filter) when it is installed in the venv, and falls back to a regex heuristic so the demo boots on a fresh machine. The active engine is shown in the top-right corner of the dashboard.

## Screenshots

### Live dashboard
A simulated inbox streams past with per-direction counts, PII label breakdowns, and sensitivity badges.

![Sentinel dashboard](docs/application_example_1.png)

### Inspection drawer
Clicking a message opens a drawer with highlighted spans, classification badges, and a redacted view.

![Inspection drawer](docs/application_example_2.png)

### Underlying engine (OPF)
When the real `opf` model is installed, span detection uses OpenAI Privacy Filter. Their own demo (bundled in the [privacy-filter repo](https://github.com/openai/privacy-filter)) looks like this:

![OpenAI Privacy Filter demo](docs/privacy_filter_example.png)

OPF detects eight span types: `private_person`, `private_email`, `private_phone`, `private_address`, `private_url`, `private_date`, `account_number`, `secret`. The heuristic fallback targets the same labels with coarse regexes.

## Stack

- **Backend:** FastAPI + Uvicorn (Python 3.14, managed by [uv](https://docs.astral.sh/uv/))
- **Frontend:** static HTML/CSS/JS served from `frontend/`, no build step
- **Detection:** `opf` (optional) or regex fallback, selected at runtime in `backend/detector.py`

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python 3.14 (uv will download it if missing).

```bash
make install       # uv sync --locked — creates .venv from uv.lock
make run           # starts uvicorn on :8000 with reload
make open          # opens http://127.0.0.1:8000 in the browser
```

Or without `make`:

```bash
uv sync
uv run uvicorn backend.main:app --reload --port 8000
```

## Switching to the real OPF engine

The heuristic mode is always available. To swap in OpenAI's model:

```bash
make install-opf     # installs the pinned OPF optional dependency
make engine          # initializes the adapter and prints the selected engine
```

The selection is saved in the ignored `.opf-enabled` file. Subsequent `make install`,
`make run`, `make engine`, and `make scan` commands retain OPF. The upstream revision
is pinned in `pyproject.toml` and resolved in `uv.lock`; no editable clone is required.

The first initialization downloads missing model weights to `~/.opf/privacy_filter`.
Set `OPF_CHECKPOINT` to use an existing checkpoint directory. CPU is the default;
use `OPF_DEVICE=cuda make run` on a CUDA-capable machine. The engine command reports
adapter selection; use `make scan` to exercise inference.

To go back:

```bash
make uninstall-opf
```

Restart a running server after switching engines. When running uv directly, include
`--extra opf` in both `uv sync` and `uv run` to select OPF; the saved selection applies
to the Makefile commands.

## Checks

```bash
make test           # Python/API/engine-workflow tests, then frontend DOM tests
```

Tests require Node.js 22.22.2, 24.15+, or 26+ in addition to Python and uv. Frontend test
dependencies are development-only; serving the UI still requires no build step.
GitHub Actions runs the same command. Tests use synthetic data and an offline OPF
test double, so they do not download model weights or verify real model inference.

Scan responses declare `offset_unit: "unicode_code_points"`. Span offsets are
zero-based, start-inclusive and end-exclusive. Both engines normalize overlapping
matches into disjoint spans covering every matched character, with secrets taking
label precedence. The UI highlights using this offset contract and displays the
backend's `redacted_text` when redaction is selected.

## Handy targets

| Target | What it does |
| --- | --- |
| `make install` | Sync locked dependencies, retaining the selected engine |
| `make lock` | Refresh `uv.lock` |
| `make run` | Start the dev server (auto-reload) |
| `make engine` | Print the active detection engine |
| `make scan` | Pipe stdin through the detector (`echo 'hi alice@acme.com' \| make scan`) |
| `make install-opf` / `make uninstall-opf` | Swap the detection engine |
| `make test` | Run backend, API, engine-switching, and frontend regression tests |
| `make clean` | Purge `__pycache__` and `.pyc` |
| `make reset` | `clean` + wipe `.venv`, legacy `.opf-src`, and engine selection |

## Credits

Detection is powered by [OpenAI Privacy Filter](https://github.com/openai/privacy-filter) — a 1.5B-parameter bidirectional token classifier for PII detection, Apache 2.0 licensed.
