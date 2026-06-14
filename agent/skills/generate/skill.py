"""
Generate Skill

Wraps the existing GenerateNode logic as a skill.
Produces the final answer based on retrieved documents and the question.

Preserves Qwen3 thinking mode:
- Captures the `reasoning` field from OpenAI SDK responses
- Strips <think...> tags defensively
- Falls back to LangChain if direct OpenAI call fails
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from agent.skills.base import BaseSkill, SkillContext, SkillResult, SkillStatus
from agent.context.state import get_last_human_message
from agent.skills.generate.prompts import (
    GENERATE_SYSTEM_PROMPT,
    GENERATE_HUMAN_PROMPT,
)
from utils.log_utils import log
from utils.think_tag_utils import strip_think_tags

__all__ = ["GenerateSkill", "GenerateSkillConfig"]


@dataclass
class GenerateSkillConfig:
    """Configuration for GenerateSkill."""
    max_retries: int = 2
    retry_delay: float = 1.0
    max_context_length: int = 2500
    system_prompt: str = GENERATE_SYSTEM_PROMPT
    human_prompt: str = GENERATE_HUMAN_PROMPT


class GenerateSkill(BaseSkill):
    """
    Skill that generates the final answer.

    Wraps GenerateNode from graph/generate_node.py:
    1. Extracts the question from messages
    2. Extracts context (retrieved documents) from the last message
    3. Generates an answer using the LLM
    4. Captures Qwen3 reasoning via direct OpenAI SDK call
    5. Returns the answer as an AIMessage
    """

    name = "generate"
    description = "Generate the final answer based on retrieved documents"

    def __init__(
        self,
        config: Optional[GenerateSkillConfig] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._skill_config = config or GenerateSkillConfig()
        self._chain = None

    @property
    def chain(self):
        """Get the generation chain (lazy, cached)."""
        if self._chain is None:
            prompt = ChatPromptTemplate.from_messages([
                ("system", self._skill_config.system_prompt),
                ("human", self._skill_config.human_prompt),
            ])
            self._chain = prompt | self.llm | StrOutputParser()
        return self._chain

    def execute(self, context: SkillContext) -> SkillResult:
        """Execute the generate skill synchronously."""
        start = time.perf_counter()
        messages = context.messages

        log.info("GenerateSkill: generating final answer")

        # Extract question and context
        question = self._extract_question(messages)
        ctx = self._extract_context(messages)

        # If no context, return empty-knowledge message
        if not ctx or not ctx.strip():
            return SkillResult(
                status=SkillStatus.PARTIAL,
                messages=[
                    AIMessage(
                        content=(
                            "当前知识库中暂无相关文档。请先通过文档管理页面上传"
                            "排故手册、维修手册等资料，然后再进行提问。"
                        )
                    )
                ],
                next_action=None,  # Terminal node
            )

        # Truncate context if needed
        if len(ctx) > self._skill_config.max_context_length:
            ctx = ctx[:self._skill_config.max_context_length] + "\n...[内容已截断]"

        # Generate with retry
        for attempt in range(self._skill_config.max_retries + 1):
            try:
                answer, reasoning = self._invoke_with_reasoning(question, ctx)
                answer = strip_think_tags(answer)

                ai_message = AIMessage(
                    content=answer,
                    additional_kwargs={"reasoning": reasoning} if reasoning else {},
                )

                elapsed = (time.perf_counter() - start) * 1000
                log.info(
                    f"GenerateSkill: {len(answer)} chars, "
                    f"{elapsed:.0f}ms"
                    f"{', reasoning: ' + str(len(reasoning)) + ' chars' if reasoning else ''}"
                )

                return SkillResult(
                    status=SkillStatus.SUCCESS,
                    messages=[ai_message],
                    next_action=None,  # Terminal -- generate ends the flow
                    metadata={
                        "answer_length": len(answer),
                        "has_reasoning": bool(reasoning),
                        "elapsed_ms": elapsed,
                    },
                )

            except Exception as e:
                log.warning(f"Generate attempt {attempt + 1} failed: {e}")
                if attempt < self._skill_config.max_retries:
                    time.sleep(self._skill_config.retry_delay * (attempt + 1))
                else:
                    return SkillResult(
                        status=SkillStatus.FAILURE,
                        skill_name=self.name,
                        error=str(e),
                        messages=[
                            AIMessage(content="抱歉，生成回答时遇到问题，请稍后重试。")
                        ],
                    )

        return SkillResult(
            status=SkillStatus.FAILURE,
            messages=[AIMessage(content="生成回答失败。")],
        )

    async def aexecute(self, context: SkillContext) -> SkillResult:
        """Generate asynchronously and publish token chunks to LangGraph streams."""
        import asyncio
        from langgraph.config import get_stream_writer

        start = time.perf_counter()
        messages = context.messages

        question = self._extract_question(messages)
        ctx = self._extract_context(messages)

        if not ctx or not ctx.strip():
            return SkillResult(
                status=SkillStatus.PARTIAL,
                messages=[
                    AIMessage(
                        content=(
                            "当前知识库中暂无相关文档。请先通过文档管理页面上传"
                            "排故手册、维修手册等资料，然后再进行提问。"
                        )
                    )
                ],
            )

        if len(ctx) > self._skill_config.max_context_length:
            ctx = ctx[:self._skill_config.max_context_length] + "\n...[内容已截断]"

        writer = get_stream_writer()
        for attempt in range(self._skill_config.max_retries + 1):
            try:
                chunks: list[str] = []
                async for chunk in self.chain.astream(
                    {"question": question, "context": ctx}
                ):
                    text = str(chunk)
                    if not text:
                        continue
                    chunks.append(text)
                    writer({"type": "token", "content": text, "node": self.name})

                answer = strip_think_tags("".join(chunks))
                elapsed = (time.perf_counter() - start) * 1000
                log.info(
                    f"GenerateSkill (async stream): {len(answer)} chars, "
                    f"{elapsed:.0f}ms"
                )
                return SkillResult(
                    status=SkillStatus.SUCCESS,
                    messages=[AIMessage(content=answer)],
                    metadata={
                        "answer_length": len(answer),
                        "has_reasoning": False,
                        "streamed": True,
                        "elapsed_ms": elapsed,
                    },
                )
            except Exception as e:
                log.warning(f"Async generate attempt {attempt + 1} failed: {e}")
                if attempt < self._skill_config.max_retries:
                    await asyncio.sleep(
                        self._skill_config.retry_delay * (attempt + 1)
                    )
                    continue
                elapsed = (time.perf_counter() - start) * 1000
                log.error(f"GenerateSkill async failed ({elapsed:.0f}ms): {e}")
                return SkillResult(
                    status=SkillStatus.FAILURE,
                    skill_name=self.name,
                    error=str(e),
                    messages=[
                        AIMessage(content="抱歉，生成回答时遇到问题，请稍后重试。")
                    ],
                )

    # ------------------------------------------------------------------
    # Qwen3 reasoning capture (from GenerateNode._invoke_with_reasoning)
    # ------------------------------------------------------------------

    def _invoke_with_reasoning(self, question: str, context: str) -> tuple:
        """
        Invoke LLM via OpenAI SDK to capture Qwen3 reasoning field.

        Returns (content, reasoning) tuple.
        """
        try:
            from openai import OpenAI
            from utils.env_utils import (
                LLM_MAX_TOKENS,
                LLM_MODEL,
                LLM_TEMPERATURE,
                LLM_TIMEOUT,
                OPENAI_API_KEY,
                OPENAI_BASE_URL,
            )

            client = OpenAI(
                base_url=OPENAI_BASE_URL or "http://localhost:11434/v1",
                api_key=OPENAI_API_KEY or "ollama",
            )

            system_msg = self._skill_config.system_prompt
            human_msg = self._skill_config.human_prompt.format(
                question=question, context=context
            )

            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": human_msg},
                ],
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
                timeout=LLM_TIMEOUT,
            )

            msg = resp.choices[0].message
            content = msg.content or ""
            reasoning = getattr(msg, 'reasoning', '') or ''
            return content, reasoning

        except Exception as e:
            log.warning(f"Direct OpenAI call failed, falling back to LangChain: {e}")
            answer = self.chain.invoke({"question": question, "context": context})
            return answer, ""

    async def _ainvoke_with_reasoning(self, question: str, context: str) -> tuple:
        """
        Async version of reasoning capture.

        Uses the sync version in a thread executor since the OpenAI
        sync client doesn't have native async.
        """
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._invoke_with_reasoning, question, context
        )

    # ------------------------------------------------------------------
    # Context/question extraction (from GenerateNode)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_question(messages: List[BaseMessage]) -> str:
        """Extract the user's question from messages."""
        try:
            human_message = get_last_human_message(messages)
            return human_message.content
        except Exception:
            return messages[-1].content if messages else ""

    @staticmethod
    def _extract_context(messages: List[BaseMessage]) -> str:
        """
        Extract context from messages.

        The context is in the last message (from the retriever / ToolNode).
        Handles both string and list (tool result) formats.
        """
        last_message = messages[-1] if messages else None
        if last_message is None:
            return ""

        content = last_message.content

        # If content is a list (tool result format), extract text
        if isinstance(content, list):
            text_parts = []
            for idx, item in enumerate(content, 1):
                if isinstance(item, dict) and "text" in item:
                    text = str(item.get("text", "")).strip()
                    if not text:
                        continue
                    metadata = item.get("metadata", {})
                    if not isinstance(metadata, dict):
                        metadata = {}
                    source = item.get("source") or metadata.get("source", "unknown")
                    title = item.get("title") or metadata.get("title", "unknown")
                    score = item.get("score") or metadata.get("score")
                    score_text = (
                        f"{float(score):.4f}"
                        if isinstance(score, (int, float))
                        else "N/A"
                    )
                    text_parts.append(
                        f"[证据{idx}] 来源={source} | "
                        f"标题={title} | 相关度={score_text}\n{text}"
                    )
                elif isinstance(item, str):
                    text_parts.append(item)
            return "\n\n".join(text_parts)

        return str(content)
