"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# Explicit process/container environment variables take precedence over `.env`.
load_dotenv(override=False)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_path(name: str, default: str) -> str:
    value = os.getenv(name, default)
    if not value:
        return ""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path.resolve())


# LLM: any OpenAI-compatible endpoint.
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "ollama")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:14b")
LLM_TEMPERATURE = _get_float("LLM_TEMPERATURE", 0.0)
LLM_MAX_TOKENS = _get_int("LLM_MAX_TOKENS", 4096)
LLM_TIMEOUT = _get_float("LLM_TIMEOUT", 60.0)
LLM_MAX_RETRIES = _get_int("LLM_MAX_RETRIES", 1)

# Embedding: local path is preferred when it exists; otherwise model ID is used.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
EMBEDDING_MODEL_PATH = _get_path(
    "EMBEDDING_MODEL_PATH", "models/local_models/bge-small-zh-v1.5"
)
EMBEDDING_DIMENSION = _get_int("EMBEDDING_DIMENSION", 512)
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")
EMBEDDING_NORMALIZE = _get_bool("EMBEDDING_NORMALIZE", True)
EMBEDDING_BATCH_SIZE = _get_int("EMBEDDING_BATCH_SIZE", 8)

# Optional cross-encoder reranker.
RERANKER_ENABLED = _get_bool("RERANKER_ENABLED", False)
RERANKER_MODEL = os.getenv(
    "RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
)
RERANKER_MODEL_PATH = _get_path("RERANKER_MODEL_PATH", "")
RERANKER_DEVICE = os.getenv("RERANKER_DEVICE", "cpu")
RERANKER_WARMUP = _get_bool("RERANKER_WARMUP", False)
RERANKER_CANDIDATE_TOP_K = _get_int("RERANKER_CANDIDATE_TOP_K", 10)
RERANKER_TOP_K = _get_int("RERANKER_TOP_K", 5)
RERANKER_BATCH_SIZE = _get_int("RERANKER_BATCH_SIZE", 8)

# OpenTelemetry: disabled by default for local development.
OTEL_ENABLED = _get_bool("OTEL_ENABLED", False)
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "rag-platform")
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
OTEL_SAMPLE_RATE = _get_float("OTEL_SAMPLE_RATE", 1.0)
OTEL_CONSOLE_EXPORTER = _get_bool("OTEL_CONSOLE_EXPORTER", False)

# Storage. Do not use the name `MILVUS_URI`; pymilvus reserves it for servers.
MILVUS_URI = os.getenv("MILVUS_DB_URI", "./milvus_data.db")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "t_collection01")
