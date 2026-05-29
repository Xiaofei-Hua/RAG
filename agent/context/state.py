"""
Agent State Definitions and Message Utilities

Consolidates graph state types and message helpers previously in
graph/graph_state.py and graph/get_human_message.py.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Dict, List, Optional, Type, TypeVar, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import add_messages
from pydantic import BaseModel, Field, ConfigDict

from agent.skills.base import SkillContext, SkillResult, SkillStatus
from utils.log_utils import log

__all__ = [
    # From skills.base (re-exported)
    "SkillContext",
    "SkillResult",
    "SkillStatus",
    # Graph state
    "AgentState",
    "NodeType",
    "RouteDecision",
    "GraphMetadata",
    "StateManager",
    # Pydantic models
    "Grade",
    "RewrittenQuery",
    "GeneratedAnswer",
    # Message utilities
    "get_last_human_message",
    "get_last_ai_message",
    "MessageExtractor",
]


# =============================================================================
# Graph State
# =============================================================================

class NodeType(str, Enum):
    AGENT = "agent"
    RETRIEVE = "retrieve"
    REWRITE = "rewrite"
    GENERATE = "generate"
    GRADE = "grade"


class RouteDecision(str, Enum):
    GENERATE = "generate"
    REWRITE = "rewrite"
    TOOLS = "tools"
    END = "END"


class AgentState(TypedDict):
    """
    Main state for the RAG agent graph.

    Fields:
        messages: List of conversation messages (add_messages reducer)
        rewrite_count: Number of query rewrites attempted
        max_rewrites: Maximum allowed rewrites before forcing generation
    """
    messages: Annotated[list[BaseMessage], add_messages]
    rewrite_count: int
    max_rewrites: int


class GraphMetadata(TypedDict, total=False):
    session_id: str
    user_id: Optional[str]
    start_time: float
    node_visits: Dict[str, int]


# =============================================================================
# Pydantic Models for Structured Output
# =============================================================================

class Grade(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    binary_score: str = Field(
        default="yes",
        description="相关性评分: 'yes' 表示文档与问题相关，'no' 表示不相关"
    )
    answer: Optional[str] = Field(
        default=None,
        description="备选字段，部分模型（如Qwen3）可能使用此字段返回yes/no"
    )

    @property
    def is_relevant(self) -> bool:
        score = self.binary_score or self.answer or ""
        return score.lower() in ("yes", "true", "relevant")


class RewrittenQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    original_query: str = Field(description="原始用户查询")
    rewritten_query: str = Field(description="改进后的查询")
    reasoning: Optional[str] = Field(default=None, description="重写推理过程")


class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    answer: str = Field(description="生成的回答内容")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    sources: Optional[List[str]] = Field(default=None, description="引用来源")


# =============================================================================
# State Manager
# =============================================================================

class StateManager:
    @staticmethod
    def get_message_count(state: AgentState) -> int:
        return len(state.get("messages", []))

    @staticmethod
    def get_last_message(state: AgentState) -> Optional[BaseMessage]:
        messages = state.get("messages", [])
        return messages[-1] if messages else None

    @staticmethod
    def create_initial_state(message: str, max_rewrites: int = 3) -> AgentState:
        return {
            "messages": [("user", message)],
            "rewrite_count": 0,
            "max_rewrites": max_rewrites,
        }

    @staticmethod
    def increment_rewrite_count(state: AgentState) -> AgentState:
        current = state.get("rewrite_count", 0)
        return {
            "rewrite_count": current + 1,
            "max_rewrites": state.get("max_rewrites", 3),
        }

    @staticmethod
    def is_rewrite_limit_reached(state: AgentState) -> bool:
        count = state.get("rewrite_count", 0)
        max_count = state.get("max_rewrites", 3)
        return count >= max_count

    @staticmethod
    def append_message(state: AgentState, message: BaseMessage) -> AgentState:
        return {"messages": [message]}


# =============================================================================
# Message Utilities
# =============================================================================

class MessageNotFoundError(Exception):
    pass


def get_last_human_message(messages: List[BaseMessage]) -> HumanMessage:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message
    raise MessageNotFoundError("No HumanMessage found in the messages list")


def get_last_ai_message(messages: List[BaseMessage]) -> Optional[AIMessage]:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


T = TypeVar("T", bound=BaseMessage)


class MessageExtractor:
    def __init__(self, messages: List[BaseMessage]):
        self.messages = messages

    def get_last_human_message(self) -> HumanMessage:
        return get_last_human_message(self.messages)

    def get_last_ai_message(self) -> Optional[AIMessage]:
        return get_last_ai_message(self.messages)
