"""
Rewrite Node for RAG Pipeline

This module implements the query rewriting node that improves the user's
question for better retrieval results.

Optimized for low-resource servers with:
- Prompt caching for efficiency
- Error handling and retry logic
- Configurable rewriting strategies
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from graph.graph_state import AgentState
from graph.get_human_message import get_last_human_message
from utils.log_utils import log

__all__ = [
    "RewriteNodeConfig",
    "RewriteNode",
    "rewrite",
]


# =============================================================================
# Default Prompts
# =============================================================================

DEFAULT_REWRITE_PROMPT = """你是一个查询优化专家，专门帮助改进用户的问题以便更好地检索相关信息。

请分析用户的原始问题，理解其深层意图，然后提出一个更清晰、更具体的改进问题。

改进问题的原则：
1. 保留原始问题的核心意图
2. 使用更精确的术语和表述
3. 补充必要的上下文信息
4. 如果问题涉及半导体/芯片领域，可以使用相关技术术语

原始问题：
{original_question}

请直接输出改进后的问题，不需要解释。"""


@dataclass
class RewriteNodeConfig:
    """
    Configuration for the rewrite node.

    Optimized for low-resource servers with conservative defaults.
    """
    max_retries: int = 2
    retry_delay: float = 1.0
    timeout: float = 30.0

    # Prompt customization
    rewrite_prompt: str = DEFAULT_REWRITE_PROMPT

    # Behavior options
    preserve_original_on_failure: bool = True


class RewriteNode:
    """
    Rewrite node that improves the user's question.

    This node:
    1. Extracts the user's question from the state
    2. Uses the LLM to rewrite/improve the question
    3. Returns the improved question as a new message

    The improved question is then fed back to the agent for
    another retrieval attempt.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        config: Optional[RewriteNodeConfig] = None,
    ):
        """
        Initialize the rewrite node.

        Args:
            llm: The language model to use
            config: Node configuration
        """
        self.llm = llm
        self.config = config or RewriteNodeConfig()
        self._chain = None

        log.debug("RewriteNode initialized")

    @property
    def chain(self):
        """Get the rewrite chain (lazy initialization with caching)."""
        if self._chain is None:
            prompt = ChatPromptTemplate.from_template(self.config.rewrite_prompt)
            self._chain = prompt | self.llm | StrOutputParser()
        return self._chain

    def __call__(self, state: AgentState) -> Dict[str, List[BaseMessage]]:
        """Execute the rewrite node."""
        return self.invoke(state)

    def invoke(self, state: AgentState) -> Dict[str, List[BaseMessage]]:
        """
        Invoke the rewrite node.

        Args:
            state: Current graph state containing messages

        Returns:
            Dictionary with rewritten question message
        """
        messages = state["messages"]

        log.info("---进入Rewrite节点, 重写查询---")

        # Extract the original question
        try:
            original_question = get_last_human_message(messages).content
        except Exception as e:
            log.warning(f"Failed to extract question: {e}")
            original_question = messages[-1].content if messages else ""

        # Rewrite with retry
        for attempt in range(self.config.max_retries + 1):
            try:
                rewritten = self.chain.invoke({
                    "original_question": original_question
                })

                log.info(f"查询重写完成: '{original_question[:50]}...' -> '{rewritten[:50]}...'")

                return {"messages": [HumanMessage(content=rewritten)]}

            except Exception as e:
                log.warning(f"Rewrite attempt {attempt + 1} failed: {e}")

                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    log.error(f"Rewrite failed after {self.config.max_retries + 1} attempts")

                    if self.config.preserve_original_on_failure:
                        log.info("Preserving original question")
                        return {"messages": [HumanMessage(content=original_question)]}

                    return {"messages": [AIMessage(content="查询重写失败，请重新提问。")]}

        return {"messages": [HumanMessage(content=original_question)]}


# =============================================================================
# Module-level node function for backward compatibility
# =============================================================================

# Global instances (lazy loaded)
_rewrite_node_instance: Optional[RewriteNode] = None


def _get_rewrite_node() -> RewriteNode:
    """Get or create the rewrite node instance (lazy initialization)."""
    global _rewrite_node_instance

    if _rewrite_node_instance is None:
        from models.llm_models import get_llm

        _rewrite_node_instance = RewriteNode(llm=get_llm())
        log.debug("Created new RewriteNode instance")

    return _rewrite_node_instance


def rewrite(state: AgentState) -> Dict[str, List[BaseMessage]]:
    """
    Rewrite node function for LangGraph.

    This is the main entry point for the rewrite node in the graph.
    Uses lazy initialization for optimal resource usage.

    Args:
        state: Current graph state containing messages

    Returns:
        dict: Updated state with rewritten question appended to messages

    Example:
        >>> from graph.graph_state import AgentState
        >>> state: AgentState = {
        ...     "messages": [
        ...         HumanMessage(content="那个东西怎么弄？"),
        ...         ToolMessage(content="..."),
        ...         AIMessage(content="无法找到相关信息")
        ...     ]
        ... }
        >>> result = rewrite(state)
        >>> # result["messages"] contains the rewritten question
    """
    node = _get_rewrite_node()
    return node.invoke(state)


def reset_rewrite_node():
    """Reset the rewrite node instance."""
    global _rewrite_node_instance
    _rewrite_node_instance = None
    log.debug("RewriteNode instance reset")