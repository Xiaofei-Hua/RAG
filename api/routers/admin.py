"""
Admin Router for Enterprise RAG Platform

Handles system administration and monitoring endpoints.
"""

from __future__ import annotations

from typing import Dict, Any

from fastapi import APIRouter

from utils.log_utils import log

router = APIRouter()


@router.get("/health")
async def health_check():
    """Detailed health check."""
    from core.fallback.circuit_breaker import get_llm_circuit, get_retriever_circuit
    from core.memory.redis_memory import get_session_memory

    llm_circuit = get_llm_circuit()
    retriever_circuit = get_retriever_circuit()

    # Check services
    services = {
        "llm": {
            "status": "healthy" if llm_circuit.state.value == "closed" else "degraded",
            "circuit": llm_circuit.state.value,
            "stats": llm_circuit.stats,
        },
        "retriever": {
            "status": "healthy" if retriever_circuit.state.value == "closed" else "degraded",
            "circuit": retriever_circuit.state.value,
            "stats": retriever_circuit.stats,
        },
    }

    # Check vector database
    try:
        from documents.milvus_db import get_milvus_manager
        manager = get_milvus_manager()
        health = manager.health_check()
        services["milvus"] = {
            "status": "healthy" if health.get("connected") else "unhealthy",
            "details": health,
        }
    except Exception as e:
        services["milvus"] = {
            "status": "unhealthy",
            "error": str(e),
        }

    from utils.env_utils import RERANKER_ENABLED
    if RERANKER_ENABLED:
        from core.retrieval.reranker import get_reranker

        reranker_status = get_reranker().status()
        services["reranker"] = {
            "status": (
                "healthy"
                if reranker_status["loaded"]
                else "degraded"
                if reranker_status["load_error"]
                else "ready"
                if reranker_status["cached"]
                else "cold"
            ),
            "details": reranker_status,
        }

    # Overall status
    all_healthy = all(
        s.get("status") in ("healthy", "degraded", "ready", "cold")
        for s in services.values()
    )

    return {
        "status": "healthy" if all_healthy else "degraded",
        "services": services,
    }


@router.get("/metrics")
async def get_metrics():
    """Get system metrics."""
    import time
    import gc
    import platform

    result = {
        "timestamp": time.time(),
        "memory": {},
        "gc": {},
        "python": {
            "version": platform.python_version(),
        },
    }

    # Memory usage - with error handling
    try:
        import psutil
        process = psutil.Process()
        memory_info = process.memory_info()
        result["memory"] = {
            "rss_mb": memory_info.rss / 1024 / 1024,
            "vms_mb": memory_info.vms / 1024 / 1024,
        }
    except ImportError:
        result["memory"] = {"error": "psutil not installed"}
    except Exception as e:
        result["memory"] = {"error": str(e)}

    # GC stats - with error handling
    try:
        gc_stats_list = gc.get_stats()
        if gc_stats_list:
            result["gc"] = {
                f"gen_{i}": {
                    "collections": stat[0],
                    "collected": stat[1],
                    "uncollectable": stat[2],
                }
                for i, stat in enumerate(gc_stats_list)
            }
        else:
            result["gc"] = {"info": "no stats available"}
    except Exception as e:
        result["gc"] = {"error": str(e)}

    return result


@router.get("/circuit-breakers")
async def get_circuit_breakers():
    """Get circuit breaker status."""
    from core.fallback.circuit_breaker import get_llm_circuit, get_retriever_circuit

    return {
        "llm": get_llm_circuit().stats,
        "retriever": get_retriever_circuit().stats,
    }


@router.post("/circuit-breakers/{name}/reset")
async def reset_circuit_breaker(name: str):
    """Reset a circuit breaker."""
    from core.fallback.circuit_breaker import get_llm_circuit, get_retriever_circuit

    if name == "llm":
        get_llm_circuit().reset()
        return {"status": "success", "message": "LLM circuit breaker reset"}
    elif name == "retriever":
        get_retriever_circuit().reset()
        return {"status": "success", "message": "Retriever circuit breaker reset"}
    else:
        return {"status": "error", "message": f"Unknown circuit breaker: {name}"}


@router.get("/degradation")
async def get_degradation_status():
    """Get degradation handler status."""
    from core.fallback.degradation import get_degradation_handler

    handler = get_degradation_handler()
    return handler.get_stats()


@router.post("/degradation/mode/{mode}")
async def set_degradation_mode(mode: str):
    """Set degradation mode."""
    from core.fallback.degradation import get_degradation_handler, FallbackMode

    handler = get_degradation_handler()

    try:
        new_mode = FallbackMode(mode)
        handler.mode = new_mode
        return {"status": "success", "mode": new_mode.value}
    except ValueError:
        valid_modes = [m.value for m in FallbackMode]
        return {
            "status": "error",
            "message": f"Invalid mode. Valid modes: {valid_modes}"
        }


@router.get("/config")
async def get_config():
    """Get current configuration."""
    from utils.env_utils import (
        COLLECTION_NAME,
        EMBEDDING_BATCH_SIZE,
        EMBEDDING_DEVICE,
        EMBEDDING_DIMENSION,
        EMBEDDING_MODEL,
        EMBEDDING_MODEL_PATH,
        EMBEDDING_NORMALIZE,
        LLM_MAX_RETRIES,
        LLM_MAX_TOKENS,
        LLM_MODEL,
        LLM_TEMPERATURE,
        LLM_TIMEOUT,
        MILVUS_URI,
        OTEL_CONSOLE_EXPORTER,
        OTEL_ENABLED,
        OTEL_EXPORTER_OTLP_ENDPOINT,
        OTEL_SAMPLE_RATE,
        OTEL_SERVICE_NAME,
        RERANKER_BATCH_SIZE,
        RERANKER_CANDIDATE_TOP_K,
        RERANKER_DEVICE,
        RERANKER_ENABLED,
        RERANKER_MODEL,
        RERANKER_MODEL_PATH,
        RERANKER_TOP_K,
        RERANKER_WARMUP,
    )

    return {
        "llm": {
            "model": LLM_MODEL,
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
            "timeout": LLM_TIMEOUT,
            "max_retries": LLM_MAX_RETRIES,
        },
        "embedding": {
            "model": EMBEDDING_MODEL,
            "local_path": EMBEDDING_MODEL_PATH,
            "dimension": EMBEDDING_DIMENSION,
            "device": EMBEDDING_DEVICE,
            "normalize": EMBEDDING_NORMALIZE,
            "batch_size": EMBEDDING_BATCH_SIZE,
        },
        "reranker": {
            "enabled": RERANKER_ENABLED,
            "model": RERANKER_MODEL,
            "local_path": RERANKER_MODEL_PATH,
            "device": RERANKER_DEVICE,
            "warmup": RERANKER_WARMUP,
            "candidate_top_k": RERANKER_CANDIDATE_TOP_K,
            "top_k": RERANKER_TOP_K,
            "batch_size": RERANKER_BATCH_SIZE,
        },
        "opentelemetry": {
            "enabled": OTEL_ENABLED,
            "service_name": OTEL_SERVICE_NAME,
            "endpoint": OTEL_EXPORTER_OTLP_ENDPOINT,
            "sample_rate": OTEL_SAMPLE_RATE,
            "console_exporter": OTEL_CONSOLE_EXPORTER,
        },
        "milvus": {
            "uri": MILVUS_URI,
            "collection": COLLECTION_NAME,
        },
        "session": {
            "ttl": 3600,
            "max_messages": 50,
        },
    }
