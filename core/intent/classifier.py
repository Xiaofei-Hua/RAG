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
INTENT_CLASSIFICATION_PROMPT = """你是一个意图分类专家，负责分析用户输入并判断其意图类型。

## 意图类型说明：
1. **rag_query**: 用户需要查询知识库中的专业信息，涉及半导体、芯片、封装、测试等技术问题
2. **general_chat**: 普通对话，如问候、闲聊、一般性问题
3. **doc_upload**: 用户想要上传文档，如"帮我上传文件"、"添加新文档"
4. **system_cmd**: 系统管理命令，如"清除缓存"、"查看状态"、"帮助"

## 分类规则：
- 如果问题涉及专业术语、技术细节、具体知识 → rag_query
- 如果是问候、闲聊、非专业问题 → general_chat
- 如果明确提到上传/添加文档 → doc_upload
- 如果是系统操作或帮助请求 → system_cmd

## 用户输入：
{query}

请分析用户意图并返回分类结果。"""


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