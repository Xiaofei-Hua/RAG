"""
Retrieve Skill

Wraps the existing retrieval pipeline (HybridRetriever / MilvusRetriever)
as a skill that can be used standalone or via the MCP retrieval server.

This skill is used in both:
- The full graph (as the ToolNode replacement / direct retriever)
- Fast mode (retrieve -> generate without agent/grade/rewrite)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from agent.skills.base import BaseSkill, SkillContext, SkillResult, SkillStatus
from utils.log_utils import log

__all__ = ["RetrieveSkill", "RetrieveSkillConfig"]


@dataclass
class RetrieveSkillConfig:
    """Configuration for RetrieveSkill."""
    top_k: int = 4
    use_hybrid: bool = True
    max_context_length: int = 2500
    # When True, returns results as ToolMessage (for graph compat)
    return_as_tool_message: bool = True


class RetrieveSkill(BaseSkill):
    """
    Skill that retrieves documents from the knowledge base.

    Wraps HybridRetriever and the existing retrieval pipeline.
    Can operate standalone or as part of a graph via MCP.
    """

    name = "retrieve"
    description = "Retrieve documents from the knowledge base"

    def __init__(
        self,
        config: Optional[RetrieveSkillConfig] = None,
        mcp_client: Optional[Any] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._skill_config = config or RetrieveSkillConfig()
        self._mcp_client = mcp_client
        self._retriever = None

    @property
    def retriever(self):
        """Lazy-load the hybrid retriever."""
        if self._retriever is None:
            from core.retrieval.hybrid_retriever import get_hybrid_retriever
            self._retriever = get_hybrid_retriever()
        return self._retriever

    def execute(self, context: SkillContext) -> SkillResult:
        """
        Retrieve documents synchronously.

        Expects the context to contain a question in the last human message
        or a tool_call from the agent.
        """
        start = time.perf_counter()
        messages = context.messages

        try:
            query = self._extract_query(context)
            if not query:
                return SkillResult(
                    status=SkillStatus.SKIPPED,
                    skill_name=self.name,
                    error="No query found in context",
                )

            # Retrieve documents (optional metadata filter + transform from shared_state)
            filter_expr = self._extract_filter(context)
            transform = self._extract_transform(context)
            documents = self._retrieve(query, filter_expr=filter_expr, transform=transform)
            documents = self._maybe_expand_parents(context, documents)
            documents = self._inject_memories(context, documents)

            # Build result messages
            result_messages = self._build_result_messages(
                documents, messages, context
            )

            elapsed = (time.perf_counter() - start) * 1000
            log.info(
                f"RetrieveSkill: {len(documents)} docs, "
                f"{elapsed:.0f}ms, query='{query[:50]}...'"
            )

            # Publish mean retrieval relevance + per-doc scores into shared_state
            # so the generate node's composite confidence can consume them
            # cross-node (previously this write was lost between nodes).
            state_updates: dict = {}
            mean_rel = self._mean_relevance(documents)
            if mean_rel is not None:
                context.shared_state["retrieval_relevance"] = mean_rel
                state_updates["shared_state"] = {"retrieval_relevance": mean_rel}

            return SkillResult(
                status=SkillStatus.SUCCESS if documents else SkillStatus.PARTIAL,
                messages=result_messages,
                next_action="grade",
                state_updates=state_updates,
                metadata={
                    "doc_count": len(documents),
                    "query": query,
                    "retrieval_time_ms": elapsed,
                },
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            log.error(f"RetrieveSkill failed ({elapsed:.0f}ms): {e}")
            return SkillResult(
                status=SkillStatus.FAILURE,
                skill_name=self.name,
                error=str(e),
                messages=[AIMessage(content="检索文档时发生错误，请稍后重试。")],
            )

    async def aexecute(self, context: SkillContext) -> SkillResult:
        """
        Retrieve documents asynchronously.

        If an MCP client is configured, delegates to the MCP retrieval server.
        Otherwise falls back to direct retrieval.
        """
        start = time.perf_counter()
        messages = context.messages

        try:
            query = self._extract_query(context)
            if not query:
                return SkillResult(
                    status=SkillStatus.SKIPPED,
                    skill_name=self.name,
                    error="No query found in context",
                )

            # Try MCP client first
            filter_expr = self._extract_filter(context)
            transform = self._extract_transform(context)
            if self._mcp_client is not None:
                try:
                    raw_results = await self._mcp_client.call_tool(
                        "rag_retrieve",
                        {
                            "query": query,
                            "top_k": self._skill_config.top_k,
                            # Forward filtering + query transform so the MCP
                            # path matches the direct-retrieval path. Previously
                            # these were dropped, causing a correctness divergence.
                            "filter_expr": filter_expr,
                            "transform": transform,
                        },
                    )
                    documents = self._raw_to_documents(raw_results)
                except Exception as e:
                    log.warning(f"MCP retrieval failed, falling back to direct: {e}")
                    documents = await self._aretrieve(query, filter_expr, transform)
            else:
                documents = await self._aretrieve(query, filter_expr, transform)
            documents = self._maybe_expand_parents(context, documents)
            documents = self._inject_memories(context, documents)

            # Build result messages
            result_messages = self._build_result_messages(
                documents, messages, context
            )

            elapsed = (time.perf_counter() - start) * 1000
            log.info(
                f"RetrieveSkill (async): {len(documents)} docs, "
                f"{elapsed:.0f}ms, query='{query[:50]}...'"
            )

            # Publish mean retrieval relevance into shared_state (parity with
            # the sync path) for cross-node composite confidence.
            state_updates: dict = {}
            mean_rel = self._mean_relevance(documents)
            if mean_rel is not None:
                context.shared_state["retrieval_relevance"] = mean_rel
                state_updates["shared_state"] = {"retrieval_relevance": mean_rel}

            return SkillResult(
                status=SkillStatus.SUCCESS if documents else SkillStatus.PARTIAL,
                messages=result_messages,
                next_action="grade",
                state_updates=state_updates,
                metadata={
                    "doc_count": len(documents),
                    "query": query,
                    "retrieval_time_ms": elapsed,
                },
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            log.error(f"RetrieveSkill async failed ({elapsed:.0f}ms): {e}")
            return SkillResult(
                status=SkillStatus.FAILURE,
                skill_name=self.name,
                error=str(e),
                messages=[AIMessage(content="检索文档时发生错误，请稍后重试。")],
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mean_relevance(documents: List[Document]) -> Optional[float]:
        """Mean of the retrieved documents' ``score`` metadata, if available."""
        scores = [
            float(d.metadata.get("score"))
            for d in documents
            if isinstance(d.metadata.get("score"), (int, float))
        ]
        if not scores:
            return None
        return sum(scores) / len(scores)

    def _retrieve(
        self,
        query: str,
        filter_expr: Optional[str] = None,
        transform: Optional[str] = None,
    ) -> List[Document]:
        """Perform retrieval using the hybrid retriever (with optional transform)."""
        try:
            if transform == "multi_query":
                from core.retrieval.query_transform import multi_query_retrieve

                return multi_query_retrieve(
                    query, self.retriever,
                    top_k=self._skill_config.top_k, filter_expr=filter_expr,
                )
            if transform == "hyde":
                from core.retrieval.query_transform import hyde

                hyde_query = hyde(query)
                return self.retriever.retrieve(
                    hyde_query, top_k=self._skill_config.top_k, filter_expr=filter_expr
                )
        except Exception as e:  # noqa: BLE001 - transform is best-effort
            log.debug(f"query transform '{transform}' failed, direct retrieve: {e}")
        return self.retriever.retrieve(
            query, top_k=self._skill_config.top_k, filter_expr=filter_expr
        )

    @staticmethod
    def _extract_transform(context: SkillContext) -> Optional[str]:
        """Which query transform to apply, if any (from shared_state).

        Recognised values: ``"hyde"`` | ``"multi_query"`` | None.
        """
        shared = getattr(context, "shared_state", None)
        if not shared:
            return None
        val = shared.get("query_transform")
        if isinstance(val, str) and val.strip() in ("hyde", "multi_query"):
            return val.strip()
        return None

    async def _aretrieve(
        self,
        query: str,
        filter_expr: Optional[str] = None,
        transform: Optional[str] = None,
    ) -> List[Document]:
        """Async retrieval with optional query transform."""
        try:
            if transform == "multi_query":
                from core.retrieval.query_transform import amulti_query_retrieve

                return await amulti_query_retrieve(
                    query, self.retriever,
                    top_k=self._skill_config.top_k, filter_expr=filter_expr,
                )
            if transform == "hyde":
                from core.retrieval.query_transform import ahyde

                hyde_query = await ahyde(query)
                return await self.retriever.aretrieve(
                    hyde_query, top_k=self._skill_config.top_k, filter_expr=filter_expr
                )
        except Exception as e:  # noqa: BLE001
            log.debug(f"query transform '{transform}' failed, direct retrieve: {e}")
        return await self.retriever.aretrieve(
            query, top_k=self._skill_config.top_k, filter_expr=filter_expr
        )

    def _extract_query(self, context: SkillContext) -> str:
        """
        Extract the search query from context.

        Looks for:
        1. Tool call arguments from the agent node
        2. Last human message content (fallback)
        """
        messages = context.messages

        # Check last AI message for tool calls
        from langchain_core.messages import AIMessage
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    for tc in tool_calls:
                        args = tc.get("args", {})
                        if "query" in args:
                            return args["query"]
                break

        # Fallback to last human message
        return context.question

    @staticmethod
    def _extract_filter(context: SkillContext) -> Optional[str]:
        """
        Extract an optional Milvus filter expression from shared state.

        Callers (e.g. the chat router) can set ``shared_state["filter_expr"]``
        to restrict retrieval by source / model / chapter, e.g.
        ``source == "engine_manual"``.
        """
        shared = getattr(context, "shared_state", None)
        if not shared:
            return None
        expr = shared.get("filter_expr")
        if isinstance(expr, str) and expr.strip():
            return expr.strip()
        return None

    @staticmethod
    def _maybe_expand_parents(
        context: SkillContext, documents: List[Document]
    ) -> List[Document]:
        """
        Optionally expand small-chunk hits to their parent documents.

        Enabled when ``shared_state["expand_parents"]`` is truthy AND the
        retrieved chunks carry ``parent_id`` metadata. When no chunk has a
        parent_id, this is a no-op (backward compatible with non-parent-child
        indexes).
        """
        shared = getattr(context, "shared_state", None)
        if not shared or not shared.get("expand_parents"):
            return documents
        if not any(
            isinstance(d.metadata, dict) and d.metadata.get("parent_id")
            for d in documents
        ):
            return documents  # nothing to expand
        try:
            from documents.parent_store import expand_to_parents

            return expand_to_parents(documents)
        except Exception as e:  # noqa: BLE001
            log.debug(f"parent expansion skipped: {e}")
            return documents

    @staticmethod
    def _inject_memories(
        context: SkillContext, documents: List[Document]
    ) -> List[Document]:
        """
        Prepend long-term memories (enriched by the memory hook) to the
        retrieved documents.

        The memory enrichment hook runs before the ``agent`` node and returns a
        ``shared_state["relevant_memories"]`` increment that is persisted into
        the graph state; this node (``retrieve``) then reads it back via its
        own ``SkillContext``. This prepends memory entries as high-priority
        context so correction memories (e.g. "振动限值应为 4.0 IPS") influence
        generation.
        """
        shared = getattr(context, "shared_state", None)
        if not shared:
            return documents
        memories = shared.get("relevant_memories")
        if not memories:
            return documents
        try:
            memory_docs = [
                Document(
                    page_content=m.get("content", "") if isinstance(m, dict) else str(m),
                    metadata={
                        "source": "agent_memory",
                        "memory_type": (m.get("type") if isinstance(m, dict) else "fact"),
                        "score": 1.0,  # memories are high-trust
                        "is_memory": True,
                    },
                )
                for m in memories
                if isinstance(m, dict) and m.get("content")
            ]
            if not memory_docs:
                return documents
            # Memories first, then retrieved docs (de-duped by content prefix).
            existing_prefixes = {d.page_content[:80] for d in documents}
            deduped = [
                md for md in memory_docs
                if md.page_content[:80] not in existing_prefixes
            ]
            return deduped + documents
        except Exception as e:  # noqa: BLE001
            log.debug(f"memory injection skipped: {e}")
            return documents

    def _build_result_messages(
        self,
        documents: List[Document],
        messages: List[BaseMessage],
        context: SkillContext,
    ) -> List[BaseMessage]:
        """
        Build result messages in the format expected by the graph.

        When return_as_tool_message is True, produces a ToolMessage
        that mirrors what LangGraph's ToolNode would emit.
        """
        if not self._skill_config.return_as_tool_message:
            # Return as plain content
            content = self._format_documents(documents)
            return [AIMessage(content=content)]

        # Find the tool_call_id from the last AI message with tool_calls
        from langchain_core.messages import AIMessage
        tool_call_id = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    tool_call_id = tool_calls[0].get("id", "retriever_call")
                    break

        if tool_call_id is None:
            tool_call_id = "retriever_call"

        content = self._format_documents(documents)
        return [
            ToolMessage(
                content=content,
                tool_call_id=tool_call_id,
            )
        ]

    @staticmethod
    def _format_documents(documents: List[Document]) -> str:
        """
        Format documents into the context string used by GenerateNode.

        Delegates to the shared :mod:`core.retrieval.formatting` layer so the
        evidence-line format is defined in one place (previously this was
        duplicated across retrieve/generate/fast-mode).
        """
        from core.retrieval.formatting import format_documents

        context, _ = format_documents(documents)
        return context

    @staticmethod
    def _raw_to_documents(raw_results: list) -> List[Document]:
        """Convert MCP raw result dicts back to Document objects."""
        documents = []
        for item in raw_results:
            if isinstance(item, dict):
                doc = Document(
                    page_content=item.get("content", ""),
                    metadata={
                        "source": item.get("source", "unknown"),
                        "title": item.get("title", "unknown"),
                        "score": item.get("score", 0.0),
                    },
                )
                documents.append(doc)
            elif isinstance(item, Document):
                documents.append(item)
        return documents

    def health_check(self) -> Dict[str, Any]:
        """Check if retriever is healthy."""
        try:
            retriever = self.retriever
            return {
                "name": self.name,
                "healthy": True,
                "retriever_type": type(retriever).__name__,
            }
        except Exception as e:
            return {"name": self.name, "healthy": False, "error": str(e)}
