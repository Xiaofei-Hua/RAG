"""
Chat Router for Enterprise RAG Platform

Handles conversation/chat endpoints.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from pydantic import BaseModel, Field

from utils.log_utils import log
from utils.think_tag_utils import strip_think_tags
from core.prompts.aircraft_prompts import (
    GENERATE_SYSTEM_PROMPT,
    GENERAL_CHAT_SYSTEM_PROMPT,
    PHM_IDENTITY_RESPONSE,
)

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class ChatMessage(BaseModel):
    """Single chat message."""
    role: str = Field(..., description="Message role: user, assistant, or system")
    content: str = Field(..., description="Message content")
    timestamp: Optional[float] = Field(None, description="Unix timestamp when message was saved")


class ChatRequest(BaseModel):
    """Chat request model."""
    message: str = Field(..., description="User message", min_length=1)
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity")
    stream: bool = Field(False, description="Enable streaming response")
    include_sources: bool = Field(True, description="Include source documents in response")
    mode: Literal["thinking", "fast"] = Field("thinking", description="Response mode: 'thinking' uses full graph pipeline, 'fast' uses direct retrieval + generation")


class SourceDocument(BaseModel):
    """Source document in response."""
    content: str
    source: Optional[str] = None
    title: Optional[str] = None
    score: float = 0.0
    retrieval_score: Optional[float] = None
    rerank_score: Optional[float] = None
    rerank_applied: bool = False


class ChatResponse(BaseModel):
    """Chat response model."""
    response: str = Field(..., description="Assistant response")
    session_id: str = Field(..., description="Session ID")
    intent: str = Field(..., description="Detected intent")
    sources: List[SourceDocument] = Field(default_factory=list, description="Source documents")
    processing_time_ms: float = Field(..., description="Processing time in milliseconds")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class PHMDiagnosis(BaseModel):
    """Structured PHM diagnosis extracted from model response."""
    conclusion: str = ""
    possible_causes: List[str] = Field(default_factory=list)
    troubleshooting_steps: List[str] = Field(default_factory=list)
    safety_risks: str = ""
    evidence_sources: List[str] = Field(default_factory=list)
    info_gaps: str = ""


class ChatHistoryResponse(BaseModel):
    """Chat history response."""
    session_id: str
    messages: List[ChatMessage]
    total_messages: int


# =============================================================================
# Helpers
# =============================================================================

def _confidence_level(confidence: Optional[float]) -> str:
    """Map a numeric confidence to a coarse level for the UI."""
    if confidence is None:
        return "unknown"
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


def _capture(
    http_request: Request,
    request_message: str,
    answer: str,
    sources: list,
    reasoning: str,
    route: str,
    prompt_profile: str,
    intent: str,
    metadata: dict,
    latency_ms: float,
    trace_id: str,
    session_id: str,
) -> None:
    """
    Capture this inference for the evaluation flywheel (sampled).

    Never raises — capture failures are logged but never break the chat
    response. The sampled trace_id / message_id are written back into
    ``metadata`` so the client can reference them when submitting feedback.
    """
    try:
        from agent.eval.capture import maybe_capture_inference

        maybe_capture_inference(
            request_message=request_message,
            answer=answer,
            sources=sources,
            reasoning=reasoning,
            route=route,
            prompt_profile=prompt_profile,
            intent=intent,
            metadata=metadata,
            latency_ms=latency_ms,
            trace_id=trace_id,
            session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001 - capture must not break chat
        log.debug(f"inference capture skipped: {exc}")


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
                if not source:
                    source = _extract_line_value(content, "Source")
                if not title:
                    title = _extract_line_value(content, "Title")
                parsed_score = _extract_line_value(content, "Score")
                if parsed_score:
                    try:
                        score = float(parsed_score)
                    except ValueError:
                        pass
                sources.append(SourceDocument(
                    content=content[:500],
                    source=source,
                    title=title,
                    score=score,
                ))
    return sources


def _extract_line_value(text: str, key: str) -> Optional[str]:
    """Extract a value from a line like `Key: value`."""
    pattern = rf"(?im)^\s*{re.escape(key)}\s*:\s*(.+?)\s*$"
    match = re.search(pattern, text)
    if match:
        value = match.group(1).strip()
        return value if value else None
    return None


def _extract_section(text: str, title: str, next_titles: List[str]) -> str:
    """Extract section content from PHM structured answer."""
    marker = f"【{title}】"
    start = text.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = len(text)
    for next_title in next_titles:
        next_marker = f"【{next_title}】"
        idx = text.find(next_marker, start)
        if idx >= 0:
            end = min(end, idx)
    return text[start:end].strip()


def _extract_numbered_items(text: str) -> List[str]:
    """Parse numbered items from a section."""
    if not text:
        return []
    items = re.findall(r"(?:^|\n)\s*\d+[.)、]\s*(.+)", text)
    if items:
        return [item.strip() for item in items if item.strip()]
    # Fallback: split by lines when numbering is absent
    return [line.strip("- ").strip() for line in text.splitlines() if line.strip()]


def _extract_phm_diagnosis(answer: str) -> Optional[PHMDiagnosis]:
    """Extract PHM diagnosis blocks from generated answer."""
    section_order = [
        "诊断结论",
        "可能原因",
        "排查步骤",
        "风险与安全提示",
        "依据来源",
        "信息缺口",
    ]
    extracted: Dict[str, str] = {}
    for idx, section in enumerate(section_order):
        extracted[section] = _extract_section(answer, section, section_order[idx + 1 :])

    if not any(extracted.values()):
        return None

    return PHMDiagnosis(
        conclusion=extracted["诊断结论"],
        possible_causes=_extract_numbered_items(extracted["可能原因"]),
        troubleshooting_steps=_extract_numbered_items(extracted["排查步骤"]),
        safety_risks=extracted["风险与安全提示"],
        evidence_sources=_extract_numbered_items(extracted["依据来源"]),
        info_gaps=extracted["信息缺口"],
    )


def _looks_like_phm_query(message: str) -> bool:
    """Heuristic PHM query detection to prevent misrouting."""
    text = (message or "").lower()
    if not text:
        return False

    keywords = [
        "故障", "排故", "诊断", "维修", "机务", "航材", "工卡", "手册", "状态监测",
        "预测性维护", "健康管理", "振动", "液压", "发动机", "航电", "告警", "故障码",
        "troubleshoot", "fault", "ata", "fws", "ecam", "eicas", "maintenance",
    ]
    if any(k in text for k in keywords):
        return True

    # ATA chapter pattern
    return bool(re.search(r"\bata[\s\-_:]*\d{2}\b", text, flags=re.IGNORECASE))


def _is_identity_capability_query(message: str) -> bool:
    """Detect 'who are you / what can you do' style questions."""
    text = (message or "").strip().lower()
    if not text:
        return False
    patterns = [
        r"你是谁",
        r"你是干什么的",
        r"你有什么功能",
        r"你能做什么",
        r"你的功能",
        r"介绍一下你",
        r"你会什么",
        r"who are you",
        r"what can you do",
    ]
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


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
    """Get agent harness instance."""
    from agent.harness import get_agent_harness
    return get_agent_harness()


@router.get("/prompt-status")
async def get_prompt_status():
    """Return current prompt profile and signature for runtime verification."""
    signature = hashlib.sha1(GENERATE_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]
    return {
        "loaded": True,
        "prompt_profile": "phm_diagnosis_v1",
        "generate_prompt_signature": signature,
        "generate_prompt_preview": GENERATE_SYSTEM_PROMPT[:120],
    }


# =============================================================================
# Endpoints
# =============================================================================

@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    session_memory = Depends(get_session_memory),
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
    route = "general_chat"
    prompt_profile = "base"
    force_rag = False
    # trace_id propagated by the tracing middleware; message_id minted here so
    # feedback can later point back at this exact answer.
    trace_id = getattr(getattr(http_request, "state", None), "trace_id", "") or str(uuid.uuid4())[:16]
    message_id = str(uuid.uuid4())
    # Answer trustworthiness, populated by the generate skill (RAG route).
    gen_confidence = None
    gen_refused = False
    reasoning_text = ""  # initialised for general_chat / fast branches (RAG fills it)

    log.info(f"Chat request: session={session_id[:8]}... message={request.message[:50]}...")

    try:
        if _is_identity_capability_query(request.message):
            answer = PHM_IDENTITY_RESPONSE
            processing_time = (time.perf_counter() - start_time) * 1000
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
            identity_meta = {
                "intent_confidence": 1.0,
                "intent_reasoning": "Identity/capability shortcut",
                "source_count": 0,
                "diagnosis": None,
                "route": "general_chat",
                "prompt_profile": "phm_identity_v1",
                "force_rag": False,
                "message_id": message_id,
            }
            _capture(http_request, request.message, answer, [], "",
                     "general_chat", "phm_identity_v1", "general_chat",
                     identity_meta, processing_time, trace_id, session_id)
            return ChatResponse(
                response=answer,
                session_id=session_id,
                intent="general_chat",
                sources=[],
                processing_time_ms=processing_time,
                metadata=identity_meta,
            )

        # Fast mode: skip intent classification / agent / grading, directly retrieve + generate
        if request.mode == "fast":
            from core.fast_mode import fast_generate_async

            result = await fast_generate_async(request.message)
            processing_time = (time.perf_counter() - start_time) * 1000

            background_tasks.add_task(
                session_memory.save_message,
                session_id,
                HumanMessage(content=request.message)
            )
            background_tasks.add_task(
                session_memory.save_message,
                session_id,
                AIMessage(content=result.answer)
            )

            fast_sources = [SourceDocument(**s) for s in result.sources]
            fast_meta = {
                "intent_confidence": 1.0,
                "intent_reasoning": "Fast mode (no classification)",
                "source_count": result.retrieval_count,
                "diagnosis": None,
                "route": "fast",
                "prompt_profile": "phm_fast_v1",
                "force_rag": False,
                "retrieval_time_ms": result.retrieval_time_ms,
                "generation_time_ms": result.generation_time_ms,
                "message_id": message_id,
            }
            _capture(http_request, request.message, result.answer, fast_sources, "",
                     "fast", "phm_fast_v1", "rag_query",
                     fast_meta, processing_time, trace_id, session_id)
            return ChatResponse(
                response=result.answer,
                session_id=session_id,
                intent="rag_query",
                sources=fast_sources,
                processing_time_ms=processing_time,
                metadata=fast_meta,
            )

        # Step 1: Intent classification
        from core.intent.classifier import get_intent_classifier
        intent_classifier = get_intent_classifier()
        intent_result = await intent_classifier.aclassify(request.message)

        log.info(f"Intent classified: {intent_result.intent.value}")

        # Step 2: Route based on intent + PHM heuristic safeguard
        use_rag = intent_result.intent.value != "general_chat"
        if not use_rag and _looks_like_phm_query(request.message):
            use_rag = True
            force_rag = True
            log.info("Intent override: forcing RAG route for PHM-like query")

        if not use_rag:
            # Direct LLM response without retrieval
            from models.llm_models import get_llm
            llm = get_llm()

            # Load conversation history for multi-turn context
            history = await session_memory.get_messages(session_id)
            history = list(reversed(history))  # oldest-first

            history_msgs = [SystemMessage(content=GENERAL_CHAT_SYSTEM_PROMPT)]
            for hm in history:
                history_msgs.append(hm)
            history_msgs.append(HumanMessage(content=request.message))

            response = await llm.ainvoke(history_msgs)
            answer = strip_think_tags(response.content)
            sources = []
            route = "general_chat"
            prompt_profile = "phm_general_v1"

        else:
            # RAG pipeline with retrieval
            from agent.harness import get_agent_harness
            harness = get_agent_harness()

            result = await harness.ainvoke(request.message, thread_id=session_id)

            # Extract response and sources
            messages = result.get("messages", [])
            reasoning_text = ""
            gen_confidence = None
            gen_refused = False
            if messages:
                last_message = messages[-1]
                raw = last_message.content if hasattr(last_message, 'content') else str(last_message)
                answer = strip_think_tags(raw)
                # Extract Qwen3 reasoning from generate node
                if hasattr(last_message, 'additional_kwargs'):
                    reasoning_text = last_message.additional_kwargs.get('reasoning', '') or ''
                    gen_confidence = last_message.additional_kwargs.get('confidence')
                    gen_refused = bool(last_message.additional_kwargs.get('refused', False))
            else:
                answer = "抱歉，无法生成回答。"

            sources = _extract_sources(messages)
            route = "rag"
            prompt_profile = "phm_diagnosis_v1"

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

        diagnosis = _extract_phm_diagnosis(answer)

        main_meta = {
            "intent_confidence": intent_result.confidence,
            "intent_reasoning": intent_result.reasoning,
            "source_count": len(sources),
            "diagnosis": diagnosis.model_dump() if diagnosis else None,
            "route": route,
            "prompt_profile": prompt_profile,
            "force_rag": force_rag,
            "reasoning": reasoning_text,
            "message_id": message_id,
            # Answer trustworthiness (filled by the generate skill when on the
            # RAG route; None for general_chat which has no grounding signal).
            "confidence": gen_confidence,
            "confidence_level": _confidence_level(gen_confidence),
            "refused": gen_refused,
        }
        _capture(http_request, request.message, answer, sources, reasoning_text,
                 route, prompt_profile, intent_result.intent.value,
                 main_meta, processing_time, trace_id, session_id)
        return ChatResponse(
            response=answer,
            session_id=session_id,
            intent=intent_result.intent.value,
            sources=sources,
            processing_time_ms=processing_time,
            metadata=main_meta,
        )

    except Exception as e:
        log.error(f"Chat error: {e}")

        # Check if circuit breaker is open
        from core.fallback.circuit_breaker import CircuitBreakerError
        from core.fallback.degradation import get_degradation_handler

        if isinstance(e, CircuitBreakerError):
            handler = get_degradation_handler()
            degraded = handler.generate_degraded_response(request.message, str(e))
            degraded_time = (time.perf_counter() - start_time) * 1000
            degraded_meta = {"error": str(e), "message_id": message_id}
            # Degraded responses are always sampled (importance sampling).
            _capture(http_request, request.message, degraded.content, [], "",
                     "degraded", "degraded", "degraded",
                     degraded_meta, degraded_time, trace_id, session_id)
            return ChatResponse(
                response=degraded.content,
                session_id=session_id,
                intent="degraded",
                sources=[],
                processing_time_ms=degraded_time,
                metadata=degraded_meta,
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

        # Messages are stored newest-first via lpush; reverse to chronological order
        messages = list(reversed(messages))

        chat_messages = []
        for msg in messages:
            role = "user" if msg.type == "human" else "assistant"
            ts = (msg.additional_kwargs or {}).pop("_timestamp", None)
            chat_messages.append(ChatMessage(
                role=role,
                content=msg.content,
                timestamp=ts,
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
        start_time = time.perf_counter()
        try:
            # Send session info
            yield _sse({"type": "session", "session_id": session_id})

            if _is_identity_capability_query(request.message):
                answer = PHM_IDENTITY_RESPONSE
                yield _sse({"type": "intent", "intent": "general_chat", "confidence": 1.0, "route": "general_chat", "force_rag": False})
                yield _sse({"type": "status", "message": "正在返回平台能力说明..."})
                yield _sse({"type": "token", "content": answer})
                await session_memory.save_message(session_id, HumanMessage(content=request.message))
                await session_memory.save_message(session_id, AIMessage(content=answer))
                yield _sse({
                    "type": "done",
                    "full_response": answer,
                    "sources": [],
                    "processing_time_ms": (time.perf_counter() - start_time) * 1000,
                    "metadata": {
                        "intent_confidence": 1.0,
                        "intent_reasoning": "Identity/capability shortcut",
                        "source_count": 0,
                        "diagnosis": None,
                        "route": "general_chat",
                        "prompt_profile": "phm_identity_v1",
                        "force_rag": False,
                    },
                })
                return

            # Fast mode: direct retrieve + stream generate
            if request.mode == "fast":
                from core.fast_mode import fast_generate_stream

                yield _sse({"type": "intent", "intent": "rag_query", "confidence": 1.0, "route": "fast", "force_rag": False})
                yield _sse({"type": "status", "message": "正在检索知识库..."})

                full_response = ""
                sources_data = []
                async for event in fast_generate_stream(request.message):
                    if event["type"] == "token":
                        if not full_response:
                            yield _sse({"type": "node", "name": "fast_generate"})
                            yield _sse({"type": "status", "message": "正在生成回答..."})
                        full_response += event["content"]
                        yield _sse({"type": "token", "content": event["content"]})
                    elif event["type"] == "done":
                        sources_data = event.get("sources", [])

                await session_memory.save_message(session_id, HumanMessage(content=request.message))
                await session_memory.save_message(session_id, AIMessage(content=full_response))

                diagnosis = _extract_phm_diagnosis(full_response)
                yield _sse({
                    "type": "done",
                    "full_response": full_response,
                    "sources": sources_data,
                    "processing_time_ms": (time.perf_counter() - start_time) * 1000,
                    "metadata": {
                        "intent_confidence": 1.0,
                        "intent_reasoning": "Fast mode (no classification)",
                        "source_count": len(sources_data),
                        "diagnosis": diagnosis.model_dump() if diagnosis else None,
                        "route": "fast",
                        "prompt_profile": "phm_fast_v1",
                        "force_rag": False,
                    },
                })
                return

            # Step 1: Intent classification
            yield _sse({"type": "status", "message": "正在分析意图..."})

            from core.intent.classifier import get_intent_classifier
            intent_classifier = get_intent_classifier()
            intent_result = await intent_classifier.aclassify(request.message)
            use_rag = intent_result.intent.value != "general_chat"
            force_rag = False
            if not use_rag and _looks_like_phm_query(request.message):
                use_rag = True
                force_rag = True
                yield _sse({"type": "status", "message": "检测为PHM技术问题，已切换知识库诊断模式..."})

            yield _sse({
                "type": "intent",
                "intent": intent_result.intent.value,
                "confidence": intent_result.confidence,
                "route": "rag" if use_rag else "general_chat",
                "force_rag": force_rag,
            })

            # Step 2: Route based on intent
            if not use_rag:
                # Direct LLM streaming (no RAG)
                yield _sse({"type": "status", "message": "正在生成回答..."})

                from models.llm_models import get_llm
                llm = get_llm()

                # Load conversation history for multi-turn context
                history = await session_memory.get_messages(session_id)
                history = list(reversed(history))  # oldest-first

                history_msgs = [SystemMessage(content=GENERAL_CHAT_SYSTEM_PROMPT)]
                for hm in history:
                    history_msgs.append(hm)
                history_msgs.append(HumanMessage(content=request.message))

                full_response = ""
                async for chunk in llm.astream(history_msgs):
                    if hasattr(chunk, 'content') and chunk.content:
                        full_response += chunk.content
                        yield _sse({"type": "token", "content": chunk.content})

                full_response = strip_think_tags(full_response)

                # Save to session
                await session_memory.save_message(session_id, HumanMessage(content=request.message))
                await session_memory.save_message(session_id, AIMessage(content=full_response))

                diagnosis = _extract_phm_diagnosis(full_response)
                done_payload = {
                    "type": "done",
                    "full_response": full_response,
                    "sources": [],
                    "processing_time_ms": (time.perf_counter() - start_time) * 1000,
                    "metadata": {
                        "intent_confidence": intent_result.confidence,
                        "intent_reasoning": intent_result.reasoning,
                        "source_count": 0,
                        "diagnosis": diagnosis.model_dump() if diagnosis else None,
                        "route": "general_chat",
                        "prompt_profile": "phm_general_v1",
                        "force_rag": force_rag,
                    },
                }

            else:
                # RAG pipeline via graph streaming
                from agent.harness import get_agent_harness
                harness = get_agent_harness()

                full_response = ""
                collected_messages = []

                async for event in harness.astream(
                    request.message,
                    thread_id=session_id,
                    stream_mode=["updates", "custom"],
                ):
                    if (
                        isinstance(event, tuple)
                        and len(event) == 2
                        and event[0] == "custom"
                    ):
                        custom_event = event[1]
                        if custom_event.get("type") == "token":
                            token = custom_event.get("content", "")
                            if not full_response:
                                yield _sse({"type": "node", "name": "generate"})
                                yield _sse({"type": "status", "message": "正在生成回答..."})
                            full_response += token
                            yield _sse({"type": "token", "content": token})
                        continue

                    if isinstance(event, tuple) and len(event) == 2:
                        _, event = event

                    for node_name, node_output in event.items():
                        if node_name == "agent":
                            messages = node_output.get("messages", [])
                            if messages:
                                msg = messages[-1]
                                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                    yield _sse({"type": "node", "name": "retrieve"})
                                    yield _sse({"type": "status", "message": "正在检索知识库..."})
                                elif hasattr(msg, 'content') and msg.content:
                                    full_response = msg.content
                                    yield _sse({"type": "status", "message": "正在生成回答..."})
                                    yield _sse({"type": "token", "content": full_response})

                        elif node_name == "retrieve":
                            collected_messages.extend(node_output.get("messages", []))
                            yield _sse({"type": "node", "name": "grade"})
                            yield _sse({"type": "status", "message": "正在评估文档相关性..."})

                        elif node_name == "rewrite":
                            yield _sse({"type": "node", "name": "rewrite"})
                            yield _sse({"type": "status", "message": "正在优化查询..."})
                            yield _sse({"type": "node", "name": "agent"})

                        elif node_name == "generate":
                            yield _sse({"type": "node", "name": "generate"})
                            yield _sse({"type": "status", "message": "正在生成回答..."})
                            messages = node_output.get("messages", [])
                            if messages:
                                answer = strip_think_tags(messages[-1].content)
                                if not full_response:
                                    full_response = answer
                                    yield _sse({"type": "token", "content": answer})
                                elif answer.startswith(full_response):
                                    suffix = answer[len(full_response):]
                                    if suffix:
                                        full_response = answer
                                        yield _sse({"type": "token", "content": suffix})
                                else:
                                    full_response = answer

                # Save to session
                await session_memory.save_message(session_id, HumanMessage(content=request.message))
                await session_memory.save_message(session_id, AIMessage(content=full_response))

                sources = _extract_sources(collected_messages)
                diagnosis = _extract_phm_diagnosis(full_response)
                done_payload = {
                    "type": "done",
                    "full_response": full_response,
                    "sources": [s.model_dump() for s in sources],
                    "processing_time_ms": (time.perf_counter() - start_time) * 1000,
                    "metadata": {
                        "intent_confidence": intent_result.confidence,
                        "intent_reasoning": intent_result.reasoning,
                        "source_count": len(sources),
                        "diagnosis": diagnosis.model_dump() if diagnosis else None,
                        "route": "rag",
                        "prompt_profile": "phm_diagnosis_v1",
                        "force_rag": force_rag,
                    },
                }

            # Send completion signal
            yield _sse(done_payload)

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
