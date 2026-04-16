"""
Chat Router for Enterprise RAG Platform

Handles conversation/chat endpoints.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from pydantic import BaseModel, Field

from utils.log_utils import log

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

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
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class ChatHistoryResponse(BaseModel):
    """Chat history response."""
    session_id: str
    messages: List[ChatMessage]
    total_messages: int


# =============================================================================
# Helpers
# =============================================================================

def _extract_sources(messages: list) -> List[SourceDocument]:
    """Extract source documents from graph result messages."""
    sources = []
    seen = set()
    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = msg.content
            if isinstance(content, list):
                content = " ".join(
                    item.get("text", "") if isinstance(item, dict) else str(item)
                    for item in content
                )
            if content and content not in seen:
                seen.add(content)
                # ToolMessage may not have metadata attribute or it may be None
                meta = getattr(msg, "metadata", None) or {}
                if isinstance(meta, dict):
                    source = meta.get("source")
                    title = meta.get("title")
                    score = meta.get("score", 0.0)
                else:
                    source, title, score = None, None, 0.0
                sources.append(SourceDocument(
                    content=content[:500],
                    source=source,
                    title=title,
                    score=score,
                ))
    return sources


def _sse(event: dict) -> str:
    """Format an SSE event."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


# =============================================================================
# Dependencies
# =============================================================================

async def get_session_memory():
    """Get session memory instance."""
    from core.memory.redis_memory import get_session_memory
    return get_session_memory()


async def get_intent_classifier():
    """Get intent classifier instance."""
    from core.intent.classifier import get_intent_classifier
    return get_intent_classifier()


async def get_rag_graph():
    """Get RAG graph instance."""
    from graph.graph import get_rag_graph
    return get_rag_graph()


# =============================================================================
# Endpoints
# =============================================================================

@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    session_memory = Depends(get_session_memory),
    intent_classifier = Depends(get_intent_classifier),
):
    """
    Send a message and get a response.

    This endpoint:
    1. Classifies user intent
    2. Routes to appropriate handler
    3. Returns response with sources
    """
    start_time = time.perf_counter()

    # Generate or use existing session ID
    session_id = request.session_id or str(uuid.uuid4())

    log.info(f"Chat request: session={session_id[:8]}... message={request.message[:50]}...")

    try:
        # Step 1: Intent classification
        intent_result = await intent_classifier.aclassify(request.message)

        log.info(f"Intent classified: {intent_result.intent.value}")

        # Step 2: Route based on intent
        if intent_result.intent.value == "general_chat":
            # Direct LLM response without retrieval
            from models.llm_models import get_llm
            llm = get_llm()
            response = await llm.ainvoke(request.message)
            answer = response.content
            sources = []

        else:
            # RAG pipeline with retrieval
            from graph.graph import get_rag_graph
            rag = get_rag_graph()

            result = rag.invoke(request.message, thread_id=session_id)

            # Extract response and sources
            messages = result.get("messages", [])
            if messages:
                last_message = messages[-1]
                answer = last_message.content if hasattr(last_message, 'content') else str(last_message)
            else:
                answer = "抱歉，无法生成回答。"

            sources = _extract_sources(messages)

        # Calculate processing time
        processing_time = (time.perf_counter() - start_time) * 1000

        # Save to session memory (background task)
        background_tasks.add_task(
            session_memory.save_message,
            session_id,
            HumanMessage(content=request.message)
        )
        background_tasks.add_task(
            session_memory.save_message,
            session_id,
            AIMessage(content=answer)
        )

        return ChatResponse(
            response=answer,
            session_id=session_id,
            intent=intent_result.intent.value,
            sources=sources,
            processing_time_ms=processing_time,
            metadata={
                "intent_confidence": intent_result.confidence,
                "intent_reasoning": intent_result.reasoning,
            }
        )

    except Exception as e:
        log.error(f"Chat error: {e}")

        # Check if circuit breaker is open
        from core.fallback.circuit_breaker import CircuitBreakerError
        from core.fallback.degradation import get_degradation_handler

        if isinstance(e, CircuitBreakerError):
            handler = get_degradation_handler()
            degraded = handler.generate_degraded_response(request.message, str(e))
            return ChatResponse(
                response=degraded.content,
                session_id=session_id,
                intent="degraded",
                sources=[],
                processing_time_ms=(time.perf_counter() - start_time) * 1000,
                metadata={"error": str(e)}
            )

        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    limit: int = 20,
    session_memory = Depends(get_session_memory),
):
    """Get chat history for a session."""
    try:
        messages = await session_memory.get_messages(session_id, limit=limit)

        chat_messages = []
        for msg in messages:
            role = "user" if msg.type == "human" else "assistant"
            chat_messages.append(ChatMessage(
                role=role,
                content=msg.content,
            ))

        return ChatHistoryResponse(
            session_id=session_id,
            messages=chat_messages,
            total_messages=len(chat_messages),
        )

    except Exception as e:
        log.error(f"Failed to get chat history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/session/{session_id}")
async def clear_session(
    session_id: str,
    session_memory = Depends(get_session_memory),
):
    """Clear a chat session."""
    try:
        await session_memory.clear_session(session_id)
        return {"status": "success", "message": f"Session {session_id} cleared"}
    except Exception as e:
        log.error(f"Failed to clear session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    session_memory = Depends(get_session_memory),
):
    """
    Streaming chat endpoint using RAGGraph.

    Returns response as SSE stream with progress events:
    - session: Session info
    - intent: Intent classification result
    - status: Processing status updates
    - node: Current graph node being executed
    - token: Streaming token content
    - done: Completion signal
    - error: Error information
    """
    session_id = request.session_id or str(uuid.uuid4())

    async def generate():
        try:
            # Send session info
            yield _sse({"type": "session", "session_id": session_id})

            # Step 1: Intent classification
            yield _sse({"type": "status", "message": "正在分析意图..."})

            from core.intent.classifier import get_intent_classifier
            intent_classifier = get_intent_classifier()
            intent_result = await intent_classifier.aclassify(request.message)

            yield _sse({
                "type": "intent",
                "intent": intent_result.intent.value,
                "confidence": intent_result.confidence,
            })

            # Step 2: Route based on intent
            if intent_result.intent.value == "general_chat":
                # Direct LLM streaming (no RAG)
                yield _sse({"type": "status", "message": "正在生成回答..."})

                from models.llm_models import get_llm
                llm = get_llm()

                full_response = ""
                async for chunk in llm.astream(request.message):
                    if hasattr(chunk, 'content') and chunk.content:
                        full_response += chunk.content
                        yield _sse({"type": "token", "content": chunk.content})

                # Save to session
                await session_memory.save_message(session_id, HumanMessage(content=request.message))
                await session_memory.save_message(session_id, AIMessage(content=full_response))

            else:
                # RAG pipeline via graph streaming
                from graph.graph import get_rag_graph
                rag = get_rag_graph()

                yield _sse({"type": "node", "name": "agent"})

                full_response = ""
                for event in rag.graph.stream(
                    {
                        "messages": [HumanMessage(content=request.message)],
                        "rewrite_count": 0,
                        "max_rewrites": 3,
                    },
                    config={"configurable": {"thread_id": session_id}},
                    stream_mode="updates",
                ):
                    # Each event is a dict: {node_name: node_output}
                    for node_name, node_output in event.items():
                        if node_name == "agent":
                            # Agent decided next action
                            messages = node_output.get("messages", [])
                            if messages:
                                msg = messages[-1]
                                # If agent made a tool call, it's going to retrieve
                                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                    yield _sse({"type": "node", "name": "retrieve"})
                                    yield _sse({"type": "status", "message": "正在检索知识库..."})

                        elif node_name == "retrieve":
                            # Retrieval complete — results are in ToolMessages
                            yield _sse({"type": "node", "name": "grade"})
                            yield _sse({"type": "status", "message": "正在评估文档相关性..."})

                        elif node_name == "rewrite":
                            # Query was rewritten
                            yield _sse({"type": "node", "name": "rewrite"})
                            yield _sse({"type": "status", "message": "正在优化查询..."})
                            yield _sse({"type": "node", "name": "agent"})

                        elif node_name == "generate":
                            # Final answer generated
                            yield _sse({"type": "node", "name": "generate"})
                            yield _sse({"type": "status", "message": "正在生成回答..."})
                            messages = node_output.get("messages", [])
                            if messages:
                                answer = messages[-1].content
                                full_response = answer
                                yield _sse({"type": "token", "content": answer})

                # Save to session
                await session_memory.save_message(session_id, HumanMessage(content=request.message))
                await session_memory.save_message(session_id, AIMessage(content=full_response))

            # Send completion signal
            yield _sse({"type": "done"})

        except Exception as e:
            log.error(f"Stream error: {e}")
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
