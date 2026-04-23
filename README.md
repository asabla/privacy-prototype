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
make install       # uv sync — creates .venv and resolves deps from pyproject.toml
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
make install-opf     # clones openai/privacy-filter into .opf-src and installs it editable
make engine          # prints the active engine
```

First run downloads the model weights (~1.5B params) to `~/.opf/privacy_filter`. To go back:

```bash
make uninstall-opf
```

## Handy targets

| Target | What it does |
| --- | --- |
| `make install` | `uv sync` against `pyproject.toml` |
| `make lock` | Refresh `uv.lock` |
| `make run` | Start the dev server (auto-reload) |
| `make engine` | Print the active detection engine |
| `make scan` | Pipe stdin through the detector (`echo 'hi alice@acme.com' \| make scan`) |
| `make install-opf` / `make uninstall-opf` | Swap the detection engine |
| `make clean` | Purge `__pycache__` and `.pyc` |
| `make reset` | `clean` + wipe `.venv` and `.opf-src` |

## Credits

Detection is powered by [OpenAI Privacy Filter](https://github.com/openai/privacy-filter) — a 1.5B-parameter bidirectional token classifier for PII detection, Apache 2.0 licensed.
