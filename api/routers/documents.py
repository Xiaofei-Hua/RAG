"""
Documents Router for Enterprise RAG Platform

Handles document upload, management, and indexing.
Uses SQLite-backed registry for persistent document tracking.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel, Field
from langchain_core.documents import Document

from documents.document_registry import get_document_registry
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
    file_hash: str = ""


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
# Helpers
# =============================================================================

def _compute_file_hash(content: bytes) -> str:
    """Compute SHA256 hash of file content."""
    return hashlib.sha256(content).hexdigest()


def _check_duplicate(filename: str, file_hash: str) -> Optional[str]:
    """
    Check if a file already exists in the vector database or registry.

    Returns an error message if duplicate found, None otherwise.
    """
    # Check registry first (fast, always available)
    registry = get_document_registry()
    existing_by_name = registry.find_by_filename(filename)
    if existing_by_name:
        return f"文件 '{filename}' 已上传过，请勿重复上传"

    existing_by_hash = registry.find_by_file_hash(file_hash)
    if existing_by_hash:
        return f"相同内容的文件已存在（来源: {existing_by_hash.get('filename', '未知')}），请勿重复上传"

    # Also check Milvus (for data from previous sessions)
    try:
        from documents.milvus_db import get_milvus_manager
        manager = get_milvus_manager()

        results = manager.query(
            filter_expr=f'source == "{filename}"',
            output_fields=["source"],
            limit=1,
        )
        if results:
            return f"文件 '{filename}' 已上传过，请勿重复上传"

        results = manager.query(
            filter_expr=f'file_hash == "{file_hash}"',
            output_fields=["source"],
            limit=1,
        )
        if results:
            existing_name = results[0].get("source", "未知")
            return f"相同内容的文件已存在（来源: {existing_name}），请勿重复上传"

    except Exception as e:
        log.debug(f"Milvus duplicate check skipped: {e}")

    return None


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

    Supported formats: .md, .txt, .pdf
    """
    allowed_extensions = {".md", ".txt", ".pdf"}
    filename = file.filename or "unknown"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {allowed_extensions}"
        )

    doc_id = str(uuid.uuid4())[:8]
    log.info(f"Uploading document: {filename} (id={doc_id})")

    try:
        content = await file.read()
        size = len(content)
        file_hash = _compute_file_hash(content)

        # Check for duplicates
        duplicate_msg = _check_duplicate(filename, file_hash)
        if duplicate_msg:
            log.warning(f"Duplicate upload rejected: {filename} (hash={file_hash[:16]}...)")
            raise HTTPException(status_code=409, detail=duplicate_msg)

        # Save temporarily
        temp_path = f"/tmp/{doc_id}_{filename}"
        with open(temp_path, "wb") as f:
            f.write(content)

        # Register document (persistent)
        registry = get_document_registry()
        registry.put(
            doc_id=doc_id,
            filename=filename,
            status="processing",
            chunks=0,
            created_at=time.time(),
            size_bytes=size,
            file_hash=file_hash,
        )

        # Process in background
        background_tasks.add_task(
            _process_document,
            doc_id,
            temp_path,
            filename,
            file_hash,
        )

        return UploadResponse(
            id=doc_id,
            filename=filename,
            status="processing",
            message="Document uploaded and processing started",
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to upload document: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _process_document(doc_id: str, file_path: str, filename: str, file_hash: str):
    """Process and index a document (background task)."""
    registry = get_document_registry()
    try:
        log.info(f"Processing document: {doc_id}")

        ext = os.path.splitext(filename)[1].lower()

        if ext == ".md":
            from documents.markdown_parser import MarkdownParser
            parser = MarkdownParser()
            documents = parser.parse_markdown_to_documents(file_path)
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            documents = [Document(
                page_content=content,
                metadata={"source": filename}
            )]

        # Attach file_hash to every chunk's metadata
        for doc in documents:
            doc.metadata["file_hash"] = file_hash

        # Index into Milvus
        from documents.milvus_db import get_milvus_manager
        manager = get_milvus_manager()
        result = manager.add_documents(documents)

        # Sync BM25 index
        try:
            from core.retrieval.bm25_retriever import get_bm25_retriever
            bm25 = get_bm25_retriever()
            bm25.add_documents(documents)
            log.info(f"BM25 index updated: +{len(documents)} docs")
        except Exception as bm25_err:
            log.warning(f"BM25 sync failed (non-critical): {bm25_err}")

        # Update registry
        registry.update_status(doc_id, "indexed", result.get("inserted", 0))
        log.info(f"Document processed: {doc_id}, chunks={len(documents)}")

    except Exception as e:
        log.error(f"Failed to process document {doc_id}: {e}")
        registry.update_status(doc_id, "failed")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    skip: int = 0,
    limit: int = 20,
):
    """List all documents."""
    registry = get_document_registry()
    docs = registry.list_all(skip=skip, limit=limit)
    return DocumentListResponse(
        documents=[DocumentInfo(**d) for d in docs],
        total=registry.count(),
    )


@router.get("/{doc_id}", response_model=DocumentInfo)
async def get_document(doc_id: str):
    """Get document details."""
    registry = get_document_registry()
    doc = registry.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentInfo(**doc)


@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a document from registry, Milvus, and BM25."""
    registry = get_document_registry()
    doc = registry.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove from Milvus
    try:
        from documents.milvus_db import get_milvus_manager
        manager = get_milvus_manager()
        file_hash = doc.get("file_hash", "")
        if file_hash:
            manager.delete_by_filter(filter_expr=f'file_hash == "{file_hash}"')
            log.info(f"Deleted document from Milvus: {doc_id}")
        else:
            manager.delete_by_filter(filter_expr=f'source == "{doc["filename"]}"')
            log.info(f"Deleted document from Milvus by filename: {doc['filename']}")
    except Exception as e:
        log.error(f"Failed to delete from Milvus: {e}")

    # Clear BM25 index (will be rebuilt on next query from Milvus)
    try:
        from core.retrieval.bm25_retriever import get_bm25_retriever
        get_bm25_retriever().clear()
        log.info("BM25 index cleared, will rebuild on next query")
    except Exception as e:
        log.warning(f"BM25 cleanup failed: {e}")

    registry.delete(doc_id)
    return {"status": "success", "message": f"Document {doc_id} deleted"}


@router.post("/reindex")
async def reindex_all_documents():
    """Reindex all documents."""
    # TODO: Implement full reindexing
    return {
        "status": "success",
        "message": "Reindexing started",
    }
