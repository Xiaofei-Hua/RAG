"""
Chat Router for Enterprise RAG Platform

Handles conversation/chat endpoints.
"""

from __future__ import annotations

import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
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
# Helper Functions for RAG Pipeline
# =============================================================================

async def _do_rewrite(llm, original_question: str, rewrite_count: int, yield_func=None):
    """
    执行查询重写

    Args:
        llm: 语言模型实例
        original_question: 原始问题
        rewrite_count: 当前重写次数
        yield_func: 用于发送 SSE 事件的函数

    Returns:
        (new_rewrite_count, rewritten_question)
    """
    from langchain_core.prompts import ChatPromptTemplate

    rewrite_prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一个查询优化专家。用户的问题可能表述不够清晰，请将其改写为更精确、更容易检索的形式。

要求：
1. 保持问题的核心意图不变
2. 使用更专业的术语
3. 增加必要的上下文信息
4. 只输出改写后的问题，不要解释"""),
        ("human", "请优化以下问题：{question}")
    ])

    rewrite_chain = rewrite_prompt | llm

    try:
        rewritten = rewrite_chain.invoke({"question": original_question})
        rewritten_question = rewritten.content if hasattr(rewritten, 'content') else str(rewritten)

        log.info(f"查询重写完成 ({rewrite_count + 1}): '{original_question[:30]}...' -> '{rewritten_question[:30]}...'")

        return rewrite_count + 1, rewritten_question

    except Exception as e:
        log.warning(f"查询重写失败: {e}")
        # 重写失败，返回原始问题
        return rewrite_count + 1, original_question


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

            # Extract response
            messages = result.get("messages", [])
            if messages:
                last_message = messages[-1]
                answer = last_message.content if hasattr(last_message, 'content') else str(last_message)
            else:
                answer = "抱歉，无法生成回答。"

            sources = []  # TODO: Extract sources from result

        # Calculate processing time
        processing_time = (time.perf_counter() - start_time) * 1000

        # Save to session memory (background task)
        from langchain_core.messages import HumanMessage, AIMessage
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
    """
    Get chat history for a session.

    Args:
        session_id: Session identifier
        limit: Maximum number of messages to return
    """
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
    Streaming chat endpoint.

    Returns response as a stream of chunks with progress events.
    Supports token-level streaming for better UX.
    """
    from fastapi.responses import StreamingResponse
    import json

    session_id = request.session_id or str(uuid.uuid4())

    async def generate():
        try:
            # Send session info
            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

            # Step 1: Intent classification
            yield f"data: {json.dumps({'type': 'status', 'message': '正在分析意图...'})}\n\n"

            from core.intent.classifier import get_intent_classifier
            intent_classifier = get_intent_classifier()
            intent_result = await intent_classifier.aclassify(request.message)

            yield f"data: {json.dumps({'type': 'intent', 'intent': intent_result.intent.value, 'confidence': intent_result.confidence})}\n\n"

            # Step 2: Route based on intent
            if intent_result.intent.value == "general_chat":
                # Direct LLM streaming
                yield f"data: {json.dumps({'type': 'status', 'message': '正在生成回答...'})}\n\n"

                from models.llm_models import get_llm
                llm = get_llm()

                # Stream tokens
                full_response = ""
                async for chunk in llm.astream(request.message):
                    if hasattr(chunk, 'content') and chunk.content:
                        full_response += chunk.content
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"

                # Save to session
                from langchain_core.messages import HumanMessage, AIMessage
                await session_memory.save_message(session_id, HumanMessage(content=request.message))
                await session_memory.save_message(session_id, AIMessage(content=full_response))

            else:
                # RAG pipeline with streaming - 完整流程包含评估和重写
                from tools.retriever_tools import get_retriever_manager
                from models.llm_models import get_llm
                from langchain_core.messages import HumanMessage, AIMessage
                from langchain_core.prompts import ChatPromptTemplate
                from pydantic import BaseModel, Field

                # 文档评估结果模型
                class GradeResult(BaseModel):
                    is_relevant: bool = Field(description="文档是否与问题相关")
                    reasoning: str = Field(default="", description="判断理由")

                llm = get_llm()
                retriever_manager = get_retriever_manager()

                # 状态跟踪
                current_question = request.message
                rewrite_count = 0
                max_rewrites = 3
                context = ""
                docs = []

                # RAG 循环：检索 → 评估 → 重写（如果需要）
                while rewrite_count <= max_rewrites:
                    # 检索阶段
                    yield f"data: {json.dumps({'type': 'status', 'message': f'正在检索知识库... (尝试 {rewrite_count + 1}/{max_rewrites + 1})'})}\n\n"
                    yield f"data: {json.dumps({'type': 'node', 'name': 'retrieve'})}\n\n"

                    docs = retriever_manager.search(current_question)
                    log.info(f"RAG检索完成: 找到 {len(docs)} 个文档, 查询: {current_question[:50]}...")

                    if not docs:
                        # 没有找到文档，检查是否需要重写
                        if rewrite_count < max_rewrites:
                            yield f"data: {json.dumps({'type': 'status', 'message': '未找到相关文档，尝试优化查询...'})}\n\n"
                            # 重写查询
                            rewrite_count, current_question = await _do_rewrite(
                                llm, current_question, rewrite_count
                            )
                            continue
                        else:
                            yield f"data: {json.dumps({'type': 'status', 'message': '未找到相关文档，将基于通用知识回答...'})}\n\n"
                            context = ""
                            break

                    # 构建上下文
                    context = "\n\n".join([
                        f"[文档{i+1}] {doc.page_content}"
                        for i, doc in enumerate(docs[:4])
                    ])
                    yield f"data: {json.dumps({'type': 'status', 'message': f'找到 {len(docs)} 个文档，正在评估相关性...'})}\n\n"

                    # 文档评估阶段
                    yield f"data: {json.dumps({'type': 'node', 'name': 'grade'})}\n\n"

                    grade_prompt = ChatPromptTemplate.from_messages([
                        ("system", """你是一个文档相关性评估专家。判断提供的文档是否能够回答用户的问题。
只需要回答 "是" 或 "否"，并简要说明理由。"""),
                        ("human", """问题：{question}

文档内容：
{context}

请判断这些文档是否能够回答上述问题。""")
                    ])

                    grade_chain = grade_prompt | llm.with_structured_output(GradeResult)

                    try:
                        grade_result = grade_chain.invoke({
                            "question": current_question,
                            "context": context[:2000]  # 限制长度
                        })
                        log.info(f"文档评估结果: 相关={grade_result.is_relevant}, 理由={grade_result.reasoning[:50]}...")

                        if grade_result.is_relevant:
                            yield f"data: {json.dumps({'type': 'status', 'message': '文档评估通过，开始生成回答...'})}\n\n"
                            break  # 文档相关，跳出循环进入生成
                        else:
                            # 文档不相关，检查是否需要重写
                            if rewrite_count < max_rewrites:
                                yield f"data: {json.dumps({'type': 'status', 'message': f'文档相关性不足，正在优化查询 ({rewrite_count + 1}/{max_rewrites})...'})}\n\n"

                                # 重写查询
                                rewrite_count, current_question = await _do_rewrite(
                                    llm, current_question, rewrite_count
                                )
                                continue
                            else:
                                yield f"data: {json.dumps({'type': 'status', 'message': '已达到最大重写次数，将基于当前文档生成回答...'})}\n\n"
                                break

                    except Exception as grade_error:
                        log.warning(f"文档评估失败: {grade_error}")
                        # 评估失败，假设文档相关继续生成
                        break

                # 流式生成回答
                yield f"data: {json.dumps({'type': 'status', 'message': '正在生成回答...'})}\n\n"
                yield f"data: {json.dumps({'type': 'node', 'name': 'generate'})}\n\n"

                generate_prompt = ChatPromptTemplate.from_messages([
                    ("system", """你是一个专业的问答助手，专门回答关于半导体和芯片的问题。

请根据提供的上下文内容回答用户的问题。要求：
1. 回答准确、简洁、专业
2. 如果上下文中没有相关信息，请明确说明
3. 引用上下文中的具体内容时，可以指出来源
4. 避免添加未经证实的信息"""),
                    ("human", """基于以下上下文回答问题：

上下文：
{context}

问题：{question}

请提供准确、简洁的回答：""")
                ])

                chain = generate_prompt | llm

                # 流式生成
                full_response = ""
                try:
                    async for chunk in chain.astream({
                        "context": context,
                        "question": current_question
                    }):
                        content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                        if content:
                            full_response += content
                            yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"

                    log.info(f"流式生成完成: {len(full_response)} 字符")
                except Exception as stream_error:
                    log.error(f"流式生成错误: {stream_error}")
                    import traceback
                    traceback.print_exc()
                    yield f"data: {json.dumps({'type': 'error', 'message': str(stream_error)})}\n\n"
                    return

                # Save to session
                await session_memory.save_message(session_id, HumanMessage(content=request.message))
                await session_memory.save_message(session_id, AIMessage(content=full_response))

            # Send completion signal
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            log.error(f"Stream error: {e}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.post("/stream-simple")
async def chat_stream_simple(request: ChatRequest):
    """
    Simple streaming endpoint for direct LLM token streaming.
    Best for general chat without RAG retrieval.
    """
    from fastapi.responses import StreamingResponse
    import json

    session_id = request.session_id or str(uuid.uuid4())

    async def generate():
        try:
            from models.llm_models import get_llm
            llm = get_llm()

            yield f"data: {json.dumps({'type': 'start', 'session_id': session_id})}\n\n"

            full_response = ""
            async for chunk in llm.astream(request.message):
                if hasattr(chunk, 'content') and chunk.content:
                    full_response += chunk.content
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'full_response': full_response})}\n\n"

        except Exception as e:
            log.error(f"Stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )