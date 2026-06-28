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


def _detect_device() -> str:
    """Resolve 'auto' to a concrete torch device. cuda only when the installed
    wheel actually ships a kernel for this GPU's compute capability — else a
    cu126 wheel on sm_120 (RTX 50-series) silently fails with
    cudaErrorNoKernelImageForDevice. Mirrors
    tests/e2e/test_e2e_coverage.py:_gpu_kernel_supported so probe + skip agree.
    Any failure degrades silently to cpu (never raises).
    """
    try:
        import torch

        if torch.cuda.is_available():
            cap = torch.cuda.get_device_capability(0)
            if f"sm_{cap[0]}{cap[1]}" in torch.cuda.get_arch_list():
                return "cuda"
    except Exception:  # noqa: BLE001 — probe MUST degrade silently
        pass
    return "cpu"


def _resolve_device(name: str, default: str) -> str:
    """Read a device env var; resolve 'auto' to cuda/cpu. The exported value is
    always a concrete device (cuda/cpu), never the literal 'auto', so downstream
    device= consumers (HuggingFaceEmbeddings, CrossEncoder) need no changes."""
    value = os.getenv(name, default)
    if value.strip().lower() == "auto":
        return _detect_device()
    return value


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
EMBEDDING_MODEL_PATH = _get_path("EMBEDDING_MODEL_PATH", "models/local_models/bge-small-zh-v1.5")
EMBEDDING_DIMENSION = _get_int("EMBEDDING_DIMENSION", 512)
EMBEDDING_DEVICE = _resolve_device("EMBEDDING_DEVICE", "auto")
EMBEDDING_NORMALIZE = _get_bool("EMBEDDING_NORMALIZE", True)
EMBEDDING_BATCH_SIZE = _get_int("EMBEDDING_BATCH_SIZE", 8)

# Embedding provider selection (api-only-deploy). ``auto`` resolves to ``local``
# when torch + langchain_huggingface are importable, otherwise ``api`` — this
# makes the airgapped API-only image (torch absent) pick DashScope automatically.
# Note (design §2.3, F-06): ``_detect_device`` short-circuiting on ``api`` is NOT
# how REQ-AO-001 closes; the real closure is the dep restructure (local-models
# extra) + lazy import. Existing ``try: import torch except: cpu`` already degrades
# safely, so EMBEDDING_DEVICE/RERANKER_DEVICE resolve to "cpu" in torch-less images.
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "auto").strip().lower()
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com").rstrip("/")

# Optional cross-encoder reranker. Default on (REQ-RD-001): a Chinese-capable
# cross-encoder is part of the shipped retrieval stack, not an opt-in extra.
# The default model is the local bge-reranker-v2-m3 directory so air-gapped
# deploys load from disk instead of hitting Hugging Face (REQ-RD-002/003).
RERANKER_ENABLED = _get_bool("RERANKER_ENABLED", True)
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
RERANKER_MODEL_PATH = _get_path(
    "RERANKER_MODEL_PATH", "models/local_models/reranker/bge-reranker-v2-m3"
)
RERANKER_DEVICE = _resolve_device("RERANKER_DEVICE", "auto")
RERANKER_WARMUP = _get_bool("RERANKER_WARMUP", False)
RERANKER_CANDIDATE_TOP_K = _get_int("RERANKER_CANDIDATE_TOP_K", 10)
RERANKER_TOP_K = _get_int("RERANKER_TOP_K", 5)
RERANKER_BATCH_SIZE = _get_int("RERANKER_BATCH_SIZE", 8)

# Intent-routing confidence gate (Bug2 Layer ②). A rag_query classified below
# this confidence falls back to general_chat (avoids misrouting ambiguous
# capability/general questions into retrieval). NOTE: prior placeholder — the
# project has no calibration data yet (defender F-06); tuned via hard rag_query
# golden regression cases. Domain-query override (_looks_like_domain_query) is a
# stronger signal and still forces RAG regardless of confidence.
LOW_INTENT_THRESHOLD = _get_float("LOW_INTENT_THRESHOLD", 0.5)

# OpenTelemetry: disabled by default for local development.
OTEL_ENABLED = _get_bool("OTEL_ENABLED", False)
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "rag-platform")
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
OTEL_SAMPLE_RATE = _get_float("OTEL_SAMPLE_RATE", 1.0)
OTEL_CONSOLE_EXPORTER = _get_bool("OTEL_CONSOLE_EXPORTER", False)

# Storage. Do not use the name `MILVUS_URI`; pymilvus reserves it for servers.
MILVUS_URI = os.getenv("MILVUS_DB_URI", "./milvus_data.db")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "t_collection01")

# Vector index tuning. AUTOINDEX is the safe default (works on Milvus Lite).
# Switch to HNSW / IVF_FLAT on a standalone Milvus server for tunable
# recall-vs-latency trade-offs. Index build + search params are JSON env vars.
MILVUS_INDEX_TYPE = os.getenv("MILVUS_INDEX_TYPE", "AUTOINDEX")
MILVUS_INDEX_PARAMS = os.getenv("MILVUS_INDEX_PARAMS", "")  # e.g. {"M":16,"efConstruction":200}
MILVUS_SEARCH_PARAMS = os.getenv("MILVUS_SEARCH_PARAMS", "")  # e.g. {"ef":64} or {"nprobe":10}

# PDF ingestion. OCR is opt-in because local OCR engines add non-trivial
# dependencies and memory usage.
PDF_EXTRACT_TABLES = _get_bool("PDF_EXTRACT_TABLES", True)
PDF_OCR_ENABLED = _get_bool("PDF_OCR_ENABLED", False)
PDF_OCR_ENGINE = os.getenv("PDF_OCR_ENGINE", "paddleocr")
PDF_OCR_LANG = os.getenv("PDF_OCR_LANG", "ch")
PDF_OCR_DPI = _get_int("PDF_OCR_DPI", 220)
PDF_OCR_MIN_TEXT_CHARS = _get_int("PDF_OCR_MIN_TEXT_CHARS", 20)
PDF_ASSET_DIR = _get_path("PDF_ASSET_DIR", "data/document_assets")
