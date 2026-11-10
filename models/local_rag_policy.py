"""Select the qualified local RAG execution policy."""

import os
from functools import lru_cache
from urllib.parse import urlparse


def bounded_local_rag(source=None) -> bool:
    policy = os.getenv("LOCAL_RAG_POLICY", "legacy").lower()
    if policy not in {"bounded", "auto"}:
        return False
    from core.prompts.domain_profile import get_active_profile
    from utils.env_utils import LLM_MODEL, OPENAI_BASE_URL

    model = getattr(source, "model_name", None) or os.getenv("LLM_MODEL", LLM_MODEL)
    endpoint = (
        getattr(source, "openai_api_base", None)
        or getattr(source, "base_url", None)
        or os.getenv("OPENAI_BASE_URL", OPENAI_BASE_URL)
    )
    try:
        url = urlparse(str(endpoint))
        return (
            model == "qwen3.5:9b"
            and get_active_profile().name == "general"
            and url.scheme == "http"
            and url.hostname in {"localhost", "127.0.0.1", "::1"}
            and url.port == 11434
            and url.path.rstrip("/") == "/v1"
            and (policy == "bounded" or _qualified_runtime(str(endpoint)))
        )
    except ValueError:
        return False


def control_kwargs(model) -> dict:
    """Bound routing and grading without changing the general-chat client."""
    if not bounded_local_rag(model):
        return {}
    return {"reasoning_effort": "none", "max_tokens": 256, "extra_body": {"max_tokens": 256}}


@lru_cache(maxsize=8)
def _qualified_runtime(endpoint: str) -> bool:
    """Read server identity without invoking a model; refresh on app restart."""
    import httpx

    from utils.log_utils import log

    url = urlparse(endpoint)._replace(path="/api/version", params="", query="", fragment="")
    try:
        with httpx.Client(timeout=1.0, trust_env=False) as client:
            response = client.get(url.geturl())
            response.raise_for_status()
            return response.json().get("version") == "0.24.0-format-backport"
    except Exception as exc:
        log.debug(f"Local RAG runtime unavailable: {type(exc).__name__}")
        return False
