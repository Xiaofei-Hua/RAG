"""
LLM Models Configuration

Provides language model instances and tools with lazy initialization
and configurable parameters.

Optimized for low-resource servers with:
- Lazy initialization of model instances
- Configurable model parameters
- Connection pooling and reuse
- Comprehensive error handling

Usage:
    >>> from models.llm_models import get_llm, llm
    >>> response = llm.invoke("Hello")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from utils.env_utils import OPENAI_API_KEY, OPENAI_BASE_URL, TAVILY_API_KEY
from utils.log_utils import log

__all__ = [
    "LLMConfig",
    "get_llm",
    "get_web_search_tool",
    "llm",
    "web_search_tool",
]


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class LLMConfig:
    """
    Configuration for language models.

    Optimized for low-resource servers with conservative defaults.
    """
    # Model settings
    model_name: str = "gpt-4o"
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    timeout: float = 60.0
    max_retries: int = 2

    # API settings
    api_key: Optional[str] = None
    base_url: Optional[str] = None

    def __post_init__(self):
        # Use environment variables as defaults
        if self.api_key is None:
            self.api_key = OPENAI_API_KEY
        if self.base_url is None:
            self.base_url = OPENAI_BASE_URL


@dataclass
class WebSearchConfig:
    """Configuration for web search tool."""
    max_results: int = 2
    api_key: Optional[str] = None

    def __post_init__(self):
        if self.api_key is None:
            self.api_key = TAVILY_API_KEY


# =============================================================================
# Model Factories
# =============================================================================

# Global instances (lazy loaded)
_llm_instance: Optional[BaseChatModel] = None
_web_search_instance = None


def get_llm(config: Optional[LLMConfig] = None) -> BaseChatModel:
    """
    Get or create the LLM instance.

    Uses singleton pattern for efficiency - same instance is reused.

    Args:
        config: Optional configuration (uses defaults if not provided)

    Returns:
        ChatOpenAI instance

    Example:
        >>> llm = get_llm()
        >>> response = llm.invoke("Hello")
    """
    global _llm_instance

    if _llm_instance is None or config is not None:
        cfg = config or LLMConfig()

        log.info(f"Creating LLM instance: model={cfg.model_name}")

        _llm_instance = ChatOpenAI(
            model=cfg.model_name,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            timeout=cfg.timeout,
            max_retries=cfg.max_retries,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
        )

        log.debug("LLM instance created successfully")

    return _llm_instance


def get_web_search_tool(config: Optional[WebSearchConfig] = None):
    """
    Get or create the web search tool instance.

    Args:
        config: Optional configuration (uses defaults if not provided)

    Returns:
        TavilySearch instance
    """
    global _web_search_instance

    if _web_search_instance is None or config is not None:
        try:
            from langchain_tavily import TavilySearch

            cfg = config or WebSearchConfig()

            log.info(f"Creating web search tool: max_results={cfg.max_results}")

            _web_search_instance = TavilySearch(
                max_results=cfg.max_results,
                tavily_api_key=cfg.api_key,
            )

            log.debug("Web search tool created successfully")

        except ImportError:
            log.warning("langchain_tavily not installed, web search unavailable")
            return None

    return _web_search_instance


def reset_llm():
    """Reset the LLM instance (useful for testing or reconfiguration)."""
    global _llm_instance
    _llm_instance = None
    log.debug("LLM instance reset")


def reset_web_search():
    """Reset the web search instance."""
    global _web_search_instance
    _web_search_instance = None
    log.debug("Web search instance reset")


# =============================================================================
# Module-level exports (lazy evaluation)
# =============================================================================

class _LLMProxy:
    """
    Proxy class for lazy LLM access.

    This allows `from models.llm_models import llm` to work
    without immediately creating the LLM instance.
    """

    _instance: Optional[BaseChatModel] = None

    def _get_instance(self) -> BaseChatModel:
        """Get the underlying LLM instance."""
        if self._instance is None:
            self._instance = get_llm()
        return self._instance

    def __getattr__(self, name):
        return getattr(self._get_instance(), name)

    def __call__(self, *args, **kwargs):
        return self._get_instance()(*args, **kwargs)

    def __or__(self, other):
        """Support LangChain pipe operator for chain composition."""
        return self._get_instance() | other

    def __ror__(self, other):
        """Support LangChain pipe operator for chain composition (right side)."""
        return other | self._get_instance()


class _WebSearchProxy:
    """
    Proxy class for lazy web search tool access.
    """

    _instance = None

    def __getattr__(self, name):
        if self._instance is None:
            self._instance = get_web_search_tool()
        if self._instance is None:
            raise RuntimeError("Web search tool not available")
        return getattr(self._instance, name)

    def __call__(self, *args, **kwargs):
        if self._instance is None:
            self._instance = get_web_search_tool()
        if self._instance is None:
            raise RuntimeError("Web search tool not available")
        return self._instance(*args, **kwargs)


# Export proxy instances for backward compatibility
llm = _LLMProxy()
web_search_tool = _WebSearchProxy()


# =============================================================================
# Convenience functions
# =============================================================================

def create_custom_llm(
    model_name: str = "gpt-4o",
    temperature: float = 0.0,
    **kwargs
) -> BaseChatModel:
    """
    Create a custom LLM instance with specified parameters.

    This always creates a new instance, unlike get_llm which reuses.

    Args:
        model_name: Model to use
        temperature: Sampling temperature
        **kwargs: Additional ChatOpenAI parameters

    Returns:
        New ChatOpenAI instance
    """
    config = LLMConfig(
        model_name=model_name,
        temperature=temperature,
        **kwargs
    )

    return ChatOpenAI(
        model=config.model_name,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout=config.timeout,
        max_retries=config.max_retries,
        api_key=config.api_key,
        base_url=config.base_url,
    )


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    print("Testing LLM connection...")

    try:
        # Test basic invocation
        response = llm.invoke("Say 'Hello' in one word.")
        print(f"Response: {response.content}")
        print("\nLLM connection successful!")

    except Exception as e:
        print(f"LLM connection failed: {e}")