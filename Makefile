PORT   ?= 8000
OPF_SRC ?= .opf-src

.PHONY: help install run dev scan open install-opf uninstall-opf engine clean reset lock

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Sync the uv-managed venv with pyproject.toml
	uv sync

lock:  ## Refresh uv.lock from pyproject.toml
	uv lock

run: install  ## Start the server on $PORT (default 8000)
	uv run uvicorn backend.main:app --reload --port $(PORT)

dev: run  ## Alias for `run`

open:  ## Open the app in the default browser
	@open http://127.0.0.1:$(PORT)

engine: install  ## Print which detection engine is active
	@uv run python -c "from backend.detector import get_detector; d = get_detector(); print(d.engine_detail)"

scan: install  ## Pipe stdin text through the detector (e.g. `echo 'hi alice@acme.com' | make scan`)
	@uv run python -c "import sys, json; from backend.detector import get_detector; print(json.dumps(get_detector().detect(sys.stdin.read()).to_dict(), indent=2))"

install-opf: install  ## Clone + install OpenAI privacy-filter into the venv
	@if [ ! -d $(OPF_SRC) ]; then \
	  git clone https://github.com/openai/privacy-filter $(OPF_SRC); \
	fi
	uv pip install -e $(OPF_SRC)
	@echo
	@echo "Engine now reports:"
	@$(MAKE) -s engine

uninstall-opf:  ## Remove OPF from the venv (back to heuristic mode)
	-uv pip uninstall opf
	@echo "Engine now reports:"
	@$(MAKE) -s engine

clean:  ## Remove Python caches
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete

reset: clean  ## Wipe the venv and the cloned OPF source
	rm -rf .venv $(OPF_SRC)
