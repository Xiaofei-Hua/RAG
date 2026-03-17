"""
Document Schemas for Enterprise RAG Platform

Pydantic models for document-related API requests and responses.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class DocumentInfo(BaseModel):
    """Document information model."""
    id: str
    filename: str
    status: str
    chunks: int = 0
    created_at: float
    size_bytes: int = 0


class DocumentListResponse(BaseModel):
    """Document list response."""
    documents: List[DocumentInfo]
    total: int


class UploadResponse(BaseModel):
    """Document upload response."""
    id: str
    filename: str
    status: str
    message: str


class ChunkInfo(BaseModel):
    """Document chunk information."""
    chunk_id: str
    content: str
    page: Optional[int] = None
    position: Optional[int] = None