"""
Model router + cross-provider fallback (P2.4 + P2.5).

Two capabilities layered on top of the existing ``get_llm`` singleton:

  - **Model routing** (P2.4): different skills use different model tiers.
    Cheaper/smaller models handle grading, intent classification, query
    rewriting; the full model handles generation. Configured via env:
    ``LLM_MODEL_GRADE``, ``LLM_MODEL_INTENT`` (default: same as ``LLM_MODEL``).

  - **Cross-provider fallback** (P2.5): a ``FallbackLLM`` wraps a primary LLM
    and one or more secondary LLMs (different base_url/model). If the primary
    raises (timeout, connection error, circuit open), the call transparently
    retries on the next provider. Secondary providers are configured via env:
    ``LLM_FALLBACK_BASE_URL`` / ``LLM_FALLBACK_MODEL`` / ``LLM_FALLBACK_API_KEY``.

Both degrade gracefully: if routing/fallback env vars are unset, behaviour is
identical to the existing single-model path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from utils.log_utils import log

__all__ = [
    "ModelTier",
    "get_model_for_tier",
    "FallbackLLM",
    "get_fallback_llm",
]


# ---------------------------------------------------------------------------
# P2.4 Model routing by tier
# ---------------------------------------------------------------------------


class ModelTier:
    """Logical model tiers mapped to (possibly different) model names."""

    GENERATE = "generate"  # full model for final answers
    GRADE = "grade"  # cheap model for relevance grading
    INTENT = "intent"  # cheap model for intent classification
    REWRITE = "rewrite"  # cheap model for query rewriting


def _env(name: str, default: str) -> str:
    return os.getenv(name, default) or default


def get_model_for_tier(tier: str, base_model: str | None = None) -> str:
    """
    Return the model name to use for a given tier.

    Defaults to the base model; override per tier via env (e.g.
    ``LLM_MODEL_GRADE=qwen3:4b``).
    """
    base = base_model or _env("LLM_MODEL", "qwen3:14b")
    if tier == ModelTier.GRADE:
        return _env("LLM_MODEL_GRADE", base)
    if tier == ModelTier.INTENT:
        return _env("LLM_MODEL_INTENT", base)
    if tier == ModelTier.REWRITE:
        return _env("LLM_MODEL_REWRITE", base)
    return base


# Cache of per-tier LLM instances (so repeated calls reuse the same ChatOpenAI).
_tier_llms: dict = {}


def get_llm_for_tier(tier: str) -> BaseChatModel:
    """
    Get a (cached) ChatOpenAI for the given tier, wrapped in fallback if
    secondary providers are configured.
    """
    if tier in _tier_llms:
        return _tier_llms[tier]

    model = get_model_for_tier(tier)
    try:
        from langchain_openai import ChatOpenAI

        from models.llm_models import LLMConfig

        cfg = LLMConfig(model_name=model)
        llm = ChatOpenAI(
            model=cfg.model_name,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            timeout=cfg.timeout,
            max_retries=cfg.max_retries,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
        )
        wrapped = get_fallback_llm(llm)
        _tier_llms[tier] = wrapped
        return wrapped
    except Exception as e:  # noqa: BLE001
        log.warning(f"get_llm_for_tier({tier}) failed: {e}")
        from models.llm_models import get_llm

        return get_llm()


def reset_tier_llms() -> None:
    """Clear the per-tier LLM cache (tests / reconfiguration)."""
    _tier_llms.clear()


# ---------------------------------------------------------------------------
# P2.5 Cross-provider fallback
# ---------------------------------------------------------------------------


@dataclass
class FallbackProvider:
    base_url: str
    model: str
    api_key: str = ""


def _parse_secondary_providers() -> list[FallbackProvider]:
    """Parse fallback providers from env. Supports a single or comma-list."""
    urls = os.getenv("LLM_FALLBACK_BASE_URL", "")
    models = os.getenv("LLM_FALLBACK_MODEL", "")
    keys = os.getenv("LLM_FALLBACK_API_KEY", "")
    if not urls:
        return []
    url_list = [u.strip() for u in urls.split(",") if u.strip()]
    model_list = [m.strip() for m in models.split(",")] if models else []
    key_list = [k.strip() for k in keys.split(",")] if keys else []
    providers = []
    for i, url in enumerate(url_list):
        providers.append(
            FallbackProvider(
                base_url=url,
                model=model_list[i] if i < len(model_list) else "qwen3:14b",
                api_key=key_list[i] if i < len(key_list) else "ollama",
            )
        )
    return providers


class FallbackLLM:
    """
    Wraps a primary LLM with optional secondary providers.

    On any exception during invoke/ainvoke, transparently retries on the next
    provider. If all providers fail, raises the last error. When no secondary
    providers are configured, behaves exactly like the primary (zero overhead).
    """

    def __init__(self, primary: BaseChatModel, secondaries: list[BaseChatModel] | None = None):
        self._primary = primary
        self._secondaries = secondaries or []
        self._all = [primary] + (secondaries or [])

    def _try_all(self, method_name: str, *args, **kwargs):
        last_exc = None
        for i, llm in enumerate(self._all):
            try:
                return getattr(llm, method_name)(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                last_exc = e
                label = "primary" if i == 0 else f"fallback[{i}]"
                log.warning(f"LLM {label} {method_name} failed: {e}")
        raise last_exc

    async def _atry_all(self, method_name: str, *args, **kwargs):
        last_exc = None
        for i, llm in enumerate(self._all):
            try:
                return await getattr(llm, method_name)(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                last_exc = e
                label = "primary" if i == 0 else f"fallback[{i}]"
                log.warning(f"LLM {label} {method_name} failed: {e}")
        raise last_exc

    # --- passthrough interface (BaseChatModel-compatible) ---

    def invoke(self, messages, **kwargs):
        return self._try_all("invoke", messages, **kwargs)

    async def ainvoke(self, messages, **kwargs):
        return await self._atry_all("ainvoke", messages, **kwargs)

    def bind_tools(self, tools, **kwargs):
        # Bind tools on the primary; fallback providers are tool-less rescue.
        return self._primary.bind_tools(tools, **kwargs)

    def with_structured_output(self, schema, **kwargs):
        return self._primary.with_structured_output(schema, **kwargs)

    @property
    def model_name(self) -> str:
        return getattr(self._primary, "model_name", getattr(self._primary, "model", "unknown"))


def get_fallback_llm(primary: BaseChatModel) -> BaseChatModel:
    """
    Wrap ``primary`` with fallback providers if configured, else return as-is.
    """
    providers = _parse_secondary_providers()
    if not providers:
        return primary
    try:
        from langchain_openai import ChatOpenAI

        secondaries = [
            ChatOpenAI(model=p.model, base_url=p.base_url, api_key=p.api_key or "ollama")
            for p in providers
        ]
        log.info(f"FallbackLLM: {len(secondaries)} secondary provider(s) configured")
        return FallbackLLM(primary, secondaries)
    except Exception as e:  # noqa: BLE001
        log.warning(f"FallbackLLM setup failed, using primary only: {e}")
        return primary
