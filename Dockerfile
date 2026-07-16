# Multi-stage Dockerfile for the API-only deploy profile.
#
# Produces a < 4 GB image with ZERO PyTorch: LLM via DashScope Qwen
# (OpenAI-compatible), embeddings via DashScope text-embedding-v3 (native API),
# reranker disabled. See docs/specs/api-only-deploy/.
#
# Secrets (DASHSCOPE_API_KEY, OPENAI_API_KEY, ADMIN_API_KEY) MUST be injected at
# runtime (`docker run -e ...` or a secret mount) — they are NEVER baked in.

# ───────────────────────── Stage 1: web builder ──────────────────────────────
FROM node:20.20.2-bookworm-slim AS web-builder
WORKDIR /workspace

# `web` is an npm workspace; the canonical lock lives at the repository root.
# Debian/glibc matches the Rollup native artifact recorded in that lock.
COPY package.json package-lock.json ./
COPY web/package.json ./web/package.json
RUN node --version \
    && npm --version \
    && npm ci --workspace web --ignore-scripts \
    && npm ls 'dompurify@>=3.4.11' --workspace web \
    && npm ls dompurify --workspace web
COPY web/ ./web/
RUN npm run build --workspace web

# ───────────────────────── Stage 2: app ──────────────────────────────────────
FROM python:3.13-slim AS app

# uv 版本与 hosted workflows 固定一致，避免 export/hash 语义随 latest 漂移。
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /usr/local/bin/uv

ARG UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/
ARG UV_SYNC_TIMEOUT_SECONDS=600

ENV UV_PROJECT_ENVIRONMENT=/app/venv \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先安装依赖层；canonical lock 保留国内源，build arg 决定本次 artifact index。
COPY pyproject.toml uv.lock ./
COPY scripts/sync_locked_deps.sh ./scripts/
RUN UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX" \
    UV_SYNC_TIMEOUT_SECONDS="$UV_SYNC_TIMEOUT_SECONDS" \
    bash scripts/sync_locked_deps.sh api-only

# Copy application source and the built frontend.
COPY . .
COPY --from=web-builder /workspace/web/dist ./web/dist

# Non-secret runtime defaults. Secrets are injected at `docker run`.
ENV EMBEDDING_PROVIDER=api \
    RERANKER_ENABLED=false \
    EMBEDDING_MODEL=text-embedding-v3 \
    EMBEDDING_DIMENSION=512 \
    MILVUS_SPARSE_INDEX=false \
    OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 \
    MILVUS_DB_URI=/app/data/milvus_data.db

EXPOSE 8000

# Healthcheck: the admin health endpoint is the cheapest liveness probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/admin/health',timeout=3).status==200 else 1)" || exit 1

CMD ["uv", "run", "--frozen", "--no-sync", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
