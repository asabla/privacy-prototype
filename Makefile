PORT   ?= 8000
OPF_SRC ?= .opf-src
OPF_EXTRA = $(if $(wildcard .opf-enabled),--extra opf)
OPF_TEST_ENV ?= .venv-opf
EVAL_ARGS ?=

.PHONY: help install run serve dev scan open install-opf uninstall-opf engine clean reset lock test test-python test-js test-workbench-api test-container audit audit-python audit-js check eval eval-extended eval-opf test-opf test-opf-offline

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Sync the uv-managed venv with pyproject.toml
	uv sync --locked $(OPF_EXTRA)

lock:  ## Refresh uv.lock from pyproject.toml
	uv lock

run: install  ## Start the server on $PORT (default 8000)
	uv run --no-sync uvicorn backend.main:app --host 127.0.0.1 --reload --port $(PORT) --no-access-log --limit-concurrency 16

serve: install  ## Preload inference and serve one process without reload
	SENTINEL_PRELOAD=1 uv run --no-sync uvicorn backend.main:app --host 127.0.0.1 --port $(PORT) --no-access-log --no-proxy-headers --limit-concurrency 16 --timeout-graceful-shutdown 30

dev: run  ## Alias for `run`

open:  ## Open the app in the default browser
	@open http://127.0.0.1:$(PORT)/workbench

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

test: test-python test-js test-workbench-api  ## Run backend, frontend, and HTTP integration tests

test-python: install
	uv run --no-sync pytest -q

test-js:
	npm ci
	npm test

test-workbench-api: install test-js  ## Exercise the actual workbench against authenticated HTTP
	uv run --no-sync python -m evaluation.workbench_smoke

test-container:  ## Build and verify the isolated Compose service (requires Docker)
	python3 -m evaluation.container_smoke

eval: install  ## Score the heuristic against the reviewed synthetic baseline
	uv run --no-sync python -m evaluation.run --engine heuristic --baseline evaluation/heuristic-baseline.json $(EVAL_ARGS)

eval-extended: install  ## Score Swedish, forwarded, credential, boundary and negative cases
	uv run --no-sync python -m evaluation.run --engine heuristic --dataset evaluation/extended-cases.json --baseline evaluation/heuristic-extended-baseline.json $(EVAL_ARGS)

eval-opf:  ## Evaluate real OPF in an isolated venv (may download model weights)
	UV_PROJECT_ENVIRONMENT="$(OPF_TEST_ENV)" uv run --locked --extra opf python -m evaluation.run --engine opf $(EVAL_ARGS)

test-opf:  ## Require real OPF and validate API inference over synthetic messages
	UV_PROJECT_ENVIRONMENT="$(OPF_TEST_ENV)" uv run --locked --extra opf python -m evaluation.smoke

test-opf-offline:  ## Require cached real OPF startup and inference with outbound sockets denied
	UV_PROJECT_ENVIRONMENT="$(OPF_TEST_ENV)" uv run --locked --offline --extra opf python -m evaluation.offline_smoke

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
