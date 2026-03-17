"""
Documents Router for Enterprise RAG Platform

Handles document upload, management, and indexing.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel, Field
from langchain_core.documents import Document

from utils.log_utils import log

router = APIRouter()


# =============================================================================
# Models
# =============================================================================

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


# =============================================================================
# In-memory document registry (for demo, use database in production)
# =============================================================================

_document_registry: dict = {}


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    Upload and process a document.

    Supported formats:
    - Markdown (.md)
    - Text (.txt)
    - PDF (.pdf) - requires additional dependencies
    """
    # Validate file type
    allowed_extensions = {".md", ".txt", ".pdf"}
    filename = file.filename or "unknown"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {allowed_extensions}"
        )

    # Generate document ID
    doc_id = str(uuid.uuid4())[:8]

    log.info(f"Uploading document: {filename} (id={doc_id})")

    try:
        # Read file content
        content = await file.read()
        size = len(content)

        # Save temporarily
        temp_path = f"/tmp/{doc_id}_{filename}"
        with open(temp_path, "wb") as f:
            f.write(content)

        # Register document
        _document_registry[doc_id] = DocumentInfo(
            id=doc_id,
            filename=filename,
            status="processing",
            chunks=0,
            created_at=time.time(),
            size_bytes=size,
        )

        # Process in background
        background_tasks.add_task(
            _process_document,
            doc_id,
            temp_path,
            filename,
        )

        return UploadResponse(
            id=doc_id,
            filename=filename,
            status="processing",
            message="Document uploaded and processing started",
        )

    except Exception as e:
        log.error(f"Failed to upload document: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _process_document(doc_id: str, file_path: str, filename: str):
    """Process and index a document (background task).

    Note: This is a synchronous function because BackgroundTasks.add_task
    runs functions in a threadpool. For async operations, use asyncio.run()
    inside or refactor to use async background workers.
    """
    try:
        log.info(f"Processing document: {doc_id}")

        # Parse document based on type
        ext = os.path.splitext(filename)[1].lower()

        if ext == ".md":
            from documents.markdown_parser import MarkdownParser
            parser = MarkdownParser()
            documents = parser.parse_markdown_to_documents(file_path)
        else:
            # Simple text chunking
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            documents = [Document(
                page_content=content,
                metadata={"source": filename}
            )]

        # Index into vector database
        from documents.milvus_db import get_milvus_manager
        manager = get_milvus_manager()

        result = manager.add_documents(documents)

        # Update registry
        if doc_id in _document_registry:
            _document_registry[doc_id].status = "indexed"
            _document_registry[doc_id].chunks = result.get("inserted", 0)

        log.info(f"Document processed: {doc_id}, chunks={len(documents)}")

    except Exception as e:
        log.error(f"Failed to process document {doc_id}: {e}")
        if doc_id in _document_registry:
            _document_registry[doc_id].status = "failed"
    finally:
        # Always cleanup temp file
        if os.path.exists(file_path):
            os.remove(file_path)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    skip: int = 0,
    limit: int = 20,
):
    """List all documents."""
    documents = list(_document_registry.values())[skip:skip + limit]
    return DocumentListResponse(
        documents=documents,
        total=len(_document_registry),
    )


@router.get("/{doc_id}", response_model=DocumentInfo)
async def get_document(doc_id: str):
    """Get document details."""
    if doc_id not in _document_registry:
        raise HTTPException(status_code=404, detail="Document not found")

    return _document_registry[doc_id]


@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a document."""
    if doc_id not in _document_registry:
        raise HTTPException(status_code=404, detail="Document not found")

    # TODO: Remove from vector database

    del _document_registry[doc_id]
    return {"status": "success", "message": f"Document {doc_id} deleted"}


@router.post("/reindex")
async def reindex_all_documents():
    """Reindex all documents."""
    # TODO: Implement full reindexing
    return {
        "status": "success",
        "message": "Reindexing started",
    }