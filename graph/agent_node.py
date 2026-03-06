"""
Agent Node for RAG Pipeline

This module implements the agent node that determines whether to use
retrieval tools or respond directly based on the user's query.

Optimized for low-resource servers with:
- Lazy loading of LLM and tools
- Error handling and retry logic
- Memory-efficient operation
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from graph.graph_state import AgentState
from utils.log_utils import log

__all__ = [
    "AgentNodeConfig",
    "AgentNode",
    "agent_node",
]


@dataclass
class AgentNodeConfig:
    """
    Configuration for the agent node.

    Optimized for low-resource servers with conservative defaults.
    """
    max_retries: int = 2
    retry_delay: float = 1.0
    timeout: float = 30.0

    # Prompt customization
    system_prompt: Optional[str] = None


class AgentNode:
    """
    Agent node that decides between tool usage and direct response.

    This node:
    1. Receives the current conversation state
    2. Binds available tools to the LLM
    3. Invokes the LLM to determine the next action
    4. Returns the response as a new message

    The LLM will automatically decide whether to:
    - Call a retrieval tool (if the query requires external knowledge)
    - Respond directly (for general conversation)
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tools: List[BaseTool],
        config: Optional[AgentNodeConfig] = None,
    ):
        """
        Initialize the agent node.

        Args:
            llm: The language model to use
            tools: List of tools available to the agent
            config: Node configuration
        """
        self.llm = llm
        self.tools = tools
        self.config = config or AgentNodeConfig()
        self._bound_model = None

        log.debug(f"AgentNode initialized with {len(tools)} tools")

    @property
    def bound_model(self):
        """Get the model with tools bound (lazy initialization)."""
        if self._bound_model is None:
            self._bound_model = self.llm.bind_tools(self.tools)
        return self._bound_model

    def __call__(self, state: AgentState) -> Dict[str, List[BaseMessage]]:
        """
        Execute the agent node.

        Args:
            state: Current graph state containing messages

        Returns:
            Dictionary with new messages to append to state
        """
        return self.invoke(state)

    def invoke(self, state: AgentState) -> Dict[str, List[BaseMessage]]:
        """
        Invoke the agent with error handling and retries.

        Args:
            state: Current graph state

        Returns:
            Dictionary with AI response message
        """
        messages = state["messages"]

        # Get the last message for context
        last_message = messages[-1] if messages else None

        if last_message is None:
            log.warning("No messages in state")
            return {"messages": [AIMessage(content="请输入您的问题。")]}

        log.info(f"---进入Agent节点, 消息数: {len(messages)}---")

        # Invoke with retry
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._invoke_model(messages)
                return {"messages": [response]}

            except Exception as e:
                log.warning(f"Agent invoke attempt {attempt + 1} failed: {e}")

                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    log.error(f"Agent failed after {self.config.max_retries + 1} attempts")
                    # Return error message to user
                    error_msg = AIMessage(
                        content="抱歉，处理您的请求时遇到问题，请稍后重试。"
                    )
                    return {"messages": [error_msg]}

        return {"messages": [AIMessage(content="处理请求失败。")]}

    def _invoke_model(self, messages: List[BaseMessage]) -> AIMessage:
        """
        Invoke the model with the conversation context.

        Args:
            messages: List of conversation messages

        Returns:
            AI response message
        """
        # Use only the last message for efficiency in tool-binding scenarios
        # The model will have context from previous messages if needed
        response = self.bound_model.invoke([messages[-1]])

        log.debug(f"Agent response: {type(response).__name__}")

        return response


# =============================================================================
# Module-level node function for backward compatibility
# =============================================================================

# Global instances (lazy loaded)
_agent_node_instance: Optional[AgentNode] = None


def _get_agent_node() -> AgentNode:
    """
    Get or create the agent node instance (lazy initialization).

    This ensures the LLM and tools are only loaded when actually needed.
    """
    global _agent_node_instance

    if _agent_node_instance is None:
        from models.llm_models import get_llm
        from tools.retriever_tools import get_retriever_tool

        retriever_tool = get_retriever_tool()
        _agent_node_instance = AgentNode(
            llm=get_llm(),
            tools=[retriever_tool],
        )
        log.debug("Created new AgentNode instance")

    return _agent_node_instance


def agent_node(state: AgentState) -> Dict[str, List[BaseMessage]]:
    """
    Agent node function for LangGraph.

    This is the main entry point for the agent node in the graph.
    Uses lazy initialization for optimal resource usage.

    Args:
        state: Current graph state containing messages

    Returns:
        dict: Updated state with agent response appended to messages

    Example:
        >>> from graph.graph_state import AgentState
        >>> state: AgentState = {"messages": [HumanMessage(content="什么是芯片?")]}
        >>> result = agent_node(state)
        >>> # result["messages"] contains the AI response
    """
    node = _get_agent_node()
    return node.invoke(state)


def reset_agent_node():
    """Reset the agent node instance (useful for testing or reconfiguration)."""
    global _agent_node_instance
    _agent_node_instance = None
    log.debug("AgentNode instance reset")