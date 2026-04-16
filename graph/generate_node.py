"""
Generate Node for RAG Pipeline

This module implements the generation node that produces the final answer
based on retrieved documents and the user's question.

Optimized for low-resource servers with:
- Prompt caching for efficiency
- Error handling and retry logic
- Configurable generation parameters
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate

from graph.graph_state import AgentState
from graph.get_human_message import get_last_human_message
from utils.log_utils import log

__all__ = [
    "GenerateNodeConfig",
    "GenerateNode",
    "generate",
]


# =============================================================================
# Default Prompts
# =============================================================================

from core.prompts.aircraft_prompts import (
    GENERATE_SYSTEM_PROMPT as DEFAULT_SYSTEM_PROMPT,
    GENERATE_HUMAN_PROMPT as DEFAULT_HUMAN_PROMPT,
)


@dataclass
class GenerateNodeConfig:
    """
    Configuration for the generate node.

    Optimized for low-resource servers with conservative defaults.
    """
    max_retries: int = 2
    retry_delay: float = 1.0
    timeout: float = 60.0

    # Context handling
    max_context_length: int = 4000  # Characters

    # Prompt customization
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    human_prompt: str = DEFAULT_HUMAN_PROMPT


class GenerateNode:
    """
    Generation node that produces the final answer.

    This node:
    1. Extracts the user's question from the state
    2. Retrieves the context from the last message (retrieved documents)
    3. Uses the LLM to generate an answer
    4. Returns the answer as an AI message

    The prompt is cached to avoid recompilation on each invocation.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        config: Optional[GenerateNodeConfig] = None,
    ):
        """
        Initialize the generate node.

        Args:
            llm: The language model to use
            config: Node configuration
        """
        self.llm = llm
        self.config = config or GenerateNodeConfig()
        self._chain = None

        log.debug("GenerateNode initialized")

    @property
    def chain(self):
        """Get the generation chain (lazy initialization with caching)."""
        if self._chain is None:
            prompt = ChatPromptTemplate.from_messages([
                ("system", self.config.system_prompt),
                ("human", self.config.human_prompt),
            ])
            self._chain = prompt | self.llm | StrOutputParser()
        return self._chain

    def __call__(self, state: AgentState) -> Dict[str, List[BaseMessage]]:
        """Execute the generate node."""
        return self.invoke(state)

    def invoke(self, state: AgentState) -> Dict[str, List[BaseMessage]]:
        """
        Invoke the generation node.

        Args:
            state: Current graph state containing messages

        Returns:
            Dictionary with AI response message
        """
        messages = state["messages"]

        log.info("---进入Generate节点, 生成最终答案---")

        # Extract question and context
        question = self._extract_question(messages)
        context = self._extract_context(messages)

        # If no context available, return a helpful message
        if not context or not context.strip():
            log.info("No context available — knowledge base may be empty")
            empty_msg = AIMessage(
                content="当前知识库中暂无相关文档。请先通过文档管理页面上传排故手册、维修手册等资料，"
                "然后再进行提问。"
            )
            return {"messages": [empty_msg]}

        # Truncate context if needed
        if len(context) > self.config.max_context_length:
            context = context[:self.config.max_context_length] + "\n...[内容已截断]"
            log.debug(f"Context truncated to {self.config.max_context_length} chars")

        # Generate with retry
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.chain.invoke({
                    "question": question,
                    "context": context
                })

                ai_message = AIMessage(content=response)
                log.info(f"生成完成, 回答长度: {len(response)} 字符")

                return {"messages": [ai_message]}

            except Exception as e:
                log.warning(f"Generate attempt {attempt + 1} failed: {e}")

                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    log.error(f"Generate failed after {self.config.max_retries + 1} attempts")
                    error_msg = AIMessage(
                        content="抱歉，生成回答时遇到问题，请稍后重试。"
                    )
                    return {"messages": [error_msg]}

        return {"messages": [AIMessage(content="生成回答失败。")]}

    def _extract_question(self, messages: List[BaseMessage]) -> str:
        """Extract the user's question from messages."""
        try:
            human_message = get_last_human_message(messages)
            return human_message.content
        except Exception as e:
            log.warning(f"Failed to extract question: {e}")
            # Fallback to last message content
            return messages[-1].content if messages else ""

    def _extract_context(self, messages: List[BaseMessage]) -> str:
        """
        Extract context from messages.

        The context is typically in the last message (from the retriever).
        """
        last_message = messages[-1] if messages else None

        if last_message is None:
            return ""

        content = last_message.content

        # If content is a list (tool result format), extract text
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    text_parts.append(item["text"])
                elif isinstance(item, str):
                    text_parts.append(item)
            return "\n\n".join(text_parts)

        return str(content)


# =============================================================================
# Module-level node function for backward compatibility
# =============================================================================

# Global instances (lazy loaded)
_generate_node_instance: Optional[GenerateNode] = None


def _get_generate_node() -> GenerateNode:
    """Get or create the generate node instance (lazy initialization)."""
    global _generate_node_instance

    if _generate_node_instance is None:
        from models.llm_models import get_llm

        _generate_node_instance = GenerateNode(llm=get_llm())
        log.debug("Created new GenerateNode instance")

    return _generate_node_instance


def generate(state: AgentState) -> Dict[str, List[BaseMessage]]:
    """
    Generate node function for LangGraph.

    This is the main entry point for the generate node in the graph.
    Uses lazy initialization for optimal resource usage.

    Args:
        state: Current graph state containing messages

    Returns:
        dict: Updated state with generated answer appended to messages

    Example:
        >>> from graph.graph_state import AgentState
        >>> state: AgentState = {
        ...     "messages": [
        ...         HumanMessage(content="发动机振动异常如何排查?"),
        ...         ToolMessage(content="检索到的文档内容...")
        ...     ]
        ... }
        >>> result = generate(state)
        >>> # result["messages"] contains the AI answer
    """
    node = _get_generate_node()
    return node.invoke(state)


def reset_generate_node():
    """Reset the generate node instance."""
    global _generate_node_instance
    _generate_node_instance = None
    log.debug("GenerateNode instance reset")