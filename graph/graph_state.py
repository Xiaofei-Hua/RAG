"""
Graph State Definitions for RAG Pipeline

Defines state models and data structures used across the LangGraph workflow.
Optimized for low-resource servers with efficient state management.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from pydantic import BaseModel, Field, ConfigDict


class NodeType(str, Enum):
    """Node identifiers for the RAG graph."""
    AGENT = "agent"
    RETRIEVE = "retrieve"
    REWRITE = "rewrite"
    GENERATE = "generate"
    GRADE = "grade"


class RouteDecision(str, Enum):
    """Routing decisions in the graph."""
    GENERATE = "generate"
    REWRITE = "rewrite"
    TOOLS = "tools"
    END = "END"


# =============================================================================
# State Definitions
# =============================================================================

class AgentState(TypedDict):
    """
    Main state for the RAG agent graph.

    The `messages` field uses `add_messages` reducer, which means
    new messages are appended to the existing list rather than replacing it.

    This enables conversational memory within the graph execution.

    Fields:
        messages: List of conversation messages
        rewrite_count: Number of query rewrites attempted (to prevent infinite loops)
        max_rewrites: Maximum allowed rewrites before forcing generation
    """
    messages: Annotated[list[BaseMessage], add_messages]
    rewrite_count: int  # Track number of rewrites to prevent infinite loops
    max_rewrites: int   # Maximum allowed rewrites


class GraphMetadata(TypedDict, total=False):
    """
    Optional metadata for graph execution.

    Used for tracking and debugging purposes.
    """
    session_id: str
    user_id: Optional[str]
    start_time: float
    node_visits: Dict[str, int]


# =============================================================================
# Pydantic Models for Structured Output
# =============================================================================

class Grade(BaseModel):
    """
    Binary relevance scoring for document-question pairs.

    Used by the grader node to determine if retrieved documents
    are relevant to the user's question.
    """
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    binary_score: str = Field(
        description="相关性评分: 'yes' 表示文档与问题相关，'no' 表示不相关"
    )

    @property
    def is_relevant(self) -> bool:
        """Check if the document is relevant."""
        return self.binary_score.lower() == "yes"


class RewrittenQuery(BaseModel):
    """
    Structured output for query rewriting.

    Contains the improved/rewritten query for better retrieval.
    """
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    original_query: str = Field(
        description="原始用户查询"
    )
    rewritten_query: str = Field(
        description="改进后的查询，更好地表达用户意图"
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="重写推理过程（可选）"
    )


class GeneratedAnswer(BaseModel):
    """
    Structured output for answer generation.

    Contains the final answer along with metadata.
    """
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    answer: str = Field(
        description="生成的回答内容"
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="回答的置信度 (0-1)"
    )
    sources: Optional[List[str]] = Field(
        default=None,
        description="引用的来源列表"
    )


# =============================================================================
# Helper Classes
# =============================================================================

class StateManager:
    """
    Helper class for state manipulation.

    Provides utility methods for working with AgentState.
    """

    @staticmethod
    def get_message_count(state: AgentState) -> int:
        """Get the number of messages in state."""
        return len(state.get("messages", []))

    @staticmethod
    def get_last_message(state: AgentState) -> Optional[BaseMessage]:
        """Get the last message from state."""
        messages = state.get("messages", [])
        return messages[-1] if messages else None

    @staticmethod
    def create_initial_state(message: str, max_rewrites: int = 3) -> AgentState:
        """Create initial state from a user message."""
        return {
            "messages": [("user", message)],
            "rewrite_count": 0,
            "max_rewrites": max_rewrites,
        }

    @staticmethod
    def increment_rewrite_count(state: AgentState) -> AgentState:
        """Increment the rewrite count (returns new state dict)."""
        current = state.get("rewrite_count", 0)
        return {
            "rewrite_count": current + 1,
            "max_rewrites": state.get("max_rewrites", 3),
        }

    @staticmethod
    def is_rewrite_limit_reached(state: AgentState) -> bool:
        """Check if rewrite limit has been reached."""
        count = state.get("rewrite_count", 0)
        max_count = state.get("max_rewrites", 3)
        return count >= max_count

    @staticmethod
    def append_message(state: AgentState, message: BaseMessage) -> AgentState:
        """Append a message to state (returns new state dict)."""
        return {"messages": [message]}


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "NodeType",
    "RouteDecision",
    "AgentState",
    "GraphMetadata",
    "Grade",
    "RewrittenQuery",
    "GeneratedAnswer",
    "StateManager",
]