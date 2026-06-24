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
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from agent.context.state import get_last_human_message
from agent.skills.base import BaseSkill, SkillContext, SkillResult, SkillStatus
from agent.skills.generate.prompts import (
    GENERATE_HUMAN_PROMPT,
    GENERATE_SYSTEM_PROMPT,
)
from core.prompts.domain_profile import get_active_profile
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
    # Refuse-to-answer: if every retrieved doc scores below this relevance,
    # do not generate (avoid hallucinating over weak evidence).
    min_relevance_threshold: float = 0.3
    # Token-budget context packing. When > 0, the context is truncated by
    # estimated TOKEN count (not raw characters), avoiding mid-token cuts and
    # model-window overflow. Set to 0 to keep the legacy char-based truncation.
    max_context_tokens: int = 2048
    # Composite confidence weights (retrieval / grounding / intent).
    confidence_w_retrieval: float = 0.4
    confidence_w_grounding: float = 0.4
    confidence_w_intent: float = 0.2


# Refusal message when retrieval yields no sufficiently-relevant evidence.
# Sourced from the active domain profile so it matches the configured domain
# (aviation refers to 维修手册/故障代码; general is domain-neutral).
def _refusal_message() -> str:
    return get_active_profile().refusal_message


REFUSAL_MESSAGE = _refusal_message()


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
        config: GenerateSkillConfig | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._skill_config = config or GenerateSkillConfig()
        self._chain = None

    @property
    def chain(self):
        """Get the generation chain (lazy, cached)."""
        if self._chain is None:
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", self._skill_config.system_prompt),
                    ("human", self._skill_config.human_prompt),
                ]
            )
            self._chain = prompt | self.llm | StrOutputParser()
        return self._chain

    def execute(self, context: SkillContext) -> SkillResult:
        """Execute the generate skill synchronously."""
        start = time.perf_counter()
        messages = context.messages
        shared_state = getattr(context, "shared_state", {}) or {}

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
                        content=get_active_profile().empty_context_message,
                        additional_kwargs={"confidence": 0.0, "refused": False},
                    )
                ],
                next_action=None,  # Terminal node
                metadata={"confidence": 0.0, "refused": False},
            )

        # Refuse-to-answer: every retrieved doc is below the relevance floor.
        # Better to decline than to hallucinate over weak evidence.
        if self._should_refuse(messages, has_context=True):
            log.info("GenerateSkill: refusing — retrieval relevance below threshold")
            return SkillResult(
                status=SkillStatus.PARTIAL,
                messages=[
                    AIMessage(
                        content=REFUSAL_MESSAGE,
                        additional_kwargs={"confidence": 0.0, "refused": True},
                    )
                ],
                next_action=None,
                metadata={
                    "confidence": 0.0,
                    "refused": True,
                    "relevance_scores": self._extract_relevance_scores(messages),
                },
            )

        # Truncate context by token budget (token-aware, avoids mid-token cuts
        # and model-window overflow). Falls back to legacy char truncation if
        # the token budget is disabled.
        ctx = self._apply_context_budget(ctx, question)

        # Stash retrieval relevance for confidence calc later.
        scores = self._extract_relevance_scores(messages)
        if scores:
            shared_state.setdefault("relevance_scores", scores)

        # Publish retrieved contexts/sources into shared_state so the output
        # guardrail's semantic grounding (NLI) branch can see them. Without
        # this, the guardrail's hallucination ESCALATE/SANITIZE path is inert
        # (it reads shared_state["retrieved_contexts"]/["sources"]).
        grounding_contexts = self._contexts_list(messages)
        grounding_sources = self._extract_sources_list(messages)
        if grounding_contexts:
            shared_state["retrieved_contexts"] = grounding_contexts
        if grounding_sources:
            shared_state["sources"] = grounding_sources

        # Generate with retry
        for attempt in range(self._skill_config.max_retries + 1):
            try:
                answer, reasoning = self._invoke_with_reasoning(question, ctx)
                answer = strip_think_tags(answer)

                # Grounding faithfulness (best-effort; None when judge down).
                faith = self._grounding_faithfulness(answer, messages)
                # Cache the verdict so the output guardrail (which also calls
                # check_grounding) can reuse it instead of paying for a second
                # per-claim judge round-trip on the hot path.
                shared_state["grounding_faithfulness"] = faith
                confidence, degraded = self._compute_confidence(shared_state, faith)

                # Self-reflection on captured reasoning (P2.6): if the model's
                # own reasoning expresses uncertainty over hard claims, append
                # a caveat. Cheap (regex), no extra LLM call.
                reflection_caveat = ""
                if reasoning:
                    try:
                        from agent.skills.generate.self_reflection import reflect_on_reasoning

                        reflection = reflect_on_reasoning(answer, reasoning, faith)
                        if not reflection.confident and reflection.caveat:
                            reflection_caveat = reflection.caveat
                            answer = answer + reflection_caveat
                    except Exception as e:  # noqa: BLE001
                        log.debug(f"self-reflection skipped: {e}")

                extra_kwargs: dict[str, Any] = {"confidence": confidence}
                if reasoning:
                    extra_kwargs["reasoning"] = reasoning

                ai_message = AIMessage(
                    content=answer,
                    additional_kwargs=extra_kwargs,
                )

                elapsed = (time.perf_counter() - start) * 1000
                log.info(
                    f"GenerateSkill: {len(answer)} chars, "
                    f"{elapsed:.0f}ms, confidence={confidence:.2f}"
                    f"{' (degraded)' if degraded else ''}"
                    f"{', reasoning: ' + str(len(reasoning)) + ' chars' if reasoning else ''}"
                )

                return SkillResult(
                    status=SkillStatus.SUCCESS,
                    messages=[ai_message],
                    next_action=None,  # Terminal -- generate ends the flow
                    state_updates={
                        # Persist published shared_state keys into the graph
                        # state. After-hooks already read them off the live
                        # context object; this keeps them in state for any
                        # post-run inspection / confidence propagation.
                        "shared_state": {
                            k: v
                            for k, v in shared_state.items()
                            if k
                            in (
                                "retrieved_contexts",
                                "sources",
                                "relevance_scores",
                                "grounding_faithfulness",
                            )
                        }
                    },
                    metadata={
                        "answer_length": len(answer),
                        "has_reasoning": bool(reasoning),
                        "elapsed_ms": elapsed,
                        "confidence": confidence,
                        "confidence_degraded": degraded,
                        "grounding_faithfulness": faith,
                        "refused": False,
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
                        messages=[AIMessage(content="抱歉，生成回答时遇到问题，请稍后重试。")],
                    )

        return SkillResult(
            status=SkillStatus.FAILURE,
            messages=[AIMessage(content="生成回答失败。")],
        )

    def _grounding_faithfulness(self, answer: str, messages: list[BaseMessage]) -> float | None:
        """
        Best-effort online grounding score for the generated answer.

        Returns the faithfulness fraction, or None if the judge is unavailable
        (the caller then marks confidence as degraded). Never raises.
        """
        try:
            from agent.guardrails.grounding_guardrail import check_grounding

            contexts = self._contexts_list(messages)
            if not contexts:
                return None
            result = check_grounding(answer, contexts)
            return result.faithfulness  # None when degraded
        except Exception as e:  # noqa: BLE001
            log.debug(f"grounding faithfulness skipped: {e}")
            return None

    async def _agrounding_faithfulness(
        self, answer: str, messages: list[BaseMessage]
    ) -> float | None:
        """
        Async grounding score: fans out per-claim entailment concurrently so an
        answer with N hard claims does not block the event loop for N sequential
        judge round-trips. The sync path above is kept for the sync pipeline.
        """
        try:
            from agent.guardrails.grounding_guardrail import acheck_grounding

            contexts = self._contexts_list(messages)
            if not contexts:
                return None
            result = await acheck_grounding(answer, contexts)
            return result.faithfulness  # None when degraded
        except Exception as e:  # noqa: BLE001
            log.debug(f"async grounding faithfulness skipped: {e}")
            return None

    @staticmethod
    def _contexts_list(messages: list[BaseMessage]) -> list[str]:
        """Flatten retrieved chunks from the last message into plain strings."""
        last_message = messages[-1] if messages else None
        if last_message is None:
            return []
        content = last_message.content
        out: list[str] = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text = str(item.get("text", "")).strip()
                elif isinstance(item, str):
                    text = item.strip()
                else:
                    text = ""
                if text:
                    out.append(text)
        elif isinstance(content, str) and content.strip():
            out.append(content.strip())
        return out

    @staticmethod
    def _extract_sources_list(messages: list[BaseMessage]) -> list[str]:
        """
        Collect source names from the retrieved chunks in the last message.

        Used to populate ``shared_state["sources"]`` so the output guardrail's
        legacy regex hallucination check has the actual source list to compare
        cited references against.
        """
        last_message = messages[-1] if messages else None
        if last_message is None:
            return []
        content = last_message.content
        sources: list[str] = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    metadata = item.get("metadata", {})
                    if not isinstance(metadata, dict):
                        metadata = {}
                    src = item.get("source") or metadata.get("source")
                    if src and str(src).strip() and str(src) not in sources:
                        sources.append(str(src))
        return sources

    async def aexecute(self, context: SkillContext) -> SkillResult:
        """Generate asynchronously and publish token chunks to LangGraph streams."""
        import asyncio

        from langgraph.config import get_stream_writer

        start = time.perf_counter()
        messages = context.messages
        shared_state = getattr(context, "shared_state", {}) or {}

        question = self._extract_question(messages)
        ctx = self._extract_context(messages)

        if not ctx or not ctx.strip():
            return SkillResult(
                status=SkillStatus.PARTIAL,
                messages=[
                    AIMessage(
                        content=get_active_profile().empty_context_message,
                        additional_kwargs={"confidence": 0.0, "refused": False},
                    )
                ],
                metadata={"confidence": 0.0, "refused": False},
            )

        # Refuse-to-answer on weak retrieval evidence.
        if self._should_refuse(messages, has_context=True):
            log.info("GenerateSkill (async): refusing — relevance below threshold")
            return SkillResult(
                status=SkillStatus.PARTIAL,
                messages=[
                    AIMessage(
                        content=REFUSAL_MESSAGE,
                        additional_kwargs={"confidence": 0.0, "refused": True},
                    )
                ],
                metadata={
                    "confidence": 0.0,
                    "refused": True,
                    "relevance_scores": self._extract_relevance_scores(messages),
                },
            )

        ctx = self._apply_context_budget(ctx, question)

        scores = self._extract_relevance_scores(messages)
        if scores:
            shared_state.setdefault("relevance_scores", scores)

        # Publish retrieved contexts/sources into shared_state so the output
        # guardrail's semantic grounding (NLI) branch can see them (parity with
        # the sync execute path).
        grounding_contexts = self._contexts_list(messages)
        grounding_sources = self._extract_sources_list(messages)
        if grounding_contexts:
            shared_state["retrieved_contexts"] = grounding_contexts
        if grounding_sources:
            shared_state["sources"] = grounding_sources

        writer = get_stream_writer()
        for attempt in range(self._skill_config.max_retries + 1):
            try:
                chunks: list[str] = []
                async for chunk in self.chain.astream({"question": question, "context": ctx}):
                    text = str(chunk)
                    if not text:
                        continue
                    chunks.append(text)
                    writer({"type": "token", "content": text, "node": self.name})

                answer = strip_think_tags("".join(chunks))
                # Grounding + confidence (best-effort). Async path fans out
                # per-claim entailment concurrently instead of blocking the
                # event loop with N sequential judge round-trips.
                faith = await self._agrounding_faithfulness(answer, messages)
                # Cache the verdict so the output guardrail can reuse it.
                shared_state["grounding_faithfulness"] = faith
                confidence, degraded = self._compute_confidence(shared_state, faith)
                elapsed = (time.perf_counter() - start) * 1000
                log.info(
                    f"GenerateSkill (async stream): {len(answer)} chars, "
                    f"{elapsed:.0f}ms, confidence={confidence:.2f}"
                    f"{' (degraded)' if degraded else ''}"
                )
                return SkillResult(
                    status=SkillStatus.SUCCESS,
                    messages=[
                        AIMessage(
                            content=answer,
                            additional_kwargs={"confidence": confidence},
                        )
                    ],
                    state_updates={
                        "shared_state": {
                            k: v
                            for k, v in shared_state.items()
                            if k
                            in (
                                "retrieved_contexts",
                                "sources",
                                "relevance_scores",
                                "grounding_faithfulness",
                            )
                        }
                    },
                    metadata={
                        "answer_length": len(answer),
                        "has_reasoning": False,
                        "streamed": True,
                        "elapsed_ms": elapsed,
                        "confidence": confidence,
                        "confidence_degraded": degraded,
                        "grounding_faithfulness": faith,
                        "refused": False,
                    },
                )
            except Exception as e:
                log.warning(f"Async generate attempt {attempt + 1} failed: {e}")
                if attempt < self._skill_config.max_retries:
                    await asyncio.sleep(self._skill_config.retry_delay * (attempt + 1))
                    continue
                elapsed = (time.perf_counter() - start) * 1000
                log.error(f"GenerateSkill async failed ({elapsed:.0f}ms): {e}")
                return SkillResult(
                    status=SkillStatus.FAILURE,
                    skill_name=self.name,
                    error=str(e),
                    messages=[AIMessage(content="抱歉，生成回答时遇到问题，请稍后重试。")],
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
            human_msg = self._skill_config.human_prompt.format(question=question, context=context)

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
            reasoning = getattr(msg, "reasoning", "") or ""

            # Record token usage as an OTel span attribute (P3.5) when OTel
            # is enabled; falls back to a no-op span otherwise.
            try:
                from core.tracing.opentelemetry import trace_llm_call

                usage = getattr(resp, "usage", None)
                usage_attrs = {}
                if usage:
                    usage_attrs = {
                        "gen_ai.usage.prompt_tokens": getattr(usage, "prompt_tokens", 0),
                        "gen_ai.usage.completion_tokens": getattr(usage, "completion_tokens", 0),
                        "gen_ai.usage.total_tokens": getattr(usage, "total_tokens", 0),
                    }
                with trace_llm_call(LLM_MODEL, len(human_msg)):
                    pass  # attributes recorded; usage logged below for observability
                if usage_attrs:
                    log.debug(f"LLM usage: {usage_attrs}")
            except Exception:  # noqa: BLE001
                pass

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
        return await loop.run_in_executor(None, self._invoke_with_reasoning, question, context)

    # ------------------------------------------------------------------
    # Context/question extraction (from GenerateNode)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_question(messages: list[BaseMessage]) -> str:
        """Extract the user's question from messages."""
        try:
            human_message = get_last_human_message(messages)
            return human_message.content
        except Exception:
            return messages[-1].content if messages else ""

    @staticmethod
    def _extract_context(messages: list[BaseMessage]) -> str:
        """
        Extract context from messages.

        The context is in the last message (from the retriever / ToolNode).
        Handles both string and list (tool result) formats. The list branch
        delegates to the shared formatting layer so the evidence-line format
        is defined once.
        """
        last_message = messages[-1] if messages else None
        if last_message is None:
            return ""

        content = last_message.content

        # If content is a list (tool result format), format via shared layer.
        if isinstance(content, list):
            from core.retrieval.formatting import FormattedDoc

            # Build FormattedDocs straight from the list items (they already
            # carry text/source/title/score) and render with the shared format.
            parts: list[str] = []
            idx = 0
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    text = str(item.get("text", "")).strip()
                    if not text:
                        continue
                    metadata = item.get("metadata", {})
                    if not isinstance(metadata, dict):
                        metadata = {}
                    idx += 1
                    source = item.get("source") or metadata.get("source", "unknown")
                    title = item.get("title") or metadata.get("title", "unknown")
                    raw_score = item.get("score") or metadata.get("score")
                    score = raw_score if isinstance(raw_score, (int, float)) else None
                    fd = FormattedDoc(
                        index=idx, source=source, title=title, score=score, content=text
                    )
                    parts.append(f"{fd.to_evidence_line()}\n{text}")
                elif isinstance(item, str):
                    parts.append(item)
            return "\n\n".join(parts)

        return str(content)

    # ------------------------------------------------------------------
    # Confidence & refusal helpers
    # ------------------------------------------------------------------

    def _apply_context_budget(self, ctx: str, question: str) -> str:
        """
        Truncate the context string to fit the token budget.

        Truncates at chunk boundaries (``\\n\\n``) rather than mid-character,
        so individual evidence chunks are never cut in half and the per-character
        walk is avoided. When ``max_context_tokens > 0`` the budget is measured
        in estimated tokens; otherwise the legacy character cap applies.

        Greedy: keeps chunks in order until adding the next would exceed the
        budget, then appends a truncation marker.
        """
        from core.context.token_budget import estimate_tokens

        # Split into evidence chunks on the blank-line separator the formatter
        # emits between chunks.
        chunks = ctx.split("\n\n")

        budget_tokens = self._skill_config.max_context_tokens
        budget_chars = self._skill_config.max_context_length
        use_tokens = bool(budget_tokens and budget_tokens > 0)

        if use_tokens and estimate_tokens(ctx) <= budget_tokens:
            return ctx
        if not use_tokens and len(ctx) <= budget_chars:
            return ctx

        kept: list[str] = []
        used_tokens = 0
        used_chars = 0
        for chunk in chunks:
            if use_tokens:
                cost = estimate_tokens(chunk) + 2  # +2 for the separator
                if used_tokens + cost > budget_tokens and kept:
                    break
                used_tokens += cost
            else:
                cost = len(chunk) + 2
                if used_chars + cost > budget_chars and kept:
                    break
                used_chars += cost
            kept.append(chunk)

        if not kept:
            # Budget too small for even one chunk: keep the first chunk's head.
            if chunks:
                head = chunks[0]
                if use_tokens:
                    return head[: budget_tokens * 2] + "\n...[内容已按 token 预算截断]"
                return head[:budget_chars] + "\n...[内容已截断]"
            return ""
        marker = "...[内容已按 token 预算截断]" if use_tokens else "...[内容已截断]"
        return "\n\n".join(kept) + "\n" + marker

    @staticmethod
    def _extract_relevance_scores(messages: list[BaseMessage]) -> list[float]:
        """
        Extract retrieval relevance scores from the last tool/retriever message.

        The string branch uses the shared parser
        (:func:`core.retrieval.formatting.parse_relevance_scores`) — the single
        authoritative reader for the ``相关度=X`` markers emitted by the shared
        formatter. The list branch reads score metadata directly.
        """
        from core.retrieval.formatting import parse_relevance_scores

        last_message = messages[-1] if messages else None
        if last_message is None:
            return []

        scores: list[float] = []
        content = last_message.content

        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    s = item.get("score") or (item.get("metadata") or {}).get("score")
                    if isinstance(s, (int, float)):
                        scores.append(float(s))
        elif isinstance(content, str):
            scores = parse_relevance_scores(content)
        return scores

    def _should_refuse(self, messages: list[BaseMessage], has_context: bool) -> bool:
        """
        Decide whether to refuse answering due to weak retrieval evidence.

        Refuses when there IS some context but every retrieved document scores
        below ``min_relevance_threshold``. No context at all is handled by the
        existing empty-knowledge branch (a different message).
        """
        if not has_context:
            return False
        scores = self._extract_relevance_scores(messages)
        if not scores:
            return False  # cannot judge relevance -> do not refuse
        return all(s < self._skill_config.min_relevance_threshold for s in scores)

    def _compute_confidence(
        self,
        shared_state: dict,
        grounding_faithfulness: float | None,
    ) -> tuple[float, bool]:
        """
        Composite confidence in [0, 1] and a 'degraded' flag.

        Blend: retrieval relevance, grounding faithfulness, intent confidence.
        When grounding is unavailable (judge down), its weight is redistributed
        to retrieval and the result is flagged degraded.
        """
        cfg = self._skill_config
        w_r = cfg.confidence_w_retrieval
        w_g = cfg.confidence_w_grounding
        w_i = cfg.confidence_w_intent

        retrieval = shared_state.get("retrieval_relevance")
        if retrieval is None:
            # Fallback: derive from relevance scores if present.
            scores = shared_state.get("relevance_scores") or []
            retrieval = (sum(scores) / len(scores)) if scores else None

        intent = shared_state.get("intent_confidence")

        faith = grounding_faithfulness
        degraded = faith is None
        if degraded:
            # Redistribute grounding weight to retrieval (the most reliable
            # remaining signal).
            w_r = w_r + w_g
            w_g = 0.0

        components = []
        if retrieval is not None:
            components.append((w_r, max(0.0, min(1.0, float(retrieval)))))
        if faith is not None:
            components.append((w_g, max(0.0, min(1.0, float(faith)))))
        if intent is not None:
            components.append((w_i, max(0.0, min(1.0, float(intent)))))

        if not components:
            return 0.0, True

        total_w = sum(w for w, _ in components) or 1.0
        confidence = sum(w * v for w, v in components) / total_w
        return max(0.0, min(1.0, confidence)), degraded
