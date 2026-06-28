# Multi-stage Dockerfile for the API-only deploy profile.
#
# Produces a < 4 GB image with ZERO PyTorch: LLM via DashScope Qwen
# (OpenAI-compatible), embeddings via DashScope text-embedding-v3 (native API),
# reranker disabled. See docs/specs/api-only-deploy/.
#
# Secrets (DASHSCOPE_API_KEY, OPENAI_API_KEY, ADMIN_API_KEY) MUST be injected at
# runtime (`docker run -e ...` or a secret mount) — they are NEVER baked in.

# ───────────────────────── Stage 1: web builder ──────────────────────────────
FROM node:20-alpine AS web-builder
WORKDIR /web
# Copy manifests first for layer caching.
COPY web/package.json web/package-lock.json* ./
# `npm install` (not `npm ci`) tolerates lockfile drift across npm versions;
# the web-builder is a throwaway stage, so reproducibility is not the goal here
# (the committed lockfile still drives local/CI installs).
RUN npm install
COPY web/ .
RUN npm run build  # → /web/dist (vue-tsc typecheck + vite build)

# ───────────────────────── Stage 2: app ──────────────────────────────────────
FROM python:3.13-slim AS app

# uv: install the pinned copy declared in pyproject's dependency-groups, then
# make it invocable on PATH. Using the official installer keeps versions in sync
# with the lockfile rather than pulling a floating image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/app/venv \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer cache: only rebuild when pyproject/lock change).
# api-only extra = torch-less profile (base deps already exclude torch).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra api-only

# Copy application source and the built frontend.
COPY . .
COPY --from=web-builder /web/dist ./web/dist

# Non-secret runtime defaults. Secrets are injected at `docker run`.
ENV EMBEDDING_PROVIDER=api \
    RERANKER_ENABLED=false \
    EMBEDDING_MODEL=text-embedding-v3 \
    EMBEDDING_DIMENSION=512 \
    OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 \
    MILVUS_DB_URI=/app/data/milvus_data.db

EXPOSE 8000

# Healthcheck: the admin health endpoint is the cheapest liveness probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/admin/health',timeout=3).status==200 else 1)" || exit 1

CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
