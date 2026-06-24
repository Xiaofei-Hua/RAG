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

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from langchain_core.documents import Document
from pydantic import BaseModel

from documents.document_registry import DocumentStatus, get_document_registry
from utils.log_utils import log

router = APIRouter()

# Module-level upload temp directory (B6). Exposed so tests/conftest.py's
# tmp_data_dir fixture can redirect it to tmp_path, keeping uploads hermetic
# (previously hardcoded "/tmp" leaked temp files when the background cleanup
# was mocked out). Conforms to AGENTS.md §6/§10 persistence-path contract.
UPLOAD_TMP_DIR = "/tmp"


# =============================================================================
# Models
# =============================================================================


class DocumentInfo(BaseModel):
    """Document information model."""

    id: str
    filename: str
    status: DocumentStatus
    chunks: int = 0
    created_at: float
    size_bytes: int = 0
    file_hash: str = ""


class DocumentListResponse(BaseModel):
    """Document list response."""

    documents: list[DocumentInfo]
    total: int


class UploadResponse(BaseModel):
    """Document upload response."""

    id: str
    filename: str
    status: DocumentStatus
    message: str


# =============================================================================
# Helpers
# =============================================================================


def _compute_file_hash(content: bytes) -> str:
    """Compute SHA256 hash of file content."""
    return hashlib.sha256(content).hexdigest()


def _secure_filename(filename: str) -> str:
    """
    Sanitise a user-supplied filename for safe use in a filesystem path.

    Strips directory components and path separators so that a name like
    ``../../etc/x.md`` cannot escape the destination directory. Falls back to
    a generic name when nothing safe remains. The original (sanitised) name
    is still used for display/duplicate-detection.
    """
    import os
    import re

    if not filename:
        return "upload"
    # Take the basename only (handles both / and \ and any leading ../).
    name = os.path.basename(filename.replace("\\", "/"))
    # Drop any remaining path separators / dots-only / control chars.
    name = re.sub(r"[\/\x00-\x1f]", "_", name)
    # Collapse ".." sequences that survived.
    name = name.replace("..", "_")
    name = name.strip(". ") or "upload"
    return name


def _escape_filter_value(value: str) -> str:
    """Escape special characters in Milvus filter expression values."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _split_documents(documents: list[Document]) -> list[Document]:
    """Split documents using semantic chunking with fallback.

    Mirrors MarkdownParser's two-stage strategy:
    1. Small docs (< ~1200 tokens) are kept intact.
    2. Large docs are split by SemanticChunker (embedding-based breakpoints).
    3. On failure, fall back to RecursiveCharacterTextSplitter.
    """
    try:
        from langchain_experimental.text_splitter import SemanticChunker
    except ImportError:
        SemanticChunker = None  # type: ignore

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:
        try:
            from langchain.text_splitter import (
                RecursiveCharacterTextSplitter,  # type: ignore[no-redef]
            )
        except ImportError:
            RecursiveCharacterTextSplitter = None  # type: ignore

    # Stage 1: separate small docs (keep intact) from large docs (need splitting)
    small: list[Document] = []
    large: list[Document] = []
    for doc in documents:
        text = doc.page_content or ""
        if not text:
            continue
        # Threshold: ~1200 tokens. Mixed Chinese/English ≈ 3.2 chars/token.
        if len(text) > 3840:
            large.append(doc)
        else:
            small.append(doc)

    if not large:
        return small

    result: list[Document] = list(small)

    # Stage 2: semantic chunking for large docs
    semantic_splitter = None
    if SemanticChunker is not None:
        try:
            from models.embedding_models import get_local_embeddings

            embeddings = get_local_embeddings()
            semantic_splitter = SemanticChunker(
                embeddings,
                breakpoint_threshold_type="percentile",
            )
        except Exception as e:
            log.debug(f"SemanticChunker init failed: {e}")

    if semantic_splitter is not None:
        try:
            pieces = semantic_splitter.split_documents(large)
            result.extend(pieces)
            log.info(f"Semantic split: {len(large)} docs -> {len(pieces)} chunks")
            return result
        except Exception as e:
            log.warning(f"Semantic split failed: {e}, falling back to recursive splitter")

    # Stage 3: fallback to RecursiveCharacterTextSplitter
    if RecursiveCharacterTextSplitter is not None:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=900,
            chunk_overlap=120,
            separators=[
                "\n\n",
                "\n",
                "。",
                "！",
                "？",
                ".",
                "!",
                "?",
                "；",
                ";",
                "，",
                ",",
                " ",
                "",
            ],
        )
        pieces = splitter.split_documents(large)
        result.extend(pieces)
        log.info(f"Fallback split: {len(large)} docs -> {len(pieces)} chunks")
    else:
        result.extend(large)

    return result


def _recover_stale_processing(registry, filename: str, file_hash: str) -> None:
    """
    Flip orphaned ``processing`` rows to ``failed`` (B7).

    A background indexing task that dies (process killed, exception before the
    status update) leaves its registry row in ``processing`` forever, which
    then blocks any re-upload of the same content. We treat a ``processing``
    row older than the stale threshold as dead: marking it ``failed`` lets a
    fresh upload proceed. Never raises — recovery is best-effort.
    """
    import time

    # Stale threshold: a healthy index of a single doc completes well under a
    # minute; anything still processing past this is almost certainly orphaned.
    stale_seconds = 120.0
    now = time.time()
    for row in (registry.find_by_filename(filename), registry.find_by_file_hash(file_hash)):
        if not row:
            continue
        if row.get("status") != "processing":
            continue
        created = row.get("created_at")
        if isinstance(created, (int, float)) and (now - float(created)) > stale_seconds:
            try:
                registry.update_status(row["id"], "failed")
                log.warning(
                    f"Recovered stale 'processing' doc {row.get('id')} "
                    f"(age {now - float(created):.0f}s) -> failed"
                )
            except Exception as e:  # noqa: BLE001
                log.debug(f"stale-processing recovery skipped: {e}")


def _check_duplicate(filename: str, file_hash: str) -> str | None:
    """
    Check if a file already exists in the vector database or registry.

    Returns an error message if duplicate found, None otherwise. A registry
    record stuck in ``processing`` for longer than the stale threshold is
    treated as an orphaned background task (B7): it is flipped to ``failed``
    and does NOT block re-upload, so a dead worker never wedges the doc.
    """
    # Check registry first (fast, always available)
    registry = get_document_registry()

    # B7: recover orphaned "processing" rows before they block uploads.
    _recover_stale_processing(registry, filename, file_hash)

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

        safe_name = _escape_filter_value(filename)
        safe_hash = _escape_filter_value(file_hash)

        results = manager.query(
            filter_expr=f'source == "{safe_name}"',
            output_fields=["source"],
            limit=1,
        )
        if results:
            return f"文件 '{filename}' 已上传过，请勿重复上传"

        results = manager.query(
            filter_expr=f'file_hash == "{safe_hash}"',
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

    Supported formats: .md, .txt, .pdf, .docx, .pptx, .html, .htm
    (DOCX/PPTX/HTML require their optional libs: python-docx, python-pptx,
    beautifulsoup4.)
    """
    allowed_extensions = {".md", ".txt", ".pdf", ".docx", ".pptx", ".html", ".htm"}
    filename = file.filename or "unknown"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400, detail=f"Unsupported file type: {ext}. Allowed: {allowed_extensions}"
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

        # Save temporarily — sanitise the filename to prevent path traversal
        # (a user-supplied name like ../../etc/x must not escape /tmp). The
        # sanitised name is also used as the document source/registry name so
        # path fragments don't leak into chunk metadata or the listing.
        safe_name = _secure_filename(filename)
        temp_path = os.path.join(UPLOAD_TMP_DIR, f"{doc_id}_{safe_name}")
        with open(temp_path, "wb") as f:
            f.write(content)

        # Register document (persistent)
        registry = get_document_registry()
        registry.put(
            doc_id=doc_id,
            filename=safe_name,
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
            safe_name,
            file_hash,
        )

        return UploadResponse(
            id=doc_id,
            filename=safe_name,
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
        elif ext == ".pdf":
            from documents.pdf_parser import parse_pdf_to_documents

            documents = parse_pdf_to_documents(file_path, filename)
            documents = _split_documents(documents)
        elif ext in (".docx", ".pptx", ".html", ".htm"):
            # Multi-format parsers (optional libs). Falls back to text on error.
            try:
                from documents.format_parsers import parse_by_extension

                documents = parse_by_extension(file_path, source=filename)
                documents = _split_documents(documents)
            except RuntimeError as fmt_err:
                log.warning(f"Multi-format parse failed ({ext}), skipping: {fmt_err}")
                raise
        else:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
            # Split by paragraph first so the splitter can respect natural boundaries.
            documents = []
            for para in content.split("\n\n"):
                para = para.strip()
                if para:
                    documents.append(Document(page_content=para, metadata={"source": filename}))
            documents = _split_documents(documents)

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
            from core.retrieval.cache import bump_retrieval_cache_version

            bm25 = get_bm25_retriever()
            bm25.add_documents(documents)
            # Invalidate cached retrieval results so the new docs are visible to
            # the read path immediately (cache key is version-scoped).
            bump_retrieval_cache_version()
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
            safe_hash = _escape_filter_value(file_hash)
            manager.delete_by_filter(filter_expr=f'file_hash == "{safe_hash}"')
            log.info(f"Deleted document from Milvus: {doc_id}")
        else:
            safe_name = _escape_filter_value(doc["filename"])
            manager.delete_by_filter(filter_expr=f'source == "{safe_name}"')
            log.info(f"Deleted document from Milvus by filename: {doc['filename']}")
    except Exception as e:
        log.error(f"Failed to delete from Milvus: {e}")

    # Remove from BM25 index (incremental)
    try:
        from core.retrieval.bm25_retriever import get_bm25_retriever
        from core.retrieval.cache import bump_retrieval_cache_version

        get_bm25_retriever().remove_by_source(doc["filename"])
        # Invalidate cached retrieval results computed against the old index.
        bump_retrieval_cache_version()
        log.info(f"BM25 index updated: removed source={doc['filename']}")
    except Exception as e:
        log.warning(f"BM25 cleanup failed: {e}")

    registry.delete(doc_id)
    return {"status": "success", "message": f"Document {doc_id} deleted"}


@router.post("/reindex")
async def reindex_all_documents(background_tasks: BackgroundTasks):
    """Reindex all markdown files from the md/ directory."""
    background_tasks.add_task(_reindex_all)
    return {
        "status": "success",
        "message": "Reindexing started in background",
    }


def _reindex_all():
    """Reindex all markdown files from md/ directory."""
    import glob

    from core.retrieval.bm25_retriever import get_bm25_retriever
    from documents.markdown_parser import MarkdownParser
    from documents.milvus_db import get_milvus_manager

    md_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "md"
    )
    md_files = glob.glob(os.path.join(md_dir, "*.md"))

    if not md_files:
        log.warning(f"No markdown files found in {md_dir}")
        return

    log.info(f"Reindexing {len(md_files)} markdown files from {md_dir}")

    registry = get_document_registry()
    parser = MarkdownParser()
    manager = get_milvus_manager()

    total_inserted = 0
    for md_path in md_files:
        filename = os.path.basename(md_path)
        try:
            # Parse document
            documents = parser.parse_markdown_to_documents(md_path)
            if not documents:
                log.warning(f"No documents parsed from {filename}")
                continue

            # Add file_hash metadata
            with open(md_path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            for doc in documents:
                doc.metadata["file_hash"] = file_hash

            # Insert into Milvus
            result = manager.add_documents(documents)
            inserted = result.get("inserted", 0)
            total_inserted += inserted

            # Update registry
            doc_id = str(uuid.uuid4())[:8]
            registry.put(
                doc_id=doc_id,
                filename=filename,
                status="indexed",
                chunks=inserted,
                created_at=time.time(),
                size_bytes=os.path.getsize(md_path),
                file_hash=file_hash,
            )

            log.info(f"Reindexed: {filename}, {inserted} chunks")

        except Exception as e:
            log.error(f"Failed to reindex {filename}: {e}")

    # Rebuild BM25 index from Milvus
    try:
        from core.retrieval.cache import bump_retrieval_cache_version

        bm25 = get_bm25_retriever()
        bm25.clear()
        results = manager.query(
            filter_expr="id > 0", output_fields=["text", "source", "title"], limit=10000
        )
        if results:
            from langchain_core.documents import Document as LCDoc

            docs = [
                LCDoc(
                    page_content=r.get("text", ""),
                    metadata={"source": r.get("source", ""), "title": r.get("title", "")},
                )
                for r in results
                if r.get("text")
            ]
            if docs:
                bm25.add_documents(docs)
                log.info(f"BM25 index rebuilt: {len(docs)} docs")
        # Full rebuild invalidates all cached retrieval results.
        bump_retrieval_cache_version()
    except Exception as e:
        log.warning(f"BM25 rebuild failed: {e}")

    log.info(f"Reindex complete: {total_inserted} chunks from {len(md_files)} files")
