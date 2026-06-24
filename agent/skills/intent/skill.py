"""
Intent Skill

Wraps the existing IntentClassifier as a skill.
Classifies user intent to route queries to the appropriate handler.

Intent types:
- rag_query: needs knowledge base retrieval (thinking or fast mode)
- general_chat: general conversation (direct response)
- doc_upload: document upload request
- system_cmd: system administration
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from agent.skills.base import BaseSkill, SkillContext, SkillResult, SkillStatus
from core.intent.classifier import (
    IntentClassifier,
    IntentClassifierConfig,
    IntentResult,
    IntentType,
)
from utils.log_utils import log

__all__ = ["IntentSkill", "IntentSkillConfig"]


@dataclass
class IntentSkillConfig:
    """Configuration for IntentSkill."""

    max_retries: int = 2
    retry_delay: float = 0.5
    fallback_intent: IntentType = IntentType.RAG_QUERY


class IntentSkill(BaseSkill):
    """
    Skill that classifies user intent.

    Wraps IntentClassifier from core/intent/classifier.py:
    1. Checks keywords for fast routing (no LLM needed)
    2. Falls back to LLM-based structured classification
    3. Returns the intent as metadata for the orchestrator to route

    The orchestrator uses the intent to decide:
    - rag_query -> run full graph or fast mode
    - general_chat -> respond directly (no retrieval)
    - doc_upload -> delegate to document handler
    - system_cmd -> delegate to system handler
    """

    name = "intent"
    description = "Classify user intent for query routing"

    def __init__(
        self,
        config: IntentSkillConfig | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._skill_config = config or IntentSkillConfig()
        self._classifier = None

    @property
    def classifier(self) -> IntentClassifier:
        """Get the IntentClassifier (lazy, cached)."""
        if self._classifier is None:
            classifier_config = IntentClassifierConfig(
                max_retries=self._skill_config.max_retries,
                retry_delay=self._skill_config.retry_delay,
                fallback_intent=self._skill_config.fallback_intent,
            )
            self._classifier = IntentClassifier(
                llm=self.llm,
                config=classifier_config,
            )
        return self._classifier

    def execute(self, context: SkillContext) -> SkillResult:
        """Classify intent synchronously."""
        start = time.perf_counter()

        query = context.question
        if not query:
            # No human message found; default to rag_query
            return SkillResult(
                status=SkillStatus.PARTIAL,
                next_action="rag_query",
                metadata={"intent": "rag_query", "confidence": 0.0},
            )

        try:
            result = self.classifier.classify(query)
            elapsed = (time.perf_counter() - start) * 1000

            log.info(
                f"IntentSkill: intent={result.intent.value}, "
                f"confidence={result.confidence:.2f}, {elapsed:.0f}ms"
            )

            # Determine next action based on intent
            next_action = self._intent_to_action(result)

            return SkillResult(
                status=SkillStatus.SUCCESS,
                next_action=next_action,
                metadata={
                    "intent": result.intent.value,
                    "confidence": result.confidence,
                    "reasoning": result.reasoning,
                    "elapsed_ms": elapsed,
                },
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            log.error(f"IntentSkill failed ({elapsed:.0f}ms): {e}")

            # On failure, default to rag_query for safety
            return SkillResult(
                status=SkillStatus.PARTIAL,
                next_action="rag_query",
                error=str(e),
                metadata={
                    "intent": "rag_query",
                    "confidence": 0.0,
                    "fallback": True,
                },
            )

    async def aexecute(self, context: SkillContext) -> SkillResult:
        """Classify intent asynchronously."""
        start = time.perf_counter()

        query = context.question
        if not query:
            return SkillResult(
                status=SkillStatus.PARTIAL,
                next_action="rag_query",
                metadata={"intent": "rag_query", "confidence": 0.0},
            )

        try:
            result = await self.classifier.aclassify(query)
            elapsed = (time.perf_counter() - start) * 1000

            log.info(
                f"IntentSkill (async): intent={result.intent.value}, "
                f"confidence={result.confidence:.2f}, {elapsed:.0f}ms"
            )

            next_action = self._intent_to_action(result)

            return SkillResult(
                status=SkillStatus.SUCCESS,
                next_action=next_action,
                metadata={
                    "intent": result.intent.value,
                    "confidence": result.confidence,
                    "reasoning": result.reasoning,
                    "elapsed_ms": elapsed,
                },
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            log.error(f"IntentSkill async failed ({elapsed:.0f}ms): {e}")

            return SkillResult(
                status=SkillStatus.PARTIAL,
                next_action="rag_query",
                error=str(e),
                metadata={"intent": "rag_query", "fallback": True},
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _intent_to_action(result: IntentResult) -> str:
        """
        Map IntentResult to orchestrator action.

        Returns one of:
        - "rag_query" -> run retrieval pipeline (thinking or fast mode)
        - "general_chat" -> respond directly
        - "doc_upload" -> delegate to doc handler
        - "system_cmd" -> delegate to system handler
        """
        mapping = {
            IntentType.RAG_QUERY: "rag_query",
            IntentType.GENERAL_CHAT: "general_chat",
            IntentType.DOCUMENT_UPLOAD: "doc_upload",
            IntentType.SYSTEM_COMMAND: "system_cmd",
        }
        return mapping.get(result.intent, "rag_query")
