"""
Intent Classifier for Enterprise RAG Platform

Classifies user intent to route queries to appropriate handlers.
Uses LLM-based structured output for accurate classification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from utils.log_utils import log


class IntentType(str, Enum):
    """User intent classification types."""
    RAG_QUERY = "rag_query"           # Requires knowledge base retrieval
    GENERAL_CHAT = "general_chat"     # General conversation
    DOCUMENT_UPLOAD = "doc_upload"    # Document upload request
    SYSTEM_COMMAND = "system_cmd"     # System administration


class IntentResult(BaseModel):
    """Structured intent classification result."""
    intent: IntentType = Field(
        description="Classified intent type"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Classification confidence (0-1)"
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="Brief explanation of the classification"
    )
    suggested_action: Optional[str] = Field(
        default=None,
        description="Suggested next action based on intent"
    )

    @property
    def needs_retrieval(self) -> bool:
        """Check if this intent requires retrieval."""
        return self.intent == IntentType.RAG_QUERY


# Classification prompt
from core.prompts.aircraft_prompts import INTENT_CLASSIFICATION_PROMPT


@dataclass
class IntentClassifierConfig:
    """Configuration for IntentClassifier."""
    max_retries: int = 2
    retry_delay: float = 0.5
    timeout: float = 10.0
    fallback_intent: IntentType = IntentType.RAG_QUERY


class IntentClassifier:
    """
    LLM-based intent classifier for user queries.

    Features:
    - Structured output for reliable classification
    - Retry logic for robustness
    - Fallback to default intent on failure
    - Confidence scoring
    """

    def __init__(
        self,
        llm: BaseChatModel,
        config: Optional[IntentClassifierConfig] = None,
    ):
        """
        Initialize the intent classifier.

        Args:
            llm: Language model for classification
            config: Classifier configuration
        """
        self.llm = llm
        self.config = config or IntentClassifierConfig()
        self._chain = None

        log.debug("IntentClassifier initialized")

    @property
    def chain(self):
        """Get the classification chain (lazy initialization)."""
        if self._chain is None:
            prompt = ChatPromptTemplate.from_template(INTENT_CLASSIFICATION_PROMPT)
            structured_llm = self.llm.with_structured_output(IntentResult)
            self._chain = prompt | structured_llm
        return self._chain

    # Keyword patterns for fast intent routing (skip LLM)
    _RAG_KEYWORDS = frozenset([
        "故障", "排故", "诊断", "维修", "机务", "航材", "工卡", "手册", "告警",
        "故障码", "振动", "液压", "发动机", "航电", "超限", "温度", "压力",
        "起落架", "飞控", "空调", "供电", "燃油", "润滑", "密封", "腐蚀",
        "寿命", "磨损", "裂纹", "泄漏", "异常", "失效", "损伤", "磨损",
        "检查", "更换", "测试", "排故", "ATA", "ATA章节", "MEL", "工卡",
        "预测性维护", "健康管理", "状态监测", "趋势", "传感器", "阈值",
        "排查", "原因", "处理", "如何", "怎么", "什么", "为什么", "哪些",
        "标准", "参数", "规定", "要求", "程序", "步骤", "流程",
        "troubleshoot", "fault", "maintenance", "inspection",
    ])

    _CHAT_KEYWORDS = frozenset([
        "你好", "谢谢", "再见", "你是谁", "你能做什么", "帮我",
        "hello", "hi", "thanks", "bye",
    ])

    def _keyword_classify(self, query: str) -> Optional[IntentResult]:
        """Classify intent via keywords. Returns None if uncertain (fall through to LLM)."""
        text = query.lower()
        if any(kw in text for kw in self._RAG_KEYWORDS):
            log.debug("Intent shortcut: rag_query (keyword match)")
            return IntentResult(
                intent=IntentType.RAG_QUERY,
                confidence=0.9,
                reasoning="Keyword-based classification",
            )
        if any(kw in text for kw in self._CHAT_KEYWORDS):
            log.debug("Intent shortcut: general_chat (keyword match)")
            return IntentResult(
                intent=IntentType.GENERAL_CHAT,
                confidence=0.9,
                reasoning="Keyword-based classification",
            )
        return None

    def classify(self, query: str) -> IntentResult:
        """
        Classify user intent synchronously.

        Args:
            query: User's input query

        Returns:
            IntentResult with classified intent and confidence
        """
        log.debug(f"Classifying intent for: {query[:50]}...")

        for attempt in range(self.config.max_retries + 1):
            try:
                start_time = time.perf_counter()

                result = self.chain.invoke({"query": query})

                elapsed = (time.perf_counter() - start_time) * 1000
                log.info(
                    f"Intent classified: {result.intent.value} "
                    f"(confidence={result.confidence:.2f}, elapsed={elapsed:.1f}ms)"
                )

                return result

            except Exception as e:
                log.warning(f"Classification attempt {attempt + 1} failed: {e}")

                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    log.error(f"Intent classification failed, using fallback: {self.config.fallback_intent}")
                    return IntentResult(
                        intent=self.config.fallback_intent,
                        confidence=0.0,
                        reasoning=f"Classification failed: {str(e)}",
                        suggested_action="Proceed with fallback handling"
                    )

        return IntentResult(intent=self.config.fallback_intent, confidence=0.0)

    async def aclassify(self, query: str) -> IntentResult:
        """
        Classify user intent asynchronously.

        Args:
            query: User's input query

        Returns:
            IntentResult with classified intent and confidence
        """
        log.debug(f"Async classifying intent for: {query[:50]}...")

        # Fast path: keyword-based classification to skip LLM call
        result = self._keyword_classify(query)
        if result is not None:
            return result

        for attempt in range(self.config.max_retries + 1):
            try:
                start_time = time.perf_counter()

                result = await self.chain.ainvoke({"query": query})

                elapsed = (time.perf_counter() - start_time) * 1000
                log.info(
                    f"Intent classified: {result.intent.value} "
                    f"(confidence={result.confidence:.2f}, elapsed={elapsed:.1f}ms)"
                )

                return result

            except Exception as e:
                log.warning(f"Async classification attempt {attempt + 1} failed: {e}")

                if attempt < self.config.max_retries:
                    import asyncio
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    log.error(f"Intent classification failed, using fallback: {self.config.fallback_intent}")
                    return IntentResult(
                        intent=self.config.fallback_intent,
                        confidence=0.0,
                        reasoning=f"Classification failed: {str(e)}",
                        suggested_action="Proceed with fallback handling"
                    )

        return IntentResult(intent=self.config.fallback_intent, confidence=0.0)


# Module-level classifier instance (lazy loaded)
_classifier_instance: Optional[IntentClassifier] = None


def get_intent_classifier() -> IntentClassifier:
    """Get or create the intent classifier instance."""
    global _classifier_instance

    if _classifier_instance is None:
        from models.llm_models import get_llm
        _classifier_instance = IntentClassifier(llm=get_llm())
        log.debug("Created new IntentClassifier instance")

    return _classifier_instance


def classify_intent(query: str) -> IntentResult:
    """Convenience function for intent classification."""
    return get_intent_classifier().classify(query)