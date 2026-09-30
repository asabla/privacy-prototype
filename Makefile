PORT   ?= 8000
OPF_SRC ?= .opf-src
OPF_EXTRA = $(if $(wildcard .opf-enabled),--extra opf)

.PHONY: help install run dev scan open install-opf uninstall-opf engine clean reset lock test test-python test-js audit audit-python audit-js check

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Sync the uv-managed venv with pyproject.toml
	uv sync --locked $(OPF_EXTRA)

lock:  ## Refresh uv.lock from pyproject.toml
	uv lock

run: install  ## Start the server on $PORT (default 8000)
	uv run --no-sync uvicorn backend.main:app --reload --port $(PORT)

dev: run  ## Alias for `run`

open:  ## Open the app in the default browser
	@open http://127.0.0.1:$(PORT)

engine: install  ## Print which detection engine is active
	@uv run --no-sync python -c "from backend.detector import get_detector; d = get_detector(); print(d.engine_detail)"

scan: install  ## Pipe stdin text through the detector (e.g. `echo 'hi alice@acme.com' | make scan`)
	@uv run --no-sync python -c "import sys, json; from backend.detector import get_detector; print(json.dumps(get_detector().detect(sys.stdin.read()).to_dict(), indent=2))"

install-opf:  ## Enable the pinned OPF optional dependency for subsequent make commands
	uv sync --locked --extra opf
	@touch .opf-enabled
	@echo "OPF enabled. Run make engine to initialize the model, or make run to start the app."

uninstall-opf:  ## Remove OPF from the venv (back to heuristic mode)
	uv sync --locked
	@rm -f .opf-enabled
	@echo "Heuristic mode enabled."

test: test-python test-js  ## Run backend and frontend regression tests

test-python: install
	uv run --no-sync pytest -q

test-js:
	npm ci
	npm test

check: test audit  ## Run regression tests and dependency vulnerability audits

audit: audit-python audit-js  ## Audit locked Python and JavaScript dependencies

audit-python: install
	@set -eu; requirements=$$(mktemp); trap 'rm -f "$$requirements"' EXIT; \
	uv export --locked --all-extras --no-emit-project --no-emit-package opf --no-header --no-annotate > "$$requirements"; \
	uv run --no-sync pip-audit --strict --disable-pip --require-hashes -r "$$requirements"

audit-js:
	npm audit

clean:  ## Remove Python caches
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

reset: clean  ## Wipe the venv and the cloned OPF source
	rm -rf .venv $(OPF_SRC) .opf-enabled
