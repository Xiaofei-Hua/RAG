"""
Markdown Parser for RAG Pipeline

A production-grade markdown parser that:
- Loads markdown files using UnstructuredMarkdownLoader
- Merges elements by title hierarchy (O(n) algorithm)
- Performs semantic chunking with token-aware thresholds
- Provides safe tiktoken usage with offline fallback
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from langchain_community.document_loaders import UnstructuredMarkdownLoader
from langchain_core.documents import Document
from langchain_experimental.text_splitter import SemanticChunker

from utils.log_utils import log


def _get_local_embeddings():
    """
    Reuse the global singleton from models/embedding_models.py.

    Ensures only one embedding model instance is loaded in the process.
    """
    from models.embedding_models import get_local_embeddings

    return get_local_embeddings()


# version-safe import
try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    try:
        from langchain.text_splitter import RecursiveCharacterTextSplitter  # type: ignore
    except ImportError:
        RecursiveCharacterTextSplitter = None  # type: ignore

__all__ = [
    "MarkdownParser",
    "MarkdownParserConfig",
    "ParserStats",
    "TokenCounter",
]


# Config / Stats


@dataclass(frozen=True)
class MarkdownParserConfig:
    """Configuration for MarkdownParser with sensible defaults."""

    # Loader settings
    loader_mode: str = "elements"
    loader_strategy: str = "fast"
    remove_languages_in_metadata: bool = True

    # Merge settings
    title_path_sep: str = " -> "
    join_content_sep: str = " "
    include_title_without_content: bool = False
    keep_orphan_elements: bool = True

    # Chunk threshold (token first, char fallback)
    chunk_threshold_tokens: int = 1200
    chunk_threshold_chars_fallback: int = 5000

    # Semantic chunker settings
    semantic_breakpoint_threshold_type: str = "percentile"
    semantic_batch_size: int = 8
    keep_original_on_split_error: bool = True

    # Fallback splitter (non-semantic)
    enable_fallback_splitter: bool = True
    fallback_chunk_size_tokens: int = 900
    fallback_chunk_overlap_tokens: int = 120

    # Output metadata keys
    add_source_path_to_metadata: bool = True
    source_path_key: str = "source"
    title_key: str = "title"
    title_path_key: str = "title_path"
    merged_category_value: str = "content"

    # Tokenizer settings
    tokenizer_model_name: str | None = None
    use_tiktoken: bool = True
    tiktoken_http_timeout_s: float = 2.5

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.chunk_threshold_tokens <= 0 and self.chunk_threshold_chars_fallback <= 0:
            raise ValueError(
                "chunk_threshold_tokens and chunk_threshold_chars_fallback cannot both be <= 0"
            )
        if self.semantic_batch_size < 1:
            raise ValueError("semantic_batch_size must be >= 1")
        if self.fallback_chunk_size_tokens <= self.fallback_chunk_overlap_tokens:
            raise ValueError("fallback_chunk_size_tokens must be > fallback_chunk_overlap_tokens")
        if self.tiktoken_http_timeout_s <= 0:
            raise ValueError("tiktoken_http_timeout_s must be > 0")


@dataclass
class ParserStats:
    """Statistics collected during parsing."""

    file: str = ""
    loaded_elements: int = 0
    titles: int = 0
    merged_docs: int = 0
    chunked_docs: int = 0
    duplicates_element_id_count: int = 0
    forward_parent_ref_count: int = 0
    orphan_elements_output: int = 0
    semantic_split_input_docs: int = 0
    semantic_split_output_docs: int = 0
    semantic_split_failed_docs: int = 0
    fallback_split_used_docs: int = 0
    tokenizer_model_used: str = ""
    tokenizer_encoding_used: str = ""
    cost_ms: float = 0.0


# Token Counter (safe)


class TokenCounter:
    """
    Production-safe TokenCounter with offline fallback.

    - Attempts tiktoken for accurate token counting
    - Falls back to approximation (chars/3.2) if tiktoken unavailable
    - Uses timeout protection to avoid hanging in offline environments
    """

    # Approximate chars per token for mixed Chinese/English text
    CHARS_PER_TOKEN_APPROX = 3.2

    def __init__(
        self,
        *,
        embeddings: Any,
        model_hint: str | None,
        use_tiktoken: bool,
        timeout_s: float,
        logger: Any = log,
    ) -> None:
        self._logger = logger
        self._use_tiktoken = use_tiktoken
        self._timeout_s = max(0.1, float(timeout_s))
        self._enc: Any = None

        self.model_used = (
            (model_hint or "").strip()
            or self._infer_model_name_from_embeddings(embeddings)
            or "unknown"
        )
        self.encoding_used = "approx"

        if self._use_tiktoken:
            self._try_init_tiktoken_encoder()

    @staticmethod
    def _infer_model_name_from_embeddings(embeddings: Any) -> str | None:
        """Extract model name from embeddings object."""
        if embeddings is None:
            return None
        for attr in ("model", "model_name", "embedding_model", "openai_model"):
            try:
                value = getattr(embeddings, attr, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            except Exception:
                continue
        return None

    def _try_init_tiktoken_encoder(self) -> None:
        """Initialize tiktoken encoder with timeout protection."""
        try:
            import tiktoken  # type: ignore
        except ImportError:
            return

        # Use context manager for safe timeout handling
        with self._patch_requests_timeout():
            try:
                # Try encoding for specific model first
                if self.model_used and self.model_used != "unknown":
                    try:
                        self._enc = tiktoken.encoding_for_model(self.model_used)
                        self.encoding_used = getattr(self._enc, "name", "encoding_for_model")
                        return
                    except Exception:
                        pass

                # Fallback to cl100k_base (common encoding)
                try:
                    self._enc = tiktoken.get_encoding("cl100k_base")
                    self.encoding_used = getattr(self._enc, "name", "cl100k_base")
                except Exception:
                    self._enc = None
                    self.encoding_used = "approx"

            except Exception:
                self._enc = None
                self.encoding_used = "approx"

    @contextmanager
    def _patch_requests_timeout(self) -> Iterable[None]:
        """
        Context manager to temporarily patch requests.get with timeout.

        This avoids hanging forever when tiktoken tries to download resources
        in offline environments.
        """
        try:
            import requests  # type: ignore
        except ImportError:
            yield
            return

        orig_get = requests.get

        def get_with_timeout(*args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("timeout", self._timeout_s)
            return orig_get(*args, **kwargs)

        requests.get = get_with_timeout  # type: ignore
        try:
            yield
        finally:
            requests.get = orig_get  # type: ignore

    def count(self, text: str) -> int:
        """Count tokens in text, using tiktoken if available, else approximation."""
        if not text:
            return 0

        if self._enc is not None:
            try:
                return len(self._enc.encode(text))
            except Exception:
                pass

        # Approximation: mixed Chinese/English empirical value
        return max(1, int(len(text) / self.CHARS_PER_TOKEN_APPROX))


# Internal Element


@dataclass
class _TreeNode:
    """Tree node for representing markdown element hierarchy."""

    element: _Element
    children: list[_TreeNode] = field(default_factory=list)
    title_path: str = ""
    nearest_title: _TreeNode | None = None


@dataclass
class _Element:
    """Internal representation of a parsed markdown element."""

    idx: int
    text: str
    metadata: dict[str, Any]
    category: str | None
    element_id: str | None
    parent_id: str | None


# Parser


class MarkdownParser:
    """
    Production-grade Markdown Parser for RAG pipelines.

    Features:
    - O(n) preprocessing for parent_idx / nearest_title_idx / title_path
    - Token-aware chunking with safe tiktoken usage
    - Batch semantic splitting with fallback support
    - Comprehensive statistics tracking
    """

    def __init__(
        self,
        *,
        config: MarkdownParserConfig = MarkdownParserConfig(),
        embeddings: Any = None,
        loader_cls: type[UnstructuredMarkdownLoader] = UnstructuredMarkdownLoader,
        splitter_cls: type[SemanticChunker] = SemanticChunker,
        logger: Any = log,
    ) -> None:
        self.cfg = config
        self.log = logger
        # Use local BGE embeddings by default (no remote API dependency)
        self._embeddings = embeddings or _get_local_embeddings()
        self._loader_cls = loader_cls
        self._splitter_cls = splitter_cls

        self._token_counter = TokenCounter(
            embeddings=self._embeddings,
            model_hint=self.cfg.tokenizer_model_name,
            use_tiktoken=self.cfg.use_tiktoken,
            timeout_s=self.cfg.tiktoken_http_timeout_s,
            logger=logger,
        )

        # Lazy init: SemanticChunker construction can trigger spaCy downloads
        self._semantic_splitter: Any | None = None

        self._fallback_splitter: Any | None = None  # lazy init
        self.last_stats: ParserStats = ParserStats()

    # Public API

    @property
    def semantic_splitter(self):
        """Get semantic splitter (lazy initialization to defer spaCy download)."""
        if self._semantic_splitter is None:
            try:
                self._semantic_splitter = self._splitter_cls(
                    self._embeddings,
                    breakpoint_threshold_type=self.cfg.semantic_breakpoint_threshold_type,
                )
            except Exception as e:
                self.log.warning(f"SemanticChunker init failed: {e}, will use fallback splitter")
                self._semantic_splitter = None
        return self._semantic_splitter

    def parse_markdown_to_documents(
        self, md_file: str | Path, *, encoding: str = "utf-8"
    ) -> list[Document]:
        """
        Parse a markdown file into a list of Document objects.

        Args:
            md_file: Path to the markdown file
            encoding: File encoding (default: utf-8)

        Returns:
            List of Document objects after merging and chunking
        """
        md_path = Path(md_file)
        t0 = time.perf_counter()

        stats = ParserStats(file=str(md_path))
        stats.tokenizer_model_used = self._token_counter.model_used
        stats.tokenizer_encoding_used = self._token_counter.encoding_used

        # Step 1: Load raw documents
        raw_docs = self._parse_markdown(md_path, encoding=encoding)
        stats.loaded_elements = len(raw_docs)
        self.log.info(
            f"[MarkdownParser] loaded elements = {stats.loaded_elements}, file = {md_path.name}"
        )

        # Step 2: Normalize elements
        elements, dup_count = self._normalize_elements(raw_docs, md_path)
        stats.duplicates_element_id_count = dup_count

        # Step 3: Precompute links (O(n))
        parent_idx, nearest_title_idx, title_path, title_count, fwd_parent = self._precompute_links(
            elements
        )
        stats.titles = title_count
        stats.forward_parent_ref_count = fwd_parent

        # Step 4: Merge by title hierarchy
        merged_docs, orphan_out = self._merge_by_precomputed(
            elements=elements,
            parent_idx=parent_idx,
            nearest_title_idx=nearest_title_idx,
            title_path=title_path,
        )
        stats.merged_docs = len(merged_docs)
        stats.orphan_elements_output = orphan_out

        # Step 5: Chunk documents
        chunked_docs, sem_in, sem_out, sem_fail, fb_used = self._chunk_documents(merged_docs)
        stats.chunked_docs = len(chunked_docs)
        stats.semantic_split_input_docs = sem_in
        stats.semantic_split_output_docs = sem_out
        stats.semantic_split_failed_docs = sem_fail
        stats.fallback_split_used_docs = fb_used

        stats.cost_ms = (time.perf_counter() - t0) * 1000
        self.last_stats = stats

        self.log.info(
            f"[MarkdownParser] done "
            f"merged = {stats.merged_docs}, chunked = {stats.chunked_docs} "
            f"dup_element_id = {stats.duplicates_element_id_count} "
            f"forward_parent_ref = {stats.forward_parent_ref_count} "
            f"orphans_out = {stats.orphan_elements_output} "
            f"semantic_in = {sem_in} semantic_out = {sem_out} "
            f"semantic_fail = {sem_fail} fallback_used = {fb_used} "
            f"tokenizer_model = {stats.tokenizer_model_used} "
            f"enc = {stats.tokenizer_encoding_used} "
            f"cost = {stats.cost_ms:.1f}ms file = {md_path.name}"
        )
        return chunked_docs

    def get_last_stats(self) -> dict[str, Any]:
        """Return statistics from the last parse operation."""
        return asdict(self.last_stats)

    # Loader

    def _parse_markdown(self, md_path: Path, *, encoding: str) -> list[Document]:
        """Load markdown file. Uses simple regex parser by default for speed."""
        if not md_path.exists() or not md_path.is_file():
            raise FileNotFoundError(f"Markdown file not found: {md_path}")

        # Prefer simple loader: fast, no external deps (no spaCy download)
        return self._simple_markdown_load(md_path, encoding)

    def _simple_markdown_load(self, md_path: Path, encoding: str) -> list[Document]:
        """
        Simple markdown loader that doesn't depend on unstructured/spaCy.

        Parses markdown by splitting on headings (# ) and creates
        Title + NarrativeText elements similar to unstructured output.
        """
        import re

        with open(md_path, encoding=encoding) as f:
            content = f.read()

        if not content.strip():
            return []

        # Split into sections by headings
        sections = re.split(r"(^#{1,6}\s+.+$)", content, flags=re.MULTILINE)

        documents = []
        idx = 0

        # Handle content before first heading
        if sections and not sections[0].startswith("#"):
            pre_content = sections[0].strip()
            if pre_content:
                documents.append(
                    Document(
                        page_content=pre_content,
                        metadata={
                            "category": "NarrativeText",
                            "element_id": f"pre_{idx}",
                            "parent_id": None,
                        },
                    )
                )
                idx += 1
            sections = sections[1:]

        # Process heading + content pairs
        current_parent_id = None
        for i in range(0, len(sections) - 1, 2):
            heading = sections[i].strip() if i < len(sections) else ""
            body = sections[i + 1].strip() if i + 1 < len(sections) else ""

            if not heading:
                continue

            title_text = re.sub(r"^#{1,6}\s+", "", heading)
            title_id = f"title_{idx}"
            level = len(heading) - len(heading.lstrip("#"))

            # Add title element
            documents.append(
                Document(
                    page_content=title_text,
                    metadata={
                        "category": "Title",
                        "element_id": title_id,
                        "parent_id": current_parent_id if level > 1 else None,
                    },
                )
            )
            idx += 1

            # Update parent for nested headings
            if level == 1:
                current_parent_id = title_id
            elif level > 1:
                current_parent_id = title_id

            # Add body content
            if body:
                for para in body.split("\n\n"):
                    para = para.strip()
                    if para:
                        documents.append(
                            Document(
                                page_content=para,
                                metadata={
                                    "category": "NarrativeText",
                                    "element_id": f"text_{idx}",
                                    "parent_id": title_id,
                                },
                            )
                        )
                        idx += 1

        self.log.info(f"Simple markdown loader: {len(documents)} elements from {md_path.name}")
        return documents

    # Normalize

    def _clean_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Clean and normalize metadata dictionary."""
        result = dict(metadata or {})
        if self.cfg.remove_languages_in_metadata:
            result.pop("languages", None)
        return result

    def _normalize_elements(
        self, docs: Sequence[Document], md_path: Path
    ) -> tuple[list[_Element], int]:
        """Convert raw documents to internal _Element objects."""
        elements: list[_Element] = []
        seen_ids: set[str] = set()
        dup_count = 0

        for idx, doc in enumerate(docs):
            metadata = self._clean_metadata(doc.metadata)

            if self.cfg.add_source_path_to_metadata:
                metadata.setdefault(self.cfg.source_path_key, str(md_path))

            category = metadata.get("category")
            element_id = metadata.get("element_id")
            parent_id = metadata.get("parent_id")

            # Normalize IDs
            element_id = element_id if isinstance(element_id, str) and element_id else None
            parent_id = parent_id if isinstance(parent_id, str) and parent_id else None

            # Track duplicates
            if element_id:
                if element_id in seen_ids:
                    dup_count += 1
                else:
                    seen_ids.add(element_id)

            elements.append(
                _Element(
                    idx=idx,
                    text=(doc.page_content or "").strip(),
                    metadata=metadata,
                    category=category,
                    element_id=element_id,
                    parent_id=parent_id,
                )
            )

        return elements, dup_count

    # Build Tree & DFS Traversal

    def _build_element_tree(
        self, elements: Sequence[_Element]
    ) -> tuple[list[_TreeNode], dict[int, _TreeNode], dict[str, _TreeNode], int]:
        """
        Build a tree structure from elements based on parent_id relationships.

        Returns:
            - roots: List of root nodes (elements without valid parent)
            - idx_to_node: Mapping from element index to tree node
            - id_to_node: Mapping from element_id to tree node
            - forward_parent_ref: Count of forward parent references
        """
        # First pass: create tree nodes and build mappings
        idx_to_node: dict[int, _TreeNode] = {}
        id_to_node: dict[str, _TreeNode] = {}

        for el in elements:
            node = _TreeNode(element=el)
            idx_to_node[el.idx] = node
            if el.element_id:
                id_to_node[el.element_id] = node

        # Second pass: build parent-child relationships
        forward_parent_ref = 0
        roots: list[_TreeNode] = []
        nodes_list = list(idx_to_node.values())

        for node in nodes_list:
            el = node.element
            if el.parent_id and el.parent_id in id_to_node:
                parent_node = id_to_node[el.parent_id]
                # Check if parent appears before child (valid tree)
                if parent_node.element.idx < el.idx:
                    parent_node.children.append(node)
                else:
                    # Forward reference: parent appears after child
                    forward_parent_ref += 1
                    roots.append(node)
            else:
                # No parent or invalid parent_id -> root
                if el.parent_id:  # parent_id exists but not found in id_to_node
                    forward_parent_ref += 1
                roots.append(node)

        return roots, idx_to_node, id_to_node, forward_parent_ref

    def _dfs_compute_title_info(
        self,
        node: _TreeNode,
        parent_title_path: str,
        current_nearest_title: _TreeNode | None,
    ) -> None:
        """
        DFS traversal to compute title_path and nearest_title for each node.

        Args:
            node: Current tree node
            parent_title_path: Title path from parent (for building hierarchy)
            current_nearest_title: Nearest title ancestor (for content elements)
        """
        el = node.element

        if el.category == "Title":
            # Build title path: parent_path + current_title
            if parent_title_path:
                node.title_path = f"{parent_title_path}{self.cfg.title_path_sep}{el.text}"
            else:
                node.title_path = el.text
            # This node becomes the nearest title for itself and descendants
            node.nearest_title = node
            nearest_for_children = node
        else:
            # Non-title element: inherit parent's title path and nearest title
            node.title_path = parent_title_path
            node.nearest_title = current_nearest_title
            nearest_for_children = current_nearest_title

        # Recursively process children
        for child in node.children:
            self._dfs_compute_title_info(child, node.title_path, nearest_for_children)

    def _precompute_links(
        self, elements: Sequence[_Element]
    ) -> tuple[list[int], list[int], dict[int, str], int, int]:
        """
        Precompute parent indices, nearest title indices, and title paths using DFS.

        Returns:
            - parent_idx: List where parent_idx[i] is the index of element i's parent
            - nearest_title_idx: List where nearest_title_idx[i] is the index of nearest title
            - title_path: Dict mapping element index to its full title path string
            - title_count: Total number of titles
            - forward_parent_ref: Count of forward parent references (parent appears after child)
        """
        # Build tree structure (includes idx_to_node and id_to_node mappings)
        roots, idx_to_node, id_to_node, forward_parent_ref = self._build_element_tree(elements)

        # DFS to compute title_path and nearest_title for all nodes
        for root in roots:
            self._dfs_compute_title_info(root, "", None)

        # Extract results into arrays/dicts
        n = len(elements)
        parent_idx: list[int] = [-1] * n
        nearest_title_idx: list[int] = [-1] * n
        title_path: dict[int, str] = {}
        title_count = 0

        for el in elements:
            idx = el.idx
            node = idx_to_node[idx]

            # Resolve parent index
            if el.parent_id and el.parent_id in id_to_node:
                parent_node = id_to_node[el.parent_id]
                # Only set if parent appears before child
                if parent_node.element.idx < idx:
                    parent_idx[idx] = parent_node.element.idx

            # Get nearest title index from DFS result
            if node.nearest_title is not None:
                nearest_title_idx[idx] = node.nearest_title.element.idx

            # Get title path from DFS result
            if node.title_path:
                title_path[idx] = node.title_path

            # Count titles
            if el.category == "Title":
                title_count += 1

        return parent_idx, nearest_title_idx, title_path, title_count, forward_parent_ref

    # Merge

    def _merge_by_precomputed(
        self,
        *,
        elements: Sequence[_Element],
        parent_idx: Sequence[int],
        nearest_title_idx: Sequence[int],
        title_path: dict[int, str],
    ) -> tuple[list[Document], int]:
        """Merge elements by title hierarchy using precomputed indices."""
        title_bucket: dict[int, list[str]] = {}
        out_with_idx: list[tuple[int, Document]] = []
        orphan_out = 0

        # Initialize title buckets
        for i, el in enumerate(elements):
            if el.category == "Title":
                title_bucket[i] = []

        # Distribute content to title buckets
        for i, el in enumerate(elements):
            if not el.text or el.category == "Title":
                continue

            # NarrativeText without parent: output directly
            if el.category == "NarrativeText" and not el.parent_id:
                out_with_idx.append(
                    (el.idx, Document(page_content=el.text, metadata=dict(el.metadata)))
                )
                continue

            # Assign to nearest title bucket
            t_idx = nearest_title_idx[i]
            if t_idx != -1 and t_idx in title_bucket:
                title_bucket[t_idx].append(el.text)
            else:
                # Orphan element
                if self.cfg.keep_orphan_elements:
                    metadata = dict(el.metadata)
                    metadata.setdefault("category", el.category or "orphan")
                    out_with_idx.append((el.idx, Document(page_content=el.text, metadata=metadata)))
                    orphan_out += 1

        # Build merged documents
        for t_idx in sorted(title_bucket.keys()):
            t_el = elements[t_idx]
            merged_content = self.cfg.join_content_sep.join(title_bucket[t_idx]).strip()
            t_path = (title_path.get(t_idx) or t_el.text).strip()

            # Skip empty titles if configured
            if not merged_content and not self.cfg.include_title_without_content:
                continue

            # Build page content
            page = t_path if not merged_content else f"{t_path}\n\n{merged_content}"

            # Build metadata
            metadata = dict(t_el.metadata)
            metadata[self.cfg.title_key] = t_el.text
            metadata[self.cfg.title_path_key] = t_path
            metadata["category"] = self.cfg.merged_category_value if merged_content else "Title"
            metadata["idx"] = t_idx
            metadata["resolved_parent_idx"] = parent_idx[t_idx]
            metadata.setdefault("doc_id", self._generate_doc_id(metadata, t_idx, page))

            out_with_idx.append((t_el.idx, Document(page_content=page, metadata=metadata)))

        # Sort by original index to preserve document order
        out_with_idx.sort(key=lambda x: x[0])
        return [doc for _, doc in out_with_idx], orphan_out

    @staticmethod
    def _generate_doc_id(metadata: dict[str, Any], idx: int, text: str) -> str:
        """Generate a stable document ID using SHA256 (truncated)."""
        source = str(metadata.get("source", ""))
        content_head = text[:256]
        raw = f"{source}#{idx}#{content_head}".encode("utf-8", errors="ignore")
        # Use first 16 chars of SHA256 for shorter but still unique ID
        return hashlib.sha256(raw).hexdigest()[:16]

    # Chunking

    def _is_over_threshold(self, text: str) -> bool:
        """Check if text exceeds the configured token/char threshold."""
        if not text:
            return False

        if self.cfg.chunk_threshold_tokens > 0:
            return self._token_counter.count(text) > self.cfg.chunk_threshold_tokens

        return len(text) > self.cfg.chunk_threshold_chars_fallback

    def _ensure_fallback_splitter(self) -> None:
        """
        Initialize fallback splitter with token-aware length function.

        Note: Uses length_function instead of from_tiktoken_encoder() to avoid
        potential hanging in offline environments.
        """
        if self._fallback_splitter is not None:
            return

        if not self.cfg.enable_fallback_splitter or RecursiveCharacterTextSplitter is None:
            return

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.cfg.fallback_chunk_size_tokens,
            chunk_overlap=self.cfg.fallback_chunk_overlap_tokens,
            length_function=self._token_counter.count,  # Token-aware with fallback
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

    def _chunk_documents(
        self, docs: Sequence[Document]
    ) -> tuple[list[Document], int, int, int, int]:
        """
        Chunk documents using semantic splitting for large docs.

        Returns:
            - List of chunked documents
            - semantic_split_input_docs: Number of docs sent to semantic splitter
            - semantic_split_output_docs: Number of docs produced by semantic splitter
            - semantic_split_failed_docs: Number of docs that failed semantic splitting
            - fallback_split_used_docs: Number of docs processed by fallback splitter
        """
        small: list[Document] = []
        large: list[Document] = []

        for doc in docs:
            text = doc.page_content or ""
            if text:
                (large if self._is_over_threshold(text) else small).append(doc)

        semantic_in = len(large)
        semantic_out = 0
        semantic_fail = 0
        fallback_used = 0

        result: list[Document] = list(small)

        if not large:
            return result, 0, 0, 0, 0

        batch_size = max(1, int(self.cfg.semantic_batch_size))

        for batch in self._batched(large, batch_size):
            # Try batch semantic split
            splitter = self.semantic_splitter
            if splitter is not None:
                try:
                    pieces = splitter.split_documents(list(batch))
                    result.extend(pieces)
                    semantic_out += len(pieces)
                    continue
                except Exception as e:
                    self.log.warning(f"[MarkdownParser] batch semantic split failed: {e}")

            # Fallback: process individually or use fallback splitter
            for doc in batch:
                split_done = False
                if splitter is not None:
                    try:
                        pieces = splitter.split_documents([doc])
                        result.extend(pieces)
                        semantic_out += len(pieces)
                        split_done = True
                        continue
                    except Exception as e:
                        semantic_fail += 1
                        self.log.warning(f"[MarkdownParser] semantic split failed for doc: {e}")

                if not split_done:
                    # Try fallback splitter
                    self._ensure_fallback_splitter()
                    if self._fallback_splitter is not None:
                        try:
                            pieces = self._fallback_splitter.split_documents([doc])
                            result.extend(pieces)
                            fallback_used += 1
                            continue
                        except Exception as e2:
                            self.log.warning(f"[MarkdownParser] fallback split failed: {e2}")

                    # Last resort: keep original
                    if self.cfg.keep_original_on_split_error:
                        result.append(doc)

        return result, semantic_in, semantic_out, semantic_fail, fallback_used

    @staticmethod
    def _batched(items: Sequence[Document], batch_size: int) -> Iterable[Sequence[Document]]:
        """Yield batches of documents."""
        for i in range(0, len(items), batch_size):
            yield items[i : i + batch_size]


# Main Entry Point

if __name__ == "__main__":
    file_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "md", "tech_report_0tfhhamx.md"
    )

    parser = MarkdownParser(
        config=MarkdownParserConfig(
            chunk_threshold_tokens=1200,
            chunk_threshold_chars_fallback=5000,
            semantic_batch_size=8,
            enable_fallback_splitter=True,
            use_tiktoken=True,
            tiktoken_http_timeout_s=2.5,
        )
    )

    docs = parser.parse_markdown_to_documents(file_path, encoding="utf-8")
    print(f"Final docs: {len(docs)}")
    print("Stats:", parser.get_last_stats())
