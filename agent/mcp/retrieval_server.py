"""
MCP Retrieval Server

Exposes retrieval tools via the MCP protocol:
- rag_retrieve: hybrid (dense + BM25) retrieval
- rag_search_dense: dense-only vector search
- rag_search_sparse: BM25-only keyword search

Wraps the existing core.retrieval.hybrid_retriever.HybridRetriever
and tools.retriever_tools.RetrieverManager.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from agent.mcp.server import InProcessMCPServer, MCPServerConfig
from utils.log_utils import log

__all__ = ["MCPRetrievalServer"]


class MCPRetrievalServer(InProcessMCPServer):
    """
    MCP server that exposes RAG retrieval as MCP tools.

    Delegates to HybridRetriever (dense + sparse) and the
    Milvus-backed RetrieverManager from the existing codebase.
    """

    def __init__(
        self,
        default_top_k: int = 4,
        config: Optional[MCPServerConfig] = None,
    ):
        server_config = config or MCPServerConfig(
            name="rag-retrieval-server",
            description="MCP server for RAG retrieval tools",
        )
        super().__init__(server_config)
        self._default_top_k = default_top_k
        self._register_tools()

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        """Register all retrieval tools on this server."""

        # --- rag_retrieve: hybrid retrieval ---
        self.register_tool(
            name="rag_retrieve",
            description=(
                "搜索并返回关于飞机故障分析、排故程序、维修手册、故障代码的信息, "
                "内容涵盖：飞机各系统（发动机、液压、航电、结构等）的故障诊断、"
                "排故流程、维修方案和技术通报"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return",
                        "default": self._default_top_k,
                    },
                    "filter_expr": {
                        "type": "string",
                        "description": (
                            "Optional Milvus boolean expression to pre-filter "
                            "dense candidates, e.g. source == \"engine_manual\""
                        ),
                    },
                    "transform": {
                        "type": "string",
                        "description": (
                            "Optional query transform: 'hyde' or 'multi_query'"
                        ),
                    },
                },
                "required": ["query"],
            },
            handler=self._hybrid_retrieve,
        )

        # --- rag_search_dense: dense-only vector search ---
        self.register_tool(
            name="rag_search_dense",
            description=(
                "Dense vector search in the knowledge base. "
                "Returns documents ranked by semantic similarity."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return",
                        "default": self._default_top_k,
                    },
                },
                "required": ["query"],
            },
            handler=self._dense_search,
        )

        # --- rag_search_sparse: BM25 keyword search ---
        self.register_tool(
            name="rag_search_sparse",
            description=(
                "Sparse (BM25) keyword search in the knowledge base. "
                "Returns documents ranked by keyword matching."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return",
                        "default": self._default_top_k,
                    },
                },
                "required": ["query"],
            },
            handler=self._sparse_search,
        )

        log.info("MCPRetrievalServer: 3 retrieval tools registered")

    # ------------------------------------------------------------------
    # Handler implementations (delegate to existing code)
    # ------------------------------------------------------------------

    def _hybrid_retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_expr: Optional[str] = None,
        transform: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid retrieval using dense + BM25 via HybridRetriever.

        Forwards ``filter_expr`` (Milvus pre-filter) and ``transform``
        (hyde/multi_query) so the MCP path matches the direct-retrieval path.
        Returns formatted result dicts with content, source, score.
        """
        top_k = top_k or self._default_top_k

        start = time.perf_counter()
        try:
            from core.retrieval.hybrid_retriever import get_hybrid_retriever
            retriever = get_hybrid_retriever()
            if transform == "multi_query":
                from core.retrieval.query_transform import multi_query_retrieve
                documents = multi_query_retrieve(
                    query, retriever, top_k=top_k, filter_expr=filter_expr
                )
            elif transform == "hyde":
                from core.retrieval.query_transform import hyde
                hyde_query = hyde(query)
                documents = retriever.retrieve(
                    hyde_query, top_k=top_k, filter_expr=filter_expr
                )
            else:
                documents = retriever.retrieve(
                    query, top_k=top_k, filter_expr=filter_expr
                )
            elapsed_ms = (time.perf_counter() - start) * 1000

            log.info(
                f"MCP rag_retrieve: {len(documents)} docs, "
                f"{elapsed_ms:.0f}ms, query='{query[:50]}...'"
                f"{f', filter={filter_expr}' if filter_expr else ''}"
                f"{f', transform={transform}' if transform else ''}"
            )
            return self._format_documents(documents)

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            log.error(f"MCP rag_retrieve failed ({elapsed_ms:.0f}ms): {e}")
            raise

    def _dense_search(self, query: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        """Dense-only retrieval via MilvusManager."""
        top_k = top_k or self._default_top_k

        start = time.perf_counter()
        try:
            from agent.mcp.retriever_tools import RetrieverManager, RetrieverConfig
            config = RetrieverConfig(top_k=top_k, use_hybrid=False)
            with RetrieverManager(config) as manager:
                documents = manager.search(query, top_k=top_k)
            elapsed_ms = (time.perf_counter() - start) * 1000

            log.info(
                f"MCP rag_search_dense: {len(documents)} docs, "
                f"{elapsed_ms:.0f}ms, query='{query[:50]}...'"
            )
            return self._format_documents(documents)

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            log.error(f"MCP rag_search_dense failed ({elapsed_ms:.0f}ms): {e}")
            raise

    def _sparse_search(self, query: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        """Sparse-only BM25 retrieval.

        Uses the hybrid retriever's shared BM25 index (which is auto-synced
        from Milvus on first access). Previously this constructed a brand-new
        empty ``BM25Retriever()`` per call, which always returned zero results
        because the index was never populated.
        """
        top_k = top_k or self._default_top_k

        start = time.perf_counter()
        try:
            from core.retrieval.hybrid_retriever import get_hybrid_retriever
            retriever = get_hybrid_retriever()
            results = retriever.sparse_retriever.retrieve(query, top_k=top_k)
            documents = [r.document for r in results]
            elapsed_ms = (time.perf_counter() - start) * 1000

            log.info(
                f"MCP rag_search_sparse: {len(documents)} docs, "
                f"{elapsed_ms:.0f}ms, query='{query[:50]}...'"
            )
            return self._format_documents(documents)

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            log.error(f"MCP rag_search_sparse failed ({elapsed_ms:.0f}ms): {e}")
            raise

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_documents(documents: List[Document]) -> List[Dict[str, Any]]:
        """Convert LangChain Documents to MCP-friendly dicts."""
        results = []
        for idx, doc in enumerate(documents, 1):
            meta = getattr(doc, "metadata", None) or {}
            content = doc.page_content if hasattr(doc, "page_content") else str(doc)
            results.append({
                "index": idx,
                "content": content,
                "source": meta.get("source", "unknown"),
                "title": meta.get("title", "unknown"),
                "score": meta.get("score", 0.0),
            })
        return results

    @staticmethod
    def documents_to_tool_content(documents: List[Document]) -> str:
        """
        Format documents into the content string that the ToolMessage
        node expects (mirrors the format used by LangChain's ToolNode).
        """
        parts: list[str] = []
        for idx, doc in enumerate(documents, 1):
            text = doc.page_content.strip() if hasattr(doc, "page_content") else str(doc).strip()
            if not text:
                continue
            meta = getattr(doc, "metadata", None) or {}
            source = meta.get("source", "unknown")
            title = meta.get("title", "unknown")
            score = meta.get("score")
            score_text = f"{float(score):.4f}" if isinstance(score, (int, float)) else "N/A"
            parts.append(
                f"[证据{idx}] 来源={source} | 标题={title} | 相关度={score_text}\n{text}"
            )
        return "\n\n".join(parts)
