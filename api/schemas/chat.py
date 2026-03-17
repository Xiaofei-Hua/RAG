"""
Chat Schemas for Enterprise RAG Platform

Pydantic models for chat-related API requests and responses.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Single chat message."""
    role: str = Field(..., description="Message role: user, assistant, or system")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    """Chat request model."""
    message: str = Field(..., description="User message", min_length=1)
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity")
    stream: bool = Field(False, description="Enable streaming response")
    include_sources: bool = Field(True, description="Include source documents in response")


class SourceDocument(BaseModel):
    """Source document in response."""
    content: str
    source: Optional[str] = None
    title: Optional[str] = None
    score: float = 0.0


class ChatResponse(BaseModel):
    """Chat response model."""
    response: str = Field(..., description="Assistant response")
    session_id: str = Field(..., description="Session ID")
    intent: str = Field(..., description="Detected intent")
    sources: List[SourceDocument] = Field(default_factory=list, description="Source documents")
    processing_time_ms: float = Field(..., description="Processing time in milliseconds")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class ChatHistoryResponse(BaseModel):
    """Chat history response."""
    session_id: str
    messages: List[ChatMessage]
    total_messages: int