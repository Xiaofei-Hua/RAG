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

            # Retrieve documents
            documents = self._retrieve(query)

            # Build result messages
            result_messages = self._build_result_messages(
                documents, messages, context
            )

            elapsed = (time.perf_counter() - start) * 1000
            log.info(
                f"RetrieveSkill: {len(documents)} docs, "
                f"{elapsed:.0f}ms, query='{query[:50]}...'"
            )

            return SkillResult(
                status=SkillStatus.SUCCESS if documents else SkillStatus.PARTIAL,
                messages=result_messages,
                next_action="grade",
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
            if self._mcp_client is not None:
                try:
                    raw_results = await self._mcp_client.call_tool(
                        "rag_retrieve",
                        {"query": query, "top_k": self._skill_config.top_k},
                    )
                    documents = self._raw_to_documents(raw_results)
                except Exception as e:
                    log.warning(f"MCP retrieval failed, falling back to direct: {e}")
                    documents = await self.retriever.aretrieve(
                        query, top_k=self._skill_config.top_k
                    )
            else:
                documents = await self.retriever.aretrieve(
                    query, top_k=self._skill_config.top_k
                )

            # Build result messages
            result_messages = self._build_result_messages(
                documents, messages, context
            )

            elapsed = (time.perf_counter() - start) * 1000
            log.info(
                f"RetrieveSkill (async): {len(documents)} docs, "
                f"{elapsed:.0f}ms, query='{query[:50]}...'"
            )

            return SkillResult(
                status=SkillStatus.SUCCESS if documents else SkillStatus.PARTIAL,
                messages=result_messages,
                next_action="grade",
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

    def _retrieve(self, query: str) -> List[Document]:
        """Perform retrieval using the hybrid retriever."""
        return self.retriever.retrieve(query, top_k=self._skill_config.top_k)

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

        Mirrors the format from GenerateNode._extract_context.
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
