FROM ghcr.io/astral-sh/uv:0.12.21@sha256:a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711 AS uv
FROM python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache

FROM builder AS opf-builder
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN uv sync --locked --no-dev --no-cache --extra opf

FROM python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOME=/tmp SENTINEL_ENGINE=heuristic SENTINEL_PRELOAD=1
COPY backend ./backend
COPY frontend ./frontend
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=2).close()"]
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "16", "--timeout-graceful-shutdown", "30"]

FROM runtime AS opf
COPY --from=opf-builder /app/.venv /app/.venv
COPY ops/model_assets.py ./ops/model_assets.py
ENV SENTINEL_ENGINE=opf OPF_DEVICE=cpu OPF_ASSETS_DIR=/models \
    OPF_CHECKPOINT=/models/checkpoint/original TIKTOKEN_CACHE_DIR=/models/tokenizer-cache \
    HF_HOME=/tmp/huggingface HF_HUB_OFFLINE=1 HF_HUB_DISABLE_IMPLICIT_TOKEN=1 \
    HF_HUB_DISABLE_TELEMETRY=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
CMD ["python", "-m", "ops.model_assets", "--serve"]

# Keep the small demonstration image as the default build target.
FROM runtime AS heuristic
COPY --from=builder /app/.venv /app/.venv
