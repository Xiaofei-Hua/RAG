from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class EvalCase:
    id: str = ""
    query: str = ""
    expected_sections: List[str] = field(default_factory=list)
    expected_keywords: List[str] = field(default_factory=list)
    expected_intent: str = "rag_query"
    expected_min_sources: int = 0
    difficulty: str = "medium"


@dataclass
class EvalScore:
    section_coverage: float = 0.0
    keyword_coverage: float = 0.0
    intent_accuracy: bool = False
    source_count_ok: bool = False
    overall_score: float = 0.0
    details: Dict = field(default_factory=dict)


@dataclass
class EvalResult:
    case_id: str = ""
    score: EvalScore = field(default_factory=EvalScore)
    actual_answer: str = ""
    actual_intent: str = ""
    actual_sources: int = 0
    execution_time_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class EvalReport:
    timestamp: float = field(default_factory=time.time)
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    average_score: float = 0.0
    results: List[EvalResult] = field(default_factory=list)
